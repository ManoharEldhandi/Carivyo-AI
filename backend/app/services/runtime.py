from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.config import Settings
from app.db import Database
from app.schemas import RuntimeProvider
from app.schemas import RuntimeModel
from app.utils import estimate_tokens, json_dumps, json_loads, new_id


class RuntimeUnavailable(RuntimeError):
    pass


class RuntimeGateway:
    ALLOWED_EXECUTABLES = {"codex", "ollama"}
    CODEX_BUNDLED_PATHS = (
        Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    )
    def __init__(self, settings: Settings, database: Optional[Database] = None):
        self.settings = settings
        self.database = database
        self._codex_path_resolved = False
        self._codex_path: Optional[Path] = None
        self._model_catalog: Optional[Tuple[RuntimeModel, ...]] = None
        self._provider_cache: Optional[Tuple[RuntimeProvider, ...]] = None
        self._provider_cache_at = 0.0

    def discover(self) -> List[RuntimeProvider]:
        now = time.monotonic()
        if self._provider_cache is None or now - self._provider_cache_at > 30:
            self._provider_cache = tuple(
                [
                    self._probe_cli(
                        "codex",
                        "Codex CLI",
                        supports_sessions=True,
                        adapter_enabled=True,
                    ),
                    self._probe_cli(
                        "claude",
                        "Claude Code",
                        supports_sessions=True,
                        adapter_enabled=False,
                    ),
                    self._probe_cli(
                        "gemini",
                        "Gemini CLI",
                        supports_sessions=True,
                        adapter_enabled=False,
                    ),
                    self._probe_cli(
                        "opencode",
                        "OpenCode",
                        supports_sessions=True,
                        adapter_enabled=False,
                    ),
                    self._probe_ollama(),
                ]
            )
            self._provider_cache_at = now
        providers = [provider.model_copy(deep=True) for provider in self._provider_cache]
        selection = self.selection()
        for provider in providers:
            if provider.id == selection["provider"]:
                provider.selected_model = selection["model"]
                provider.selected_reasoning_effort = selection["reasoning_effort"]
        return providers

    def _probe_cli(
        self,
        executable: str,
        name: str,
        supports_sessions: bool,
        adapter_enabled: bool,
    ) -> RuntimeProvider:
        codex_path = self._resolved_codex_executable() if executable == "codex" else None
        path = str(codex_path) if codex_path else shutil.which(executable)
        if not path:
            return RuntimeProvider(
                id=executable,
                name=name,
                kind="cli",
                available=False,
                supports_sessions=supports_sessions,
                privacy="provider",
            )
        detail = path
        authenticated: Optional[bool] = None
        try:
            result = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            detail = (result.stdout or result.stderr or path).strip()[:300]
        except (OSError, subprocess.SubprocessError):
            pass
        if executable == "codex" and adapter_enabled:
            try:
                auth = subprocess.run(
                    [path, "login", "status"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
                auth_detail = (auth.stdout or auth.stderr or "").strip()
                authenticated = auth.returncode == 0 and "logged in" in auth_detail.casefold()
                if not authenticated:
                    detail = f"{detail} · Codex authentication is unavailable"
            except (OSError, subprocess.SubprocessError):
                authenticated = False
                detail = f"{detail} · Codex authentication check failed"
        return RuntimeProvider(
            id=executable,
            name=name,
            kind="cli",
            available=adapter_enabled and authenticated is not False,
            authenticated=authenticated,
            supports_sessions=supports_sessions and adapter_enabled and authenticated is not False,
            supports_usage=False,
            privacy="provider",
            detail=(
                detail
                if adapter_enabled
                else f"{detail} · detected, but no controlled Carivyo adapter is enabled"
            ),
            models=list(self._codex_models()) if executable == "codex" and adapter_enabled else [],
        )

    def _probe_ollama(self) -> RuntimeProvider:
        path = shutil.which("ollama")
        if not path:
            return RuntimeProvider(
                id="ollama",
                name="Ollama",
                kind="local_endpoint",
                available=False,
                privacy="local",
            )
        try:
            response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
            response.raise_for_status()
            models = self._local_ollama_model_names(response.json())
            return RuntimeProvider(
                id="ollama",
                name="Ollama",
                kind="local_endpoint",
                available=bool(models),
                authenticated=True,
                supports_sessions=False,
                supports_usage=True,
                privacy="local",
                detail=", ".join(models[:5]) if models else "No local models installed",
                models=[
                    RuntimeModel(
                        id=model,
                        name=model,
                        profile="local",
                        recommended=index == 0,
                        detail="Runs through the local Ollama service.",
                        reasoning_efforts=["none"],
                        use_cases=[
                            "chat",
                            "resume_review",
                            "hiring_manager_simulation",
                        ],
                    )
                    for index, model in enumerate(models)
                ],
            )
        except httpx.HTTPError:
            return RuntimeProvider(
                id="ollama",
                name="Ollama",
                kind="local_endpoint",
                available=False,
                authenticated=False,
                supports_usage=True,
                privacy="local",
                detail="Ollama is installed but its local service is unavailable",
            )

    def selection(self) -> Dict[str, Any]:
        catalog = self._codex_models()
        configured_default = next(
            (model.id for model in catalog if model.id == self.settings.codex_model),
            next(model.id for model in catalog if model.recommended),
        )
        local_models = self._available_local_ollama_models()
        configured_local = self.settings.ollama_model
        local_default = (
            configured_local
            if configured_local in local_models
            else (local_models[0] if local_models else None)
        )
        default = (
            {
                "provider": "ollama",
                "model": local_default or configured_local or "",
                "reasoning_effort": "none",
                "fully_local": True,
            }
            if self.settings.fully_local_mode
            else
            {
                "provider": "ollama",
                "model": local_default,
                "reasoning_effort": "none",
                "fully_local": bool(self.settings.fully_local_mode),
            }
            if local_default
            else {
                "provider": "codex",
                "model": configured_default,
                "reasoning_effort": "low",
                "fully_local": False,
            }
        )
        if not self.database:
            return default
        row = self.database.fetch_one(
            "SELECT value_json FROM settings WHERE key = 'runtime_selection'"
        )
        stored = json_loads(row["value_json"], {}) if row else {}
        selection = {**default, **stored}
        if selection.get("fully_local"):
            selection["provider"] = "ollama"
            selection["reasoning_effort"] = "none"
            if local_default:
                selection["model"] = local_default
        return selection

    def configure(
        self,
        provider: str,
        model: str,
        reasoning_effort: str,
        fully_local: bool = False,
    ) -> Dict[str, Any]:
        available_providers = {
            item.id: item for item in self.discover() if item.available
        }
        resolved_provider = (
            "ollama"
            if fully_local and provider == "auto"
            else provider
            if provider != "auto"
            else "ollama"
            if "ollama" in available_providers
            else "codex"
        )
        if fully_local and resolved_provider != "ollama":
            raise ValueError("Fully local mode requires an installed Ollama model")
        available = available_providers.get(resolved_provider)
        if not available:
            raise ValueError(f"{resolved_provider} is not available")
        allowed_models = {item.id for item in available.models}
        if model not in allowed_models:
            raise ValueError(
                f"{model} is not an available model for {available.name}"
            )
        selected_model = next(item for item in available.models if item.id == model)
        if (
            available.id == "codex"
            and reasoning_effort not in selected_model.reasoning_efforts
        ):
            raise ValueError(
                f"{reasoning_effort} reasoning is not supported by {selected_model.name}"
            )
        selection = {
            "provider": resolved_provider,
            "model": model,
            "reasoning_effort": reasoning_effort,
            "fully_local": fully_local,
        }
        if self.database:
            self.database.execute(
                """
                INSERT INTO settings(key, value_json) VALUES ('runtime_selection', ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (json_dumps(selection),),
            )
        return selection

    def run_chat(
        self,
        prompt: str,
        provider: str = "auto",
        session_id: Optional[str] = None,
        session_key: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
    ) -> Dict[str, Any]:
        selected = self.resolve_provider(provider)
        configured = self.selection()
        selected_model = model or (
            configured["model"] if configured["provider"] == selected else None
        )
        selected_effort = reasoning_effort or configured["reasoning_effort"]
        if selected == "ollama":
            return self._run_ollama(prompt, selected_model)
        if selected == "codex":
            catalog = {item.id: item for item in self._codex_models()}
            allowed_models = set(catalog)
            if selected_model not in allowed_models:
                raise RuntimeUnavailable(
                    f"The selected Codex model {selected_model} is not in Carivyo's reviewed catalog"
                )
            if selected_effort not in catalog[selected_model].reasoning_efforts:
                raise RuntimeUnavailable(
                    f"{selected_effort} reasoning is not supported by {catalog[selected_model].name}"
                )
            return self._run_codex(
                prompt,
                session_id,
                session_key,
                selected_model or self.settings.codex_model,
                selected_effort,
            )
        raise RuntimeUnavailable(f"{selected} has no controlled adapter")

    def resolve_provider(self, provider: str = "auto") -> str:
        available = {item.id: item for item in self.discover() if item.available}
        fully_local = bool(self.selection().get("fully_local"))
        if fully_local:
            if "ollama" not in available:
                raise RuntimeUnavailable(
                    "Fully local mode is enabled, but Ollama has no available local model"
                )
            if provider not in {"auto", "ollama"}:
                raise RuntimeUnavailable(
                    "Fully local mode blocks provider-backed model execution"
                )
            return "ollama"
        selected = provider
        if provider == "auto":
            configured = self.selection()["provider"]
            if configured != "auto" and configured in available:
                selected = configured
            else:
                selected = "ollama" if "ollama" in available else "codex"
        if selected not in available:
            raise RuntimeUnavailable(f"{selected} is not available")
        return selected

    def _run_ollama(self, prompt: str, model: Optional[str]) -> Dict[str, Any]:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).json()
        models = self._local_ollama_model_names(tags)
        if not models:
            raise RuntimeUnavailable("Ollama has no installed model")
        selected_model = model or models[0]
        if selected_model not in models:
            raise RuntimeUnavailable(
                f"The selected Ollama model {selected_model} is no longer installed"
            )
        started = time.perf_counter()
        response = httpx.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": selected_model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"num_predict": self.settings.max_chat_output_tokens},
            },
            timeout=self.settings.runtime_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = ((payload.get("message") or {}).get("content") or "").strip()
        return {
            "provider": "ollama",
            "model": payload.get("model") or selected_model,
            "content": content,
            "input_tokens": int(payload.get("prompt_eval_count") or estimate_tokens(prompt)),
            "output_tokens": int(payload.get("eval_count") or estimate_tokens(content)),
            "cache_read_tokens": 0,
            "usage_kind": "measured"
            if payload.get("prompt_eval_count") is not None
            else "estimated",
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    def run_structured(
        self,
        prompt: str,
        schema: Dict[str, Any],
        *,
        provider: str = "ollama",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_output_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Run a bounded JSON-schema request through an on-device Ollama model."""

        if provider != "ollama":
            raise RuntimeUnavailable(
                "Structured hiring evaluation is restricted to the local Ollama adapter"
            )
        if not schema:
            raise RuntimeUnavailable("Structured output requires a validation schema")
        local_models = self._available_local_ollama_models()
        if not local_models:
            raise RuntimeUnavailable("Ollama has no installed on-device model")
        selected_model = model or (
            self.selection()["model"]
            if self.selection().get("provider") == "ollama"
            else local_models[0]
        )
        if selected_model not in local_models:
            raise RuntimeUnavailable(
                f"The selected Ollama model {selected_model} is not installed on device"
            )
        started = time.perf_counter()
        response = httpx.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": selected_model,
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                # JSON mode is materially faster across small local models than
                # grammar-compiling a large nested schema. The caller still
                # validates the decoded object against the supplied schema model.
                "format": "json",
                "options": {
                    "temperature": temperature,
                    "num_ctx": 2048,
                    "num_predict": min(
                        self.settings.max_chat_output_tokens,
                        max_output_tokens or 260,
                    ),
                },
            },
            timeout=self.settings.runtime_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = ((payload.get("message") or {}).get("content") or "").strip()
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeUnavailable(
                "The local model returned invalid structured JSON"
            ) from exc
        return {
            "provider": "ollama",
            "model": payload.get("model") or selected_model,
            "data": data,
            "content": content,
            "input_tokens": int(
                payload.get("prompt_eval_count") or estimate_tokens(prompt)
            ),
            "output_tokens": int(
                payload.get("eval_count") or estimate_tokens(content)
            ),
            "cache_read_tokens": 0,
            "usage_kind": (
                "measured"
                if payload.get("prompt_eval_count") is not None
                else "estimated"
            ),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    def local_model(self) -> Optional[str]:
        models = self._available_local_ollama_models()
        if self.settings.ollama_model in models:
            return self.settings.ollama_model
        return models[0] if models else None

    def _available_local_ollama_models(self) -> List[str]:
        try:
            response = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2)
            response.raise_for_status()
            return self._local_ollama_model_names(response.json())
        except (httpx.HTTPError, ValueError, TypeError):
            return []

    @staticmethod
    def _local_ollama_model_names(payload: Dict[str, Any]) -> List[str]:
        """Exclude Ollama cloud pointers from paths labelled as on-device AI."""

        result: List[str] = []
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if (
                not isinstance(name, str)
                or not name
                or item.get("remote_host")
                or item.get("remote_model")
            ):
                continue
            result.append(name)
        return result

    def _run_codex(
        self,
        prompt: str,
        session_id: Optional[str],
        session_key: Optional[str],
        model: str,
        reasoning_effort: str,
    ) -> Dict[str, Any]:
        executable_path = self._resolved_codex_executable()
        executable = str(executable_path) if executable_path else None
        if not executable:
            raise RuntimeUnavailable("Codex CLI is not installed")
        run_id = new_id()
        safe_session_key = re.sub(r"[^A-Za-z0-9_-]", "-", session_key or run_id)
        workspace = (
            self.settings.runtime_dir / "chat" / safe_session_key
        ).resolve()
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        workspace.chmod(0o700)
        output_path = workspace / f"response-{run_id}.txt"
        common = [
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--disable",
            "shell_tool",
            "--disable",
            "unified_exec",
            "--disable",
            "unified_exec_zsh_fork",
            "--disable",
            "apps",
            "--disable",
            "enable_mcp_apps",
            "--disable",
            "browser_use",
            "--disable",
            "browser_use_external",
            "--disable",
            "computer_use",
            "--disable",
            "in_app_browser",
            "--disable",
            "multi_agent",
            "--disable",
            "multi_agent_v2",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{reasoning_effort}"',
            "-c",
            'sandbox_mode="read-only"',
            "--json",
            "-o",
            str(output_path),
        ]
        if session_id:
            command = [
                executable,
                "exec",
                "resume",
                *common,
                session_id,
                prompt,
            ]
        else:
            command = [
                executable,
                "exec",
                *common,
                "-s",
                "read-only",
                "-C",
                str(workspace),
                prompt,
            ]
        if Path(command[0]).name not in self.ALLOWED_EXECUTABLES:
            raise RuntimeUnavailable("Runtime executable is not allowlisted")
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "CODEX_HOME": os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        }
        started = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                cwd=str(workspace),
                env=env,
                capture_output=True,
                text=True,
                timeout=self.settings.runtime_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeUnavailable("Codex chat timed out") from exc
        if result.returncode != 0 or not output_path.exists():
            raise RuntimeUnavailable("Codex runtime request failed")
        content = output_path.read_text(encoding="utf-8").strip()
        output_path.chmod(0o600)
        provider_session_id = session_id or self._codex_session_id(result.stdout)
        if not provider_session_id:
            raise RuntimeUnavailable(
                "Codex chat completed without a resumable session identifier"
            )
        return {
            "provider": "codex",
            "model": model,
            "content": content,
            "input_tokens": estimate_tokens(prompt),
            "output_tokens": estimate_tokens(content),
            "cache_read_tokens": 0,
            "usage_kind": "estimated",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "provider_session_id": provider_session_id,
            "session_reused": bool(session_id),
        }

    @classmethod
    def _codex_executable(cls) -> Optional[Path]:
        """Prefer the newest installed controlled Codex binary.

        The desktop app can ship a newer CLI than a package-manager PATH entry.
        Selecting by semantic version avoids false runtime failures caused by an
        older binary trying to read a newer shared model cache.
        """
        candidates: List[Path] = []
        path_entry = shutil.which("codex")
        if path_entry:
            candidates.append(Path(path_entry))
        candidates.extend(path for path in cls.CODEX_BUNDLED_PATHS if path.is_file())
        unique_candidates = list(dict.fromkeys(path.resolve() for path in candidates))
        if not unique_candidates:
            return None

        def version(path: Path) -> Tuple[int, ...]:
            try:
                result = subprocess.run(
                    [str(path), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return ()
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", result.stdout or result.stderr)
            return tuple(int(value) for value in match.groups()) if match else ()

        return max(unique_candidates, key=lambda candidate: (version(candidate), str(candidate)))

    def _resolved_codex_executable(self) -> Optional[Path]:
        if not self._codex_path_resolved:
            self._codex_path = self._codex_executable()
            self._codex_path_resolved = True
        return self._codex_path

    def _codex_models(self) -> Tuple[RuntimeModel, ...]:
        if self._model_catalog is not None:
            return self._model_catalog
        catalog_path = Path(__file__).resolve().parents[1] / "runtime_models.json"
        try:
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
            models = tuple(RuntimeModel.model_validate(item) for item in payload["models"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeUnavailable(
                f"The reviewed model catalog could not be loaded: {exc}"
            ) from exc
        if not models or sum(1 for model in models if model.recommended) != 1:
            raise RuntimeUnavailable(
                "The reviewed model catalog must contain exactly one recommended default"
            )
        self._model_catalog = models
        return models

    @staticmethod
    def _codex_session_id(stdout: str) -> Optional[str]:
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") in {"thread.started", "thread_started"}:
                return (
                    event.get("thread_id")
                    or event.get("threadId")
                    or event.get("session_id")
                )
        return None
