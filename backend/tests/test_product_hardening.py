from __future__ import annotations

from datetime import timedelta

from app.connectors.base import JobCandidate
from app.main import build_container
from app.services.preference_intelligence import (
    interpret_onboarding_answer,
    interpret_preference_message,
)
from app.services.search_plan import normalize_search_plan
from app.utils import new_id, utcnow

from test_integration import RESUME, SECOND_RESUME, complete_onboarding


def candidate(
    *,
    title: str = "Backend Software Engineer",
    location: str = "Hyderabad, India",
    work_mode: str = "hybrid",
    posted_hours_ago: int = 8,
) -> JobCandidate:
    return JobCandidate(
        connector_id="greenhouse-example",
        external_id=f"{title}-{location}",
        title=title,
        company="Example",
        description="Build Python APIs with FastAPI and PostgreSQL.",
        location=location,
        work_mode=work_mode,
        employment_type="Full-time",
        posted_at=(utcnow() - timedelta(hours=posted_hours_ago)).isoformat(),
        posted_semantics="first_published",
        apply_url="https://job-boards.greenhouse.io/example/jobs/1",
        source_url="https://job-boards.greenhouse.io/example/jobs/1",
        source_family="greenhouse",
        raw={},
    )


def strict_plan() -> dict:
    return {
        "target_roles": ["Backend Engineer", "Software Engineer I"],
        "role_aliases": [
            "Backend Engineer",
            "Backend Developer",
            "API Engineer",
            "Software Engineer",
            "SDE",
        ],
        "locations": ["Hyderabad", "Bengaluru", "Remote India"],
        "excluded_locations": [],
        "work_modes": ["remote", "hybrid", "onsite"],
        "seniority_tolerance": "Fresher to 2 years",
        "excluded_keywords": ["sales", "unpaid"],
        "freshness_hours": 48,
        "source_families": ["greenhouse", "lever", "ashby"],
    }


def test_legacy_search_plan_shapes_gain_safe_strict_freshness_defaults():
    plan = normalize_search_plan(
        {
            "target_roles": ["Backend Engineer"],
            "locations": ["Hyderabad", "Remote India"],
            "work_mode": "Remote or hybrid",
            "freshness_hours": [48],
        }
    )

    assert plan["target_roles"] == ["Backend Engineer"]
    assert plan["locations"] == ["Hyderabad", "Remote India"]
    assert plan["work_modes"] == ["remote", "hybrid"]
    assert plan["freshness_hours"] == 48
    assert plan["location_policy"] == "preference_order"
    assert plan["role_policy"] == "expanded_early_career"
    assert plan["freshness_policy"] == "strict"
    assert plan["metadata_policy"] == "include_unknown"


def test_onboarding_interprets_ranked_locations_and_modes_semantically():
    locations = interpret_onboarding_answer(
        "preferred_locations",
        "Hyderabad first, Bangalore next, and India remote",
        {},
    )
    modes = interpret_onboarding_answer(
        "work_mode",
        "Remote or hybrid preferred; onsite is fine in Hyderabad",
        {},
    )

    assert locations["value"] == ["Hyderabad", "Bengaluru", "Remote India"]
    assert locations["kind"] == "hard"
    assert modes["value"] == ["remote", "hybrid", "onsite"]


def test_outside_selected_areas_changes_location_policy_not_keywords():
    interpreted = interpret_preference_message(
        "Don't include jobs from other areas than what I selected",
        {
            "preferred_locations": ["Hyderabad", "Bengaluru"],
            "excluded_keywords": ["sales"],
        },
    )

    assert interpreted is not None
    assert interpreted["updates"] == [
        {
            "key": "location_policy",
            "value": "strict",
            "kind": "hard",
            "operation": "replace",
        }
    ]


def test_mixed_exclusion_answer_keeps_location_policy_out_of_keyword_bag():
    onboarding = interpret_onboarding_answer(
        "exclusions",
        "Avoid sales, support-only, unpaid, and frontend-only roles. Keep the location policy strict.",
        {},
    )
    message = interpret_preference_message(
        "Avoid sales and unpaid roles; keep the location policy strict",
        {"excluded_keywords": []},
    )

    assert onboarding["value"] == ["sales", "support-only", "unpaid", "frontend-only"]
    assert message is not None
    updates = {item["key"]: item["value"] for item in message["updates"]}
    assert updates["location_policy"] == "strict"
    assert updates["excluded_keywords"] == ["sales", "unpaid"]


def test_named_geographic_exclusions_update_locations_not_keywords():
    interpreted = interpret_preference_message(
        "Exclude Singapore and Paris jobs",
        {"excluded_keywords": [], "excluded_locations": []},
    )

    assert interpreted is not None
    assert interpreted["updates"] == [
        {
            "key": "excluded_locations",
            "value": ["Singapore", "Paris"],
            "kind": "negative",
            "operation": "add",
        }
    ]


def test_outside_named_locations_creates_strict_allowlist_not_exclusions():
    interpreted = interpret_preference_message(
        "Do not include jobs outside Hyderabad, Bangalore, or Remote India",
        {
            "preferred_locations": ["India"],
            "excluded_locations": ["Bengaluru", "Singapore"],
            "excluded_keywords": ["sales"],
        },
    )

    assert interpreted is not None
    updates = {item["key"]: item for item in interpreted["updates"]}
    assert updates["preferred_locations"]["value"] == [
        "Hyderabad",
        "Bengaluru",
        "Remote India",
    ]
    assert updates["excluded_locations"]["value"] == ["Singapore"]
    assert updates["location_policy"]["value"] == "strict"
    assert "excluded_keywords" not in updates


