from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.config import Settings
from app.security import SessionSecurity
from app.schemas import RuntimeProvider
from app.services.runtime import RuntimeGateway, RuntimeUnavailable


def test_runtime_rejects_unreviewed_per_message_model(settings, monkeypatch):
    gateway = RuntimeGateway(settings)
    monkeypatch.setattr(gateway, "resolve_provider", lambda _provider: "codex")

    with pytest.raises(RuntimeUnavailable, match="reviewed catalog"):
        gateway.run_chat("hello", provider="codex", model="not-in-catalog")


def test_ollama_cloud_pointers_are_not_reported_as_local(settings, monkeypatch):
    payload = {
        "models": [
            {
                "name": "cloud-model:cloud",
                "remote_host": "https://ollama.com",
                "remote_model": "cloud-model",
            },
            {"name": "llama-local:latest", "size": 4_000_000_000},
        ]
    }
    assert RuntimeGateway._local_ollama_model_names(payload) == [
        "llama-local:latest"
    ]

    gateway = RuntimeGateway(settings)
    monkeypatch.setattr(
        gateway,
        "_available_local_ollama_models",
        lambda: ["llama-local:latest"],
    )
    assert gateway.selection() == {
        "provider": "codex",
        "model": settings.codex_model,
        "reasoning_effort": "low",
        "fully_local": False,
    }


def test_codex_discovery_requires_authentication(settings, monkeypatch):
    gateway = RuntimeGateway(settings)
    monkeypatch.setattr(gateway, "_codex_executable", lambda: Path("/fake/codex"))

    def fake_run(command, **_kwargs):
        if command[-2:] == ["login", "status"]:
            return subprocess.CompletedProcess(command, 1, "", "Not logged in")
        return subprocess.CompletedProcess(command, 0, "codex-cli 1.2.3", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = gateway._probe_cli("codex", "Codex CLI", True, True)

    assert provider.available is False
    assert provider.authenticated is False
    assert provider.supports_sessions is False


def test_fully_local_mode_never_falls_back_to_provider_runtime(settings, monkeypatch):
    gateway = RuntimeGateway(settings)
    monkeypatch.setattr(
        gateway,
        "selection",
        lambda: {
            "provider": "ollama",
            "model": "local-model",
            "reasoning_effort": "none",
            "fully_local": True,
        },
    )
    monkeypatch.setattr(
        gateway,
        "discover",
        lambda: [
            RuntimeProvider(
                id="codex",
                name="Codex",
                kind="cli",
                available=True,
                privacy="provider",
            )
        ],
    )

    with pytest.raises(RuntimeUnavailable, match="Ollama has no available local model"):
        gateway.resolve_provider("auto")


def test_newest_codex_binary_is_selected(tmp_path, monkeypatch):
    old = tmp_path / "old-codex"
    newer = tmp_path / "new-codex"
    old.touch()
    newer.touch()
    monkeypatch.setattr("app.services.runtime.shutil.which", lambda _name: str(old))
    monkeypatch.setattr(RuntimeGateway, "CODEX_BUNDLED_PATHS", (newer,))

    def fake_run(command, **_kwargs):
        output = "codex-cli 0.145.0" if command[0] == str(newer) else "codex-cli 0.138.0"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert RuntimeGateway._codex_executable() == newer.resolve()


def test_settings_reject_non_loopback_bind(tmp_path):
    with pytest.raises(ValidationError, match="loopback"):
        Settings(project_root=tmp_path, data_dir=tmp_path / "data", host="0.0.0.0")


def test_session_security_rejects_non_loopback_peer():
    security = SessionSecurity.create(
        ["http://127.0.0.1:5173"],
        "bootstrap",
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/session",
            "headers": [(b"origin", b"http://127.0.0.1:5173")],
            "client": ("192.0.2.10", 50000),
            "server": ("127.0.0.1", 8420),
            "scheme": "http",
            "query_string": b"",
        }
    )

    with pytest.raises(Exception, match="loopback clients"):
        security.require_bootstrap(request, "bootstrap")


def test_session_endpoint_requires_private_launch_token(client):
    response = client.get("/api/session")

    assert response.status_code == 401
    assert "launch session expired" in response.json()["detail"]


def test_codex_runtime_disables_agent_tools_and_redacts_failures(settings, monkeypatch):
    gateway = RuntimeGateway(settings)
    monkeypatch.setattr(
        gateway,
        "_resolved_codex_executable",
        lambda: Path("/usr/local/bin/codex"),
    )
    commands = []

    def successful_run(command, **_kwargs):
        commands.append(command)
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("Safe response", encoding="utf-8")
        return subprocess.CompletedProcess(
            command,
            0,
            '{"type":"thread.started","thread_id":"safe-session"}\n',
            "",
        )

    monkeypatch.setattr(subprocess, "run", successful_run)
    result = gateway._run_codex("Untrusted text", None, "chat", "gpt-5.6-terra", "low")

    disabled = {
        commands[0][index + 1]
        for index, value in enumerate(commands[0][:-1])
        if value == "--disable"
    }
    assert {"shell_tool", "unified_exec", "apps", "browser_use", "computer_use"} <= disabled
    assert result["provider_session_id"] == "safe-session"

    def failed_run(command, **_kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            "",
            "secret-token=must-not-leak",
        )

    monkeypatch.setattr(subprocess, "run", failed_run)
    with pytest.raises(RuntimeUnavailable) as caught:
        gateway._run_codex("hello", None, "chat", "gpt-5.6-terra", "low")
    assert "must-not-leak" not in str(caught.value)
