from __future__ import annotations

import json
from typing import Any, Dict

from test_integration import RESUME, SECOND_RESUME, complete_onboarding
from app.services.onboarding import OnboardingService


THIRD_RESUME = """
Taylor Draft
taylor.draft@example.com | +91 92222 22222 | https://github.com/taylor-draft

SUMMARY
Platform engineer focused on Kubernetes infrastructure and Go services.

SKILLS
Go, Kubernetes, Terraform, Docker, PostgreSQL, Git

EXPERIENCE
Built Go services and Kubernetes deployment automation for a platform team.

PROJECTS
Created Terraform modules with deterministic policy validation.

EDUCATION
Bachelor of Technology in Computer Science.
""".strip()


def _preference_values(client) -> Dict[str, Any]:
    return {
        item["key"]: item["value"]
        for item in client.get("/api/preferences").json()["preferences"]
    }


def _active_state(client) -> Dict[str, Any]:
    profile = client.get("/api/profile").json()
    preferences = client.get("/api/preferences").json()
    return {
        "profile_version": profile["version"],
        "profile": profile["profile"],
        "resume_base_ids": [item["id"] for item in profile["resume_bases"]],
        "evidence_ids": [item["id"] for item in profile["evidence"]],
        "preferences": preferences,
        "search_plan_version": profile["search_plan"]["version"],
        "search_plan": profile["search_plan"]["plan"],
    }


