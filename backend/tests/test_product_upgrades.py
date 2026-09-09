from __future__ import annotations

from datetime import timedelta

import pytest

from test_integration import RESUME, complete_onboarding


@pytest.mark.asyncio
async def test_opt_in_schedule_runs_a_due_saved_priority_search(client, monkeypatch):
    defaults = client.get("/api/search-schedule")
    assert defaults.status_code == 200
    assert defaults.json()["enabled"] is False
    assert defaults.json()["requires_open_service"] is True

    complete_onboarding(client, RESUME)
    configured = client.put(
        "/api/search-schedule",
        json={
            "enabled": True,
            "cadence": "weekly",
            "weekday": 2,
            "time": "09:15",
            "notify": True,
        },
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["next_run_at"]
    assert configured.json()["notify"] is True

    schedule = client.app.state.container.schedule
    due = schedule._stored()
    due["next_run_at"] = (schedule._now() - timedelta(minutes=1)).isoformat()
    schedule._save(due)
    calls: list[str] = []

    def create_run(*, reason: str):
        calls.append(reason)
        return {"id": "scheduled-search"}

    async def run(_run_id: str) -> None:
        return None

    monkeypatch.setattr(schedule.search, "create_run", create_run)
    monkeypatch.setattr(schedule.search, "run", run)
    monkeypatch.setattr(
        schedule.search,
        "run_status",
        lambda _run_id: {"id": "scheduled-search", "status": "complete", "error": None},
    )

    assert await schedule.tick() == "scheduled-search"
    assert schedule._task is not None
    await schedule._task
    state = schedule.state()
    assert calls == ["scheduled"]
    assert state["last_run_id"] == "scheduled-search"
    assert state["last_status"] == "complete"
    assert state["last_completed_at"]


def test_feedback_reranks_similar_roles_and_explains_fit(client):
    complete_onboarding(client, RESUME)
    jobs = client.get("/api/jobs").json()["jobs"]
    selected = jobs[0]

    response = client.post(
        f"/api/jobs/{selected['id']}/feedback",
        json={"action": "save"},
    )
    assert response.status_code == 200, response.text

    container = client.app.state.container
    reranked = container.matching.score(
        selected,
        selected["freshness_class"],
        container.plans.active()["plan"],
    )
    assert reranked["factors"]["feedback_fit"] > 0
    assert any(item["code"] == "feedback_learning" for item in reranked["reasons"])

    detail = client.get(f"/api/jobs/{selected['id']}")
    assert detail.status_code == 200, detail.text
    why = detail.json()["why_this_job"]
    assert set(why) >= {"summary", "proven", "priority_alignment", "unknowns", "gaps"}
    assert why["proven"] or why["priority_alignment"]


@pytest.mark.parametrize(
    ("template", "template_id"),
    [
        ("balanced", "carivyo-ats-a4-tex-v2"),
        ("ai", "carivyo-ats-a4-ai-v1"),
        ("software", "carivyo-ats-a4-software-v1"),
    ],
)
def test_each_resume_template_generates_a_validated_truthful_run(client, template, template_id):
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]

    response = client.post(
        f"/api/jobs/{job['id']}/resume-runs",
        json={
            "template": template,
            "custom_instructions": "Keep one page and prioritize requirements I can prove.",
        },
    )

    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "needs_user_review"
    assert run["result"]["template"]["id"] == template_id
    assert run["result"]["validation"]["export_ok"] is True
    assert run["result"]["validation"]["evidence_ok"] is True
    assert run["result"]["validation"]["page_count_ok"] is True
