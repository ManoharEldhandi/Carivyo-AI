from __future__ import annotations

import math
import time

from app.utils import json_dumps, new_id, stable_hash


RESUME = b"""Avery Candidate
avery@example.com | +91 90000 00000

SUMMARY
Backend software engineer.

SKILLS
Python, FastAPI, SQL, PostgreSQL, Docker

EXPERIENCE
Built reliable Python APIs and automated tests.

EDUCATION
Bachelor of Technology in Computer Science.
"""


def _complete_fixture_search(client) -> str:
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", RESUME, "text/plain")},
    )
    assert imported.status_code == 200, imported.text
    state = imported.json()
    answers = {
        "role_focus": "Backend Engineer, Software Engineer",
        "preferred_locations": "Bengaluru, Hyderabad, Remote India",
        "work_mode": "Remote or hybrid preferred.",
        "seniority": "Fresher to 2 years.",
        "exclusions": "sales, unpaid",
    }
    while state.get("question"):
        question = state["question"]
        answered = client.post(
            "/api/onboarding/message",
            json={
                "session_id": state["session_id"],
                "question_id": question["id"],
                "answer": answers[question["id"]],
            },
        )
        assert answered.status_code == 200, answered.text
        state["question"] = answered.json()["question"]
    confirmed = client.post(
        "/api/onboarding/confirm",
        json={
            "session_id": state["session_id"],
            "start_search": True,
            "profile_review": state["summary"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()["search_run_id"]


def _expand_result_set(client, run_id: str, target_count: int = 80) -> None:
    container = client.app.state.container
    database = container.database
    profile = container.profiles.active_profile()
    preference_version = container.profiles.preference_version()
    base_job = database.fetch_one(
        "SELECT * FROM jobs ORDER BY first_seen_at ASC, rowid ASC LIMIT 1"
    )
    base_match = database.fetch_one(
        """
        SELECT * FROM match_results
        WHERE job_id = ? AND profile_version = ? AND preference_version = ?
        """,
        (base_job["id"], profile["version"], preference_version),
    )
    existing = database.fetch_one(
        "SELECT COUNT(*) AS count FROM search_run_jobs WHERE run_id = ?",
        (run_id,),
    )["count"]

    with database.transaction() as connection:
        for index in range(existing, target_count):
            job_id = new_id()
            external_id = f"perf-{index}"
            apply_url = f"https://jobs.example.com/perf/{index}"
            connection.execute(
                """
                INSERT INTO jobs(
                    id, connector_id, external_id, canonical_key, title, company,
                    description, description_hash, location, work_mode,
                    employment_type, posted_at, posted_semantics, apply_url,
                    source_url, source_family
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    base_job["connector_id"],
                    external_id,
                    stable_hash(external_id),
                    base_job["title"],
                    f"Performance Company {index}",
                    base_job["description"],
                    base_job["description_hash"],
                    base_job["location"],
                    base_job["work_mode"],
                    base_job["employment_type"],
                    base_job["posted_at"],
                    base_job["posted_semantics"],
                    apply_url,
                    apply_url,
                    base_job["source_family"],
                ),
            )
            connection.execute(
                """
                INSERT INTO job_verifications(
                    id, job_id, live_state, freshness_class,
                    posting_evidence_json, apply_host, verifier_version
                ) VALUES (?, ?, 'live', 'verified_24h', ?, 'jobs.example.com', 'perf')
                """,
                (new_id(), job_id, json_dumps({"official_listing_present": True})),
            )
            connection.execute(
                """
                INSERT INTO match_results(
                    id, job_id, profile_version, preference_version, score, tier,
                    factors_json, reasons_json, risks_json, evidence_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    job_id,
                    profile["version"],
                    preference_version,
                    base_match["score"],
                    base_match["tier"],
                    base_match["factors_json"],
                    base_match["reasons_json"],
                    base_match["risks_json"],
                    base_match["evidence_ids_json"],
                ),
            )
            connection.execute(
                "INSERT INTO search_run_jobs(run_id, job_id, ordinal) VALUES (?, ?, ?)",
                (run_id, job_id, index),
            )
            for event_index in range(3):
                connection.execute(
                    """
                    INSERT INTO activity_events(id, event_type, job_id, metadata_json)
                    VALUES (?, 'save', ?, ?)
                    """,
                    (new_id(), job_id, json_dumps({"sample": event_index})),
                )


def test_populated_jobs_endpoint_p95_stays_within_local_budget(client):
    run_id = _complete_fixture_search(client)
    _expand_result_set(client, run_id)

    durations = []
    for _ in range(10):
        started = time.perf_counter()
        response = client.get("/api/jobs")
        durations.append(time.perf_counter() - started)
        assert response.status_code == 200
        assert response.json()["count"] == 80

    p95 = sorted(durations)[math.ceil(len(durations) * 0.95) - 1]
    assert p95 < 1.0, f"populated /api/jobs p95 was {p95:.3f}s"
