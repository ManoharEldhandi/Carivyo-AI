from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


RESUME = """
Avery Candidate
avery.candidate@example.com | +91 90000 00000 | https://github.com/avery-candidate

SUMMARY
Software engineer focused on backend and AI systems.

SKILLS
Python, FastAPI, Java, TypeScript, React, SQL, PostgreSQL, Docker, AWS, Git, Playwright, RAG, LLM

EXPERIENCE
Built Python and FastAPI services with PostgreSQL for a production-oriented application.
Developed REST APIs and automated tests using GitHub Actions and Playwright.

PROJECTS
Created a RAG assistant using Python, vector retrieval, and an evidence-grounded answer pipeline.
Built a React and TypeScript dashboard connected to secure backend APIs.

EDUCATION
Bachelor of Technology in Computer Science.
""".strip()

SECOND_RESUME = """
Jordan Current
jordan.current@example.com | +91 91111 11111 | https://github.com/jordan-current

SUMMARY
Software engineer focused on Java services and quality automation.

SKILLS
Java, Spring Boot, SQL, Git, Selenium

EXPERIENCE
Built Java and Spring Boot services with SQL-backed persistence.
Created Selenium regression tests for critical user workflows.

PROJECTS
Developed a Java service with deterministic validation and structured logging.

EDUCATION
Bachelor of Engineering in Information Technology.
""".strip()


