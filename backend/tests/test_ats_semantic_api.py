from __future__ import annotations

from app.services.runtime import RuntimeUnavailable

from test_integration import RESUME, complete_onboarding


class UnavailableSemanticRuntime:
    def __init__(self):
        self.calls = 0

    def selection(self):
        return {"provider": "codex", "model": "gpt-5.6-terra", "reasoning_effort": "low"}

    def run_chat(self, *_args, **_kwargs):
        self.calls += 1
        raise RuntimeUnavailable("controlled unavailable runtime")


def test_semantic_review_api_is_explicit_advisory_and_score_preserving(client):
    assert (
        client.app.state.container.ats_semantic.stale_after_seconds
        == client.app.state.container.settings.runtime_timeout_seconds
    )
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]
    run_response = client.post(
        f"/api/jobs/{job['id']}/resume-runs",
        json={"custom_instructions": "Keep one page."},
    )
    assert run_response.status_code == 200, run_response.text
    run = run_response.json()
    score_before = run["result"]["ats_analysis"]["overall_score"]
    runtime = UnavailableSemanticRuntime()
    client.app.state.container.ats_semantic.runtime = runtime

    denied = client.post(
        f"/api/resume-runs/{run['id']}/ats-semantic-review",
        json={"provider": "codex"},
    )
    assert denied.status_code == 422
    assert runtime.calls == 0

    response = client.post(
        f"/api/resume-runs/{run['id']}/ats-semantic-review",
        json={
            "provider": "codex",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "low",
            "confirmed_full_document_processing": True,
        },
    )

    assert response.status_code == 200, response.text
    review = response.json()
    assert review["status"] == "failed"
    assert review["error"] == "AI runtime was unavailable"
    assert runtime.calls == 2
    analysis = client.get(
        f"/api/resume-runs/{run['id']}/ats-analysis"
    ).json()
    assert analysis["overall_score"] == score_before
    client.app.state.container.database.execute(
        """
        UPDATE ats_semantic_reviews
        SET status = 'running', response_json = NULL, attempt_count = 0,
            error_code = NULL, error = NULL, completed_at = NULL,
            updated_at = '2000-01-01 00:00:00'
        WHERE id = ?
        """,
        (review["id"],),
    )

    recovered_response = client.post(
        f"/api/resume-runs/{run['id']}/ats-semantic-review",
        json={
            "provider": "codex",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "low",
            "confirmed_full_document_processing": True,
        },
    )

    assert recovered_response.status_code == 200, recovered_response.text
    recovered = recovered_response.json()
    assert recovered["id"] != review["id"]
    assert recovered["status"] == "failed"
    assert recovered["error"] == "AI runtime was unavailable"
    assert runtime.calls == 4
    listed = client.get(
        f"/api/resume-runs/{run['id']}/ats-semantic-reviews"
    ).json()
    assert listed["count"] == 2
    assert all(
        item["metadata"]["authoritative"] is False
        for item in listed["reviews"]
    )
    stale = next(item for item in listed["reviews"] if item["id"] == review["id"])
    assert stale["status"] == "failed"
    assert stale["error_code"] == "stale_run"