def _preview(client, resume: str = SECOND_RESUME, filename: str = "replacement.txt"):
    response = client.post(
        "/api/profile/resume/preview",
        files={"resume": (filename, resume.encode("utf-8"), "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _set_advanced_preferences(client) -> None:
    response = client.patch(
        "/api/preferences",
        json={
            "target_roles": ["Backend Engineer", "SDE I"],
            "preferred_locations": ["Hyderabad", "Remote India"],
            "work_modes": ["remote", "hybrid"],
            "seniority_tolerance": "0 to 2 years",
            "excluded_keywords": ["sales", "unpaid"],
            "excluded_locations": ["Singapore"],
            "preferred_industries": ["Developer Tools"],
            "preferred_companies": ["Acme"],
            "excluded_companies": ["Example Staffing"],
            "priority_skills": ["FastAPI", "PostgreSQL"],
            "employment_types": ["full_time"],
            "salary_min": 1_200_000,
            "salary_currency": "INR",
            "salary_period": "year",
            "location_policy": "strict",
            "freshness_hours": 72,
        },
    )
    assert response.status_code == 200, response.text


def test_preview_is_reviewable_deterministic_and_leaves_active_state_unchanged(client):
    complete_onboarding(client, RESUME)
    _set_advanced_preferences(client)
    before = _active_state(client)

    preview = _preview(client)

    assert preview["draft_id"] == preview["session_id"]
    assert preview["status"] == "needs_confirmation"
    assert preview["summary"]["name"] == "Jordan Current"
    assert set(preview["diff"]) == {
        "identity",
        "skills",
        "role_tracks",
        "highlights",
    }
    assert preview["diff"]["identity"]["changed"][0] == {
        "field": "name",
        "before": "Avery Candidate",
        "after": "Jordan Current",
    }
    assert preview["diff"]["skills"]["added"] == ["Selenium", "Spring Boot"]
    assert _active_state(client) == before

    database = client.app.state.container.database
    draft = database.fetch_one(
        "SELECT status, artifact_ids_json FROM onboarding_sessions WHERE id = ?",
        (preview["draft_id"],),
    )
    assert draft and draft["status"] == "needs_confirmation"
    artifact_id = json.loads(draft["artifact_ids_json"])[0]
    assert {
        row["approval"]
        for row in database.fetch_all(
            "SELECT approval FROM evidence_claims WHERE artifact_id = ?",
            (artifact_id,),
        )
    } == {"pending"}

    deprecated = client.post(
        "/api/profile/resume",
        files={"resume": ("replacement.txt", SECOND_RESUME, "text/plain")},
    )
    assert deprecated.status_code == 409
    assert "/api/profile/resume/preview" in deprecated.json()["detail"]
    assert _active_state(client) == before


def test_confirm_activates_reviewed_version_only_and_preserves_preferences(client):
    complete_onboarding(client, RESUME)
    _set_advanced_preferences(client)
    database = client.app.state.container.database
    before = _active_state(client)
    old_snapshot = database.fetch_one(
        "SELECT profile_json FROM profile_snapshots WHERE version = ?",
        (before["profile_version"],),
    )
    preview = _preview(client)
    unrelated_preview = _preview(client, THIRD_RESUME, "unrelated-draft.txt")
    draft_row = database.fetch_one(
        "SELECT artifact_ids_json FROM onboarding_sessions WHERE id = ?",
        (preview["draft_id"],),
    )
    unrelated_row = database.fetch_one(
        "SELECT artifact_ids_json FROM onboarding_sessions WHERE id = ?",
        (unrelated_preview["draft_id"],),
    )
    draft_artifact_id = json.loads(draft_row["artifact_ids_json"])[0]
    unrelated_artifact_id = json.loads(unrelated_row["artifact_ids_json"])[0]
    reviewed = {
        "name": "Jordan Reviewed",
        "email": "reviewed.jordan@example.com",
        "phone": "+91 93333 33333",
        "links": ["https://github.com/jordan-reviewed"],
        "skills": ["Java", "Spring Boot", "PostgreSQL"],
        "role_tracks": ["Backend Platform Engineer"],
        "highlights": ["Built reviewed, production-grade Java services."],
    }

    confirmed = client.post(
        "/api/profile/resume/confirm",
        json={"draft_id": preview["draft_id"], "profile_review": reviewed},
    )

    assert confirmed.status_code == 200, confirmed.text
    payload = confirmed.json()
    assert payload["status"] == "confirmed"
    assert payload["preserved_preferences"] is True
    assert payload["summary"] == reviewed
    assert payload["profile_version"] != before["profile_version"]
    profile = payload["profile"]["profile"]
    assert profile["identity"]["name"] == "Jordan Reviewed"
    assert profile["skills"] == reviewed["skills"]
    assert profile["role_families"] == reviewed["role_tracks"]
    assert profile["highlights"] == reviewed["highlights"]
    assert profile["confirmed_by_user"] is True
    assert profile["supersedes_profile_version"] == before["profile_version"]
    assert profile["source_artifact_ids"] == [draft_artifact_id]
    assert profile["resume_provenance"]["artifact_id"] == draft_artifact_id

    assert client.get("/api/preferences").json() == before["preferences"]
    assert _preference_values(client)["preferred_industries"] == ["Developer Tools"]
    plan = payload["search_plan"]
    assert plan["version"] != before["search_plan_version"]
    assert plan["plan"]["generated_from"]["profile_version"] == payload[
        "profile_version"
    ]
    assert plan["plan"]["generated_from"]["preference_version"] == before[
        "preferences"
    ]["version"]
    assert plan["plan"]["target_roles"] == [
        "Backend Engineer",
        "SDE I",
        "Backend Platform Engineer",
    ]
    assert plan["plan"]["skills"] == reviewed["skills"]
    assert database.fetch_one(
        "SELECT status FROM search_plans WHERE version = ?",
        (before["search_plan_version"],),
    )["status"] == "stale"

    active_evidence = payload["profile"]["evidence"]
    assert active_evidence
    assert {item["artifact_id"] for item in active_evidence} == {draft_artifact_id}
    assert {
        row["approval"]
        for row in database.fetch_all(
            "SELECT approval FROM evidence_claims WHERE artifact_id = ?",
            (unrelated_artifact_id,),
        )
    } == {"pending"}
    assert database.fetch_one(
        "SELECT profile_json FROM profile_snapshots WHERE version = ?",
        (before["profile_version"],),
    ) == old_snapshot
    activity = database.fetch_one(
        """
        SELECT reason, metadata_json FROM activity_events
        WHERE event_type = 'resume_replacement_confirmed'
        """
    )
    assert activity and activity["reason"] == "explicit_user_confirmation"
    provenance = json.loads(activity["metadata_json"])
    assert provenance["profile_version"] == payload["profile_version"]
    assert provenance["artifact_id"] == draft_artifact_id

    snapshot_count = database.fetch_one(
        "SELECT COUNT(*) AS count FROM profile_snapshots"
    )["count"]
    repeat = client.post(
        "/api/profile/resume/confirm",
        json={"session_id": preview["session_id"], "profile_review": reviewed},
    )
    assert repeat.status_code == 409
    assert "already confirmed" in repeat.json()["detail"]
    assert "no changes were applied" in repeat.json()["detail"]
    assert database.fetch_one(
        "SELECT COUNT(*) AS count FROM profile_snapshots"
    )["count"] == snapshot_count
    assert client.get("/api/profile").json()["version"] == payload["profile_version"]

    stale = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": unrelated_preview["draft_id"],
            "profile_review": unrelated_preview["summary"],
        },
    )
    assert stale.status_code == 409
    assert "active profile changed" in stale.json()["detail"]


def test_missing_invalid_and_malformed_confirmation_are_rejected(client):
    complete_onboarding(client, RESUME)
    profile = client.get("/api/profile").json()["profile"]
    valid_review = {
        "name": "Candidate",
        "skills": ["Python"],
        "role_tracks": ["Backend Engineer"],
        "highlights": [],
    }

    missing = client.post(
        "/api/profile/resume/confirm",
        json={"draft_id": "missing-draft", "profile_review": valid_review},
    )
    assert missing.status_code == 404

    invalid = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": profile["onboarding_session_id"],
            "profile_review": valid_review,
        },
    )
    assert invalid.status_code == 409
    assert "not a valid replacement resume draft" in invalid.json()["detail"]

    malformed = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": "anything",
            "profile_review": {
                "name": "Candidate",
                "skills": [],
                "role_tracks": [],
                "highlights": [],
            },
        },
    )
    assert malformed.status_code == 422

    whitespace_name = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": "anything",
            "profile_review": {
                "name": "   ",
                "skills": [],
                "role_tracks": ["Backend Engineer"],
                "highlights": [],
            },
        },
    )
    assert whitespace_name.status_code == 422

    mismatched = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": "draft-one",
            "session_id": "draft-two",
            "profile_review": valid_review,
        },
    )
    assert mismatched.status_code == 422


