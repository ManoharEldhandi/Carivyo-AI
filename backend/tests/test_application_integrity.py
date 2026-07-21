from __future__ import annotations

import pytest

from app.services.resume import ResumeRunBlocked
from app.utils import stable_hash


def _seed_application_context(client, monkeypatch) -> None:
    database = client.app.state.container.database
    database.execute(
        """
        INSERT INTO connectors(
            id, connector_type, name, source_domain, config_json,
            trust_tier, parser_version
        ) VALUES ('connector-application-integrity', 'fixture', 'Fixture',
                  'example.com', '{}', 'official', 'test-1')
        """
    )
    description = "Build and maintain reliable backend APIs."
    database.execute(
        """
        INSERT INTO jobs(
            id, connector_id, external_id, canonical_key, title, company,
            description, description_hash, location, apply_url, source_url,
            source_family
        ) VALUES (
            'job-application-integrity', 'connector-application-integrity',
            'external-application-integrity', 'application-integrity-key',
            'Backend Engineer', 'Example Labs', ?, ?, 'Remote India',
            'https://example.com/apply', 'https://example.com/job', 'fixture'
        )
        """,
        (description, stable_hash(description)),
    )
    for run_id in ("approved-run-1", "approved-run-2"):
        database.execute(
            """
            INSERT INTO resume_runs(
                id, job_id, status, stage, mode, custom_instructions,
                workspace_path, jd_hash, profile_version
            ) VALUES (?, 'job-application-integrity', 'ready_to_apply',
                      'complete', 'build', '', ?, ?, 'profile-v1')
            """,
            (run_id, f"/tmp/{run_id}", stable_hash(description)),
        )

    async def revalidate(job_id: str):
        assert job_id == "job-application-integrity"
        return {"id": job_id, "live_state": "live"}

    def verify_ready_for_handoff(run_id: str):
        assert run_id in {"approved-run-1", "approved-run-2"}
        return {
            "id": run_id,
            "job_id": "job-application-integrity",
            "status": "ready_to_apply",
            "result": {
                "variant": 1,
                "provenance": {"pdf_hash": f"pdf-hash-{run_id}"},
            },
        }

    container = client.app.state.container
    monkeypatch.setattr(container.search, "revalidate", revalidate)
    monkeypatch.setattr(
        container.resumes,
        "verify_ready_for_handoff",
        verify_ready_for_handoff,
    )


def test_prepare_omissions_preserve_approved_resume_and_notes(client, monkeypatch):
    _seed_application_context(client, monkeypatch)
    endpoint = "/api/jobs/job-application-integrity/prepare-application"
    original = client.post(
        endpoint,
        json={"resume_run_id": "approved-run-1", "notes": "Manual review needed."},
    )
    assert original.status_code == 200, original.text

    repeated = client.post(endpoint, json={})

    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == original.json()["id"]
    assert repeated.json()["resume_run_id"] == "approved-run-1"
    assert repeated.json()["notes"] == "Manual review needed."


def test_preserved_resume_is_reverified_for_prepare_and_open(client, monkeypatch):
    _seed_application_context(client, monkeypatch)
    endpoint = "/api/jobs/job-application-integrity/prepare-application"
    assert client.post(
        endpoint,
        json={"resume_run_id": "approved-run-1"},
    ).status_code == 200

    calls = []

    def invalid_resume(run_id: str):
        calls.append(run_id)
        raise ResumeRunBlocked("Approved resume artifacts changed")

    monkeypatch.setattr(
        client.app.state.container.resumes,
        "verify_ready_for_handoff",
        invalid_resume,
    )

    repeated = client.post(endpoint, json={})
    opened = client.post("/api/jobs/job-application-integrity/open-apply", json={})

    assert repeated.status_code == 409
    assert opened.status_code == 409
    assert calls == ["approved-run-1", "approved-run-1"]


@pytest.mark.parametrize("locked_status", ["applied", "interview"])
def test_prepare_cannot_reassociate_resume_after_submission(
    client,
    monkeypatch,
    locked_status,
):
    _seed_application_context(client, monkeypatch)
    endpoint = "/api/jobs/job-application-integrity/prepare-application"
    prepared = client.post(
        endpoint,
        json={"resume_run_id": "approved-run-1", "notes": "Original notes."},
    )
    assert prepared.status_code == 200, prepared.text
    application_id = prepared.json()["id"]

    applied = client.patch(
        f"/api/applications/{application_id}",
        json={"status": "applied", "notes": "Submitted."},
    )
    assert applied.status_code == 200, applied.text
    if locked_status == "interview":
        interviewing = client.patch(
            f"/api/applications/{application_id}",
            json={"status": "interview"},
        )
        assert interviewing.status_code == 200, interviewing.text

    reassociation = client.post(
        endpoint,
        json={"resume_run_id": "approved-run-2", "notes": "Mutated notes."},
    )

    assert reassociation.status_code == 409
    assert "resume association is immutable" in reassociation.json()["detail"]
    persisted = client.app.state.container.applications.get(application_id)
    assert persisted["status"] == locked_status
    assert persisted["resume_run_id"] == "approved-run-1"
    assert persisted["notes"] == "Submitted."


def test_submitted_application_rejects_changed_artifact_in_the_same_run(
    client, monkeypatch
):
    _seed_application_context(client, monkeypatch)
    endpoint = "/api/jobs/job-application-integrity/prepare-application"
    prepared = client.post(endpoint, json={"resume_run_id": "approved-run-1"})
    assert prepared.status_code == 200, prepared.text
    application_id = prepared.json()["id"]
    assert client.patch(
        f"/api/applications/{application_id}", json={"status": "applied"}
    ).status_code == 200

    def changed_artifact(run_id: str):
        return {
            "id": run_id,
            "job_id": "job-application-integrity",
            "status": "ready_to_apply",
            "result": {
                "variant": 2,
                "provenance": {"pdf_hash": "changed-pdf-hash"},
            },
        }

    monkeypatch.setattr(
        client.app.state.container.resumes,
        "verify_ready_for_handoff",
        changed_artifact,
    )
    changed = client.post(endpoint, json={"resume_run_id": "approved-run-1"})

    assert changed.status_code == 409
    assert "association is immutable" in changed.json()["detail"]
    persisted = client.app.state.container.applications.get(application_id)
    assert persisted["resume_variant"] == 1
    assert persisted["resume_pdf_hash"] == "pdf-hash-approved-run-1"
