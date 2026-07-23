from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        project_root=Path(__file__).resolve().parents[2],
        data_dir=tmp_path / "data",
        fixture_jobs_path=Path(__file__).parent / "fixtures" / "jobs.json",
        bootstrap_token="test-bootstrap-token",
        request_timeout_seconds=2,
        runtime_timeout_seconds=5,
        local_hiring_agent_enabled=False,
    )


@pytest.fixture()
def client(settings: Settings):
    application = create_app(settings)
    with TestClient(application) as test_client:
        session = test_client.get(
            "/api/session",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "X-Carivyo-Bootstrap": "test-bootstrap-token",
            },
        )
        assert session.status_code == 200
        token = session.json()["token"]
        test_client.headers.update(
            {
                "Origin": "http://127.0.0.1:5173",
                "X-Carivyo-Session": token,
            }
        )
        yield test_client