def test_hard_job_gates_reject_foreign_remote_off_role_and_stale(settings):
    search = build_container(settings).search
    plan = strict_plan()

    accepted, rejected = search._filter_candidates(
        [
            candidate(),
            candidate(location="Remote — United States only", work_mode="remote"),
            candidate(location="Singapore", work_mode="onsite"),
            candidate(title="Data Analyst"),
            candidate(posted_hours_ago=72),
            candidate(title="Senior Backend Engineer"),
        ],
        plan,
    )

    assert [item.location for item in accepted] == ["Hyderabad, India"]
    assert rejected["location_outside_policy"] == 2
    assert rejected["role_outside_policy"] >= 1
    assert rejected["freshness_outside_policy"] == 1
    assert rejected["seniority_outside_policy"] == 1


def test_profile_priorities_are_editable_and_resume_refresh_preserves_them(client):
    complete_onboarding(client, RESUME)
    update = client.patch(
        "/api/preferences",
        json={
            "target_roles": ["Backend Engineer", "SDE I"],
            "preferred_locations": ["Hyderabad", "Bengaluru", "Remote India"],
            "work_modes": ["remote", "hybrid", "onsite"],
            "seniority_tolerance": "0 to 2 years",
            "excluded_keywords": ["frontend", "sales", "unpaid"],
            "excluded_locations": ["Singapore", "Paris"],
            "location_policy": "strict",
            "freshness_hours": 48,
        },
    )
    assert update.status_code == 200, update.text

    preview = client.post(
        "/api/profile/resume/preview",
        files={
            "resume": (
                "new-resume.txt",
                SECOND_RESUME.encode("utf-8"),
                "text/plain",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    refreshed = client.post(
        "/api/profile/resume/confirm",
        json={
            "draft_id": preview.json()["draft_id"],
            "profile_review": preview.json()["summary"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    payload = refreshed.json()
    assert payload["preserved_preferences"] is True
    assert payload["profile"]["profile"]["identity"]["name"] == "Jordan Current"
    preferences = {
        item["key"]: item["value"] for item in payload["profile"]["preferences"]
    }
    assert preferences["preferred_locations"] == [
        "Hyderabad",
        "Bengaluru",
        "Remote India",
    ]
    assert preferences["excluded_locations"] == ["Singapore", "Paris"]


def test_jobs_api_exposes_enforced_contract_and_rejection_coverage(client):
    complete_onboarding(client, RESUME)
    payload = client.get("/api/jobs").json()

    assert payload["contract"]["location_policy"] == "preference_order"
    assert payload["contract"]["role_policy"] == "expanded_early_career"
    assert payload["contract"]["freshness_policy"] == "strict"
    assert payload["contract"]["freshness_hours"] == 48
    assert payload["contract"]["source_policy"] == "official_direct"
    assert payload["latest_run"]["status"] == "complete"
    assert "rejections" in payload["latest_run"]["coverage"]
    assert all(
        job["location"] in {"Bengaluru, India", "Hyderabad, India", "Remote India"}
        for job in payload["jobs"]
    )
    observation = client.app.state.container.database.fetch_one(
        """
        SELECT payload_hash, candidate_json, parser_version
        FROM job_source_observations
        ORDER BY observed_at DESC LIMIT 1
        """
    )
    assert observation is not None
    assert len(observation["payload_hash"]) == 64
    assert observation["candidate_json"]
    assert observation["parser_version"]


def test_latest_verification_uses_rowid_when_timestamps_tie(client):
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]
    database = client.app.state.container.database
    latest = database.fetch_one(
        """
        SELECT checked_at FROM job_verifications WHERE job_id = ?
        ORDER BY checked_at DESC, rowid DESC LIMIT 1
        """,
        (job["id"],),
    )
    database.execute(
        """
        INSERT INTO job_verifications(
            id, job_id, live_state, freshness_class, posting_evidence_json,
            checked_at, apply_host, verifier_version
        ) VALUES (?, ?, 'uncertain', 'uncertain', '{}', ?, 'jobs.example.com', 'test')
        """,
        (new_id(), job["id"], latest["checked_at"]),
    )

    refreshed = client.get(f"/api/jobs/{job['id']}")

    assert refreshed.status_code == 200
    assert refreshed.json()["live_state"] == "uncertain"


def test_naive_sqlite_last_seen_timestamp_is_treated_as_utc(client):
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]
    database = client.app.state.container.database
    naive_utc = (utcnow() - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
    database.execute(
        "UPDATE jobs SET last_seen_at = ? WHERE id = ?",
        (naive_utc, job["id"]),
    )

    verified = client.app.state.container.search.verify(job["id"])

    assert verified["live_state"] == "live"


def test_ats_analysis_uses_final_artifact_and_tampering_blocks_approval(client):
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]
    created = client.post(
        f"/api/jobs/{job['id']}/resume-runs",
        json={"custom_instructions": "Keep one page and emphasize backend APIs."},
    )
    assert created.status_code == 200, created.text
    run = created.json()
    analysis = client.get(
        f"/api/resume-runs/{run['id']}/ats-analysis"
    )
    assert analysis.status_code == 200
    assert len(analysis.json()["checks"]) == 27
    assert analysis.json()["bindings"]["pdf_hash"] == run["result"]["provenance"]["pdf_hash"]

    pdf_path = run["result"]["artifacts"]["pdf"]
    with open(pdf_path, "ab") as handle:
        handle.write(b"\n% post-analysis tamper\n")
    approved = client.post(f"/api/resume-runs/{run['id']}/approve")
    assert approved.status_code == 409
    assert "changed after ATS analysis" in approved.json()["detail"]
