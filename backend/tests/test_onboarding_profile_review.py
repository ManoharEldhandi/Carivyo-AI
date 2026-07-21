from __future__ import annotations

import pytest

from test_integration import RESUME


def _finish_questions(client, imported):
    state = imported
    while state.get("question"):
        question = state["question"]
        examples = {
            "role_focus": "Backend Engineer",
            "preferred_locations": "Hyderabad, then Remote India",
            "work_mode": "Remote or hybrid",
            "seniority": "0 to 2 years",
            "exclusions": "Avoid sales roles",
        }
        response = client.post(
            "/api/onboarding/message",
            json={
                "session_id": imported["session_id"],
                "question_id": question["id"],
                "answer": examples[question["id"]],
            },
        )
        assert response.status_code == 200, response.text
        state = response.json()
    return state


def test_onboarding_confirmation_uses_reviewed_not_silent_inferred_values(client):
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", RESUME.encode(), "text/plain")},
    ).json()
    _finish_questions(client, imported)
    review = {
        "name": "Jordan Confirmed",
        "email": "jordan@example.com",
        "phone": "+91 99999 11111",
        "links": ["https://www.linkedin.com/in/jordan"],
        "skills": ["Python", "FastAPI"],
        "role_tracks": ["Backend Engineer"],
        "highlights": ["Built a verified API project."],
    }

    confirmed = client.post(
        "/api/onboarding/confirm",
        json={
            "session_id": imported["session_id"],
            "start_search": False,
            "profile_review": review,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    profile = client.get("/api/profile").json()["profile"]
    assert profile["identity"]["name"] == "Jordan Confirmed"
    assert profile["skills"] == ["Python", "FastAPI"]
    assert profile["role_families"] == ["Backend Engineer"]
    assert profile["confirmed_by_user"] is True
    assert len(profile["parsed_summary_hash"]) == 64


def test_onboarding_review_requires_at_least_one_role(client):
    response = client.post(
        "/api/onboarding/confirm",
        json={
            "session_id": "missing",
            "profile_review": {
                "name": "Candidate",
                "skills": [],
                "role_tracks": [],
                "highlights": [],
            },
        },
    )
    assert response.status_code == 422


def test_onboarding_confirmation_rejects_missing_profile_review(client):
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", RESUME.encode(), "text/plain")},
    ).json()
    _finish_questions(client, imported)

    response = client.post(
        "/api/onboarding/confirm",
        json={"session_id": imported["session_id"], "start_search": False},
    )

    assert response.status_code == 422


def test_onboarding_service_rejects_missing_profile_review(client):
    imported = client.post(
        "/api/onboarding/import",
        files={"resume": ("resume.txt", RESUME.encode(), "text/plain")},
    ).json()
    _finish_questions(client, imported)

    with pytest.raises(ValueError, match="Review the extracted profile"):
        client.app.state.container.onboarding.confirm(imported["session_id"], None)

    with pytest.raises(ValueError, match="Confirm at least one role direction"):
        client.app.state.container.onboarding.confirm(
            imported["session_id"],
            {"name": "Candidate", "role_tracks": []},
        )