def complete_onboarding(client, resume: str):
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", resume.encode("utf-8"), "text/plain")},
    )
    assert imported.status_code == 200, imported.text
    state = imported.json()
    answers = {
        "role_focus": "Backend Engineer, Software Engineer",
        "preferred_locations": "Bengaluru, Hyderabad, Remote India",
        "work_mode": "Remote or hybrid preferred.",
        "seniority": "Fresher to 2 years, including SDE I.",
        "exclusions": "sales, unpaid",
    }
    while state.get("question"):
        question = state["question"]
        response = client.post(
            "/api/onboarding/message",
            json={
                "session_id": state["session_id"],
                "question_id": question["id"],
                "answer": answers[question["id"]],
            },
        )
        assert response.status_code == 200, response.text
        state["question"] = response.json()["question"]
    confirmed = client.post(
        "/api/onboarding/confirm",
        json={
            "session_id": state["session_id"],
            "start_search": True,
            "profile_review": state["summary"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_temporary_search_override_is_typed_and_does_not_change_preferences(client):
    complete_onboarding(client, RESUME)
    before = client.get("/api/preferences").json()

    response = client.post(
        "/api/search-runs",
        json={
            "temporary_instruction": (
                "Find Software Engineer I jobs in Hyderabad, onsite, "
                "within the last 48 hours"
            )
        },
    )

    assert response.status_code == 200, response.text
    status = client.get(f"/api/search-runs/{response.json()['id']}").json()
    assert status["status"] == "complete"
    payload = client.get("/api/jobs").json()
    assert payload["contract"]["target_roles"] == ["Software Engineer I"]
    assert payload["contract"]["locations"] == ["Hyderabad"]
    assert payload["contract"]["work_modes"] == ["onsite"]
    assert payload["contract"]["freshness_hours"] == 48
    assert payload["contract"]["temporary_override"]["saved_preferences_changed"] is False
    assert [job["title"] for job in payload["jobs"]] == ["Software Engineer I"]
    after = client.get("/api/preferences").json()
    assert after == before


def test_temporary_search_accepts_the_exact_ui_instruction_shape(client):
    complete_onboarding(client, RESUME)

    response = client.post(
        "/api/search-runs",
        json={
            "temporary_instruction": (
                "Backend roles in Hyderabad, onsite, within 24 hours"
            )
        },
    )

    assert response.status_code == 200, response.text
    contract = client.get("/api/jobs").json()["contract"]
    assert contract["target_roles"] == ["Backend"]
    assert contract["locations"] == ["Hyderabad"]
    assert contract["work_modes"] == ["onsite"]
    assert contract["freshness_hours"] == 24


def test_chat_requires_confirmation_before_broadening_saved_preferences(client):
    complete_onboarding(client, RESUME)
    before = client.get("/api/preferences").json()

    proposed = client.post(
        "/api/chat/messages",
        json={
            "message": "Show Backend Engineer roles in Singapore",
            "current_page": "jobs",
            "provider": "auto",
            "use_ai": False,
        },
    )

    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["intent"] == "confirm_preference_update"
    assert proposal["search_requested"] is False
    assert proposal["preference_confirmation"]["id"]
    assert client.get("/api/preferences").json() == before

    accepted = client.post(
        f"/api/chat/preference-changes/{proposal['preference_confirmation']['id']}/decision",
        json={"accept": True},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "applied"
    assert accepted.json()["search_run_id"]
    preferences = {
        item["key"]: item["value"]
        for item in client.get("/api/preferences").json()["preferences"]
    }
    assert preferences["preferred_locations"] == ["Singapore"]


def test_critical_user_journey(client, tmp_path: Path):
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", RESUME.encode("utf-8"), "text/plain")},
    )
    assert imported.status_code == 200, imported.text
    state = imported.json()
    assert state["summary"]["skills"]
    assert state["progress"]["total"] <= 7

    answers = {
        "role_focus": "Backend Engineer, AI/LLM Engineer",
        "preferred_locations": "Bengaluru, Hyderabad, Remote India",
        "work_mode": "Remote or hybrid preferred; onsite is okay in Bengaluru.",
        "seniority": "Fresher to 2 years, including SDE I.",
        "exclusions": "sales, unpaid",
    }
    while state.get("question"):
        question = state["question"]
        response = client.post(
            "/api/onboarding/message",
            json={
                "session_id": state["session_id"],
                "question_id": question["id"],
                "answer": answers[question["id"]],
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        state["question"] = payload["question"]

    confirmed = client.post(
        "/api/onboarding/confirm",
        json={
            "session_id": state["session_id"],
            "start_search": True,
            "profile_review": state["summary"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    run_id = confirmed.json()["search_run_id"]
    run = client.get(f"/api/search-runs/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "complete"
    assert set(run.json()["coverage"]["families"]) == {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
    }

    profile = client.get("/api/profile")
    assert profile.status_code == 200
    assert profile.json()["profile"]["identity"]["email"] == "avery.candidate@example.com"
    assert len(profile.json()["evidence"]) > 3

    jobs = client.get("/api/jobs")
    assert jobs.status_code == 200
    payload = jobs.json()
    assert payload["count"] == 2
    assert payload["freshness"]["verified_24h"] == 2
    selected = payload["jobs"][0]
    assert selected["reasons"]
    assert selected["apply_url"].startswith("https://jobs.example.com/")

    explained = client.post(
        "/api/chat/messages",
        json={
            "message": "Why is this job recommended?",
            "selected_job_id": selected["id"],
            "current_page": "jobs",
            "use_ai": False,
        },
    )
    assert explained.status_code == 200, explained.text
    assert "scored" in explained.json()["content"]
    conversation_id = explained.json()["conversation_id"]
    history = client.get(f"/api/chat/conversations/{conversation_id}")
    assert len(history.json()["messages"]) == 2

    resume = client.post(
        f"/api/jobs/{selected['id']}/resume-runs",
        json={
            "custom_instructions": "Make it one page and emphasize backend APIs. Keep the layout if safe."
        },
    )
    assert resume.status_code == 200, resume.text
    run = resume.json()
    assert run["status"] == "needs_user_review"
    result = run["result"]
    assert result["mode"] == "tailor"
    assert result["base_selection"]["score"] > 0
    assert result["approval"] == {
        "required": True,
        "user_approved": False,
    }
    assert result["provenance"]["skill_version"] == "4.0.0"
    assert len(result["ats_analysis"]["checks"]) == 27
    assert 0 <= result["ats_analysis"]["overall_score"] <= 100
    assert "No universal ATS score exists" in result["ats_analysis"]["disclaimer"]
    assert result["validation"]["export_ok"] is True
    assert result["validation"]["evidence_ok"] is True
    assert result["validation"]["links_ok"] is True
    assert result["validation"]["identity_ok"] is True
    assert result["validation"]["section_order_ok"] is True
    assert result["validation"]["change_budget_applicable"] is True
    assert result["validation"]["change_percent"] <= 25
    assert result["validation"]["change_budget_status"] in {
        "within_target",
        "within_review_budget",
    }
    expected_role = "_".join(selected["title"].split())
    assert result["export_filename"] == f"Avery_Candidate_{expected_role}_Resume.pdf"
    filename_check = next(
        check for check in result["ats_analysis"]["checks"] if check["id"] == "filename"
    )
    assert filename_check["status"] == "pass"
    assert result["export_filename"] in filename_check["evidence"][0]
    assert any(
        item.get("type") == "layout" and item.get("status") == "applied"
        for item in result["custom_instruction_interpretation"]
    )
    assert Path(result["artifacts"]["pdf"]).exists()
    assert Path(result["artifacts"]["render"]).exists()
    assert Path(result["artifacts"]["ats_report"]).exists()
    artifact = client.get(f"/api/resume-runs/{run['id']}/artifact/pdf")
    assert artifact.status_code == 200
    assert result["export_filename"] in artifact.headers["content-disposition"]
    contract_check = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[2]
                / "skills"
                / "carivyo-resume-designer"
                / "scripts"
                / "validate_run.py"
            ),
            run["workspace_path"],
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert contract_check.returncode == 0, contract_check.stdout + contract_check.stderr

    approved = client.post(f"/api/resume-runs/{run['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "ready_to_apply"
    assert approved.json()["result"]["approval"]["user_approved"] is True

    prepared = client.post(
        f"/api/jobs/{selected['id']}/prepare-application",
        json={"resume_run_id": run["id"], "notes": "Review company questions manually."},
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["status"] == "draft"

    opened = client.post(f"/api/jobs/{selected['id']}/open-apply")
    assert opened.status_code == 200
    assert opened.json()["application"]["status"] == "opened"
    assert opened.json()["official_url"] == selected["apply_url"]

    prepared_again = client.post(
        f"/api/jobs/{selected['id']}/prepare-application",
        json={},
    )
    assert prepared_again.status_code == 200, prepared_again.text
    assert prepared_again.json()["resume_run_id"] == run["id"]
    assert prepared_again.json()["notes"] == "Review company questions manually."

    applied = client.patch(
        f"/api/applications/{opened.json()['application']['id']}",
        json={"status": "applied", "notes": "Submitted by the user."},
    )
    assert applied.status_code == 200
    assert applied.json()["status"] == "applied"
    assert set(applied.json()["allowed_transitions"]) == {
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    }

    prepared_after_submission = client.post(
        f"/api/jobs/{selected['id']}/prepare-application",
        json={},
    )
    assert prepared_after_submission.status_code == 200
    assert prepared_after_submission.json()["resume_run_id"] == run["id"]
    assert prepared_after_submission.json()["status"] == "applied"

    invalid_transition = client.patch(
        f"/api/applications/{opened.json()['application']['id']}",
        json={"status": "draft"},
    )
    assert invalid_transition.status_code == 409
    assert "cannot move directly" in invalid_transition.json()["detail"]

    usage = client.get("/api/ai-usage")
    assert usage.status_code == 200
    assert usage.json()["totals"]["runs"] >= 1

    backup = client.post("/api/backup")
    assert backup.status_code == 200
    backup_path = Path(backup.json()["path"])
    assert backup_path.exists()
    downloaded_backup = client.get(
        f"/api/backups/{backup.json()['filename']}"
    )
    assert downloaded_backup.status_code == 200
    assert downloaded_backup.headers["content-type"] == "application/zip"
    assert downloaded_backup.content.startswith(b"PK")
    assert client.get("/api/backups/..%2Fcarivyo.sqlite3").status_code == 404

    deleted = client.delete("/api/data")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["deleted_backups"] == 1
    assert not backup_path.exists()
    assert client.app.state.container.database.fetch_one(
        "SELECT COUNT(*) AS count FROM profile_snapshots"
    )["count"] == 0


def test_profile_rollover_and_revision_keep_resume_run_frozen(client):
    complete_onboarding(client, RESUME)
    first_profile = client.get("/api/profile").json()
    first_evidence_ids = {claim["id"] for claim in first_profile["evidence"]}
    first_base_ids = {base["id"] for base in first_profile["resume_bases"]}
    assert first_evidence_ids
    assert first_base_ids

    selected = client.get("/api/jobs").json()["jobs"][0]
    created = client.post(
        f"/api/jobs/{selected['id']}/resume-runs",
        json={
            "custom_instructions": "Keep it one page and emphasize backend APIs."
        },
    )
    assert created.status_code == 200, created.text
    original_run = created.json()
    workspace = Path(original_run["workspace_path"])
    original_spec = json.loads(
        (workspace / "inputs" / "run-spec.json").read_text(encoding="utf-8")
    )
    frozen_claim_ids = {
        claim["id"] for claim in original_spec["evidence_claims"]
    }
    assert frozen_claim_ids <= first_evidence_ids
    assert original_spec["profile_snapshot"]["profile"]["identity"]["name"] == (
        "Avery Candidate"
    )

    complete_onboarding(client, SECOND_RESUME)
    current_profile = client.get("/api/profile").json()
    current_evidence_ids = {claim["id"] for claim in current_profile["evidence"]}
    current_base_ids = {base["id"] for base in current_profile["resume_bases"]}
    current_evidence_text = " ".join(
        claim["text"] for claim in current_profile["evidence"]
    )

    assert current_profile["profile"]["identity"]["name"] == "Jordan Current"
    assert "Avery Candidate" not in current_evidence_text
    assert current_evidence_ids.isdisjoint(first_evidence_ids)
    assert current_base_ids.isdisjoint(first_base_ids)

    revised = client.post(
        f"/api/resume-runs/{original_run['id']}/message",
        json={"message": "Give the approved API evidence slightly more prominence."},
    )
    assert revised.status_code == 200, revised.text
    revised_run = revised.json()
    assert revised_run["result"]["variant"] == 2
    assert revised_run["result"]["mode"] == "revise"
    assert revised_run["result"]["provenance"]["profile_snapshot_hash"] == (
        original_spec["profile_snapshot"]["hash"]
    )

    revised_markdown = Path(
        revised_run["result"]["artifacts"]["editable_source"]
    ).read_text(encoding="utf-8")
    assert "Avery Candidate" in revised_markdown
    assert "Jordan Current" not in revised_markdown
    referenced_ids = {
        evidence_id
        for group in revised_run["result"]["coverage"].values()
        for item in group
        for evidence_id in item.get("evidence_ids", [])
    }
    assert referenced_ids <= frozen_claim_ids
    assert (workspace / "inputs" / "revision-2.json").is_file()

    contract_check = subprocess.run(
        [
            sys.executable,
            str(
                Path(__file__).resolve().parents[2]
                / "skills"
                / "carivyo-resume-designer"
                / "scripts"
                / "validate_run.py"
            ),
            str(workspace),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert contract_check.returncode == 0, contract_check.stdout + contract_check.stderr