def test_profile_list_diff_reports_order_only_changes():
    diff = OnboardingService._list_diff(
        ["Backend Engineer", "AI Engineer"],
        ["AI Engineer", "Backend Engineer"],
    )

    assert diff["added"] == []
    assert diff["removed"] == []
    assert diff["changed"] == [
        {
            "before": "Backend Engineer, AI Engineer",
            "after": "AI Engineer, Backend Engineer",
        }
    ]


def test_extraction_failure_leaves_active_and_persisted_state_unchanged(client):
    complete_onboarding(client, RESUME)
    database = client.app.state.container.database
    before = _active_state(client)
    tables = (
        "source_artifacts",
        "onboarding_sessions",
        "evidence_claims",
        "resume_bases",
        "profile_snapshots",
        "preferences",
        "search_plans",
        "activity_events",
    )
    counts = {
        table: database.fetch_one(f"SELECT COUNT(*) AS count FROM {table}")["count"]
        for table in tables
    }

    failed = client.post(
        "/api/profile/resume/preview",
        files={"resume": ("empty.txt", b"too short", "text/plain")},
    )

    assert failed.status_code == 422
    assert "Not enough readable text" in failed.json()["detail"]
    assert _active_state(client) == before
    assert {
        table: database.fetch_one(f"SELECT COUNT(*) AS count FROM {table}")["count"]
        for table in tables
    } == counts
