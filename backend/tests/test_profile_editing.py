from __future__ import annotations

from test_integration import RESUME, complete_onboarding


def test_profile_edit_creates_confirmed_version_and_preserves_evidence(client):
    complete_onboarding(client, RESUME)
    before = client.get("/api/profile").json()
    evidence_ids = [item["id"] for item in before["evidence"]]
    bases = [item["id"] for item in before["resume_bases"]]

    response = client.patch(
        "/api/profile",
        json={
            "identity": {
                **before["profile"]["identity"],
                "location": "Hyderabad, India",
            },
            "skills": [*before["profile"]["skills"], "FastAPI"],
            "role_families": ["Backend Engineer"],
            "highlights": before["profile"]["highlights"],
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] != before["version"]
    assert updated["profile"]["confirmed_by_user"] is True
    assert updated["profile"]["supersedes_profile_version"] == before["version"]
    assert updated["profile"]["identity"]["location"] == "Hyderabad, India"
    assert [item["id"] for item in updated["evidence"]] == evidence_ids
    assert [item["id"] for item in updated["resume_bases"]] == bases
    assert updated["search_plan"]["plan"]["generated_from"]["profile_version"] == updated["version"]

    history = client.app.state.container.database.fetch_one(
        "SELECT metadata_json FROM activity_events WHERE event_type = 'profile_updated'"
    )
    assert history is not None


def test_profile_edit_rejects_invalid_links_and_empty_roles(client):
    complete_onboarding(client, RESUME)
    profile = client.get("/api/profile").json()["profile"]

    response = client.patch(
        "/api/profile",
        json={
            "identity": {**profile["identity"], "links": ["javascript:alert(1)"]},
            "skills": profile["skills"],
            "role_families": [],
            "highlights": profile["highlights"],
        },
    )
    assert response.status_code == 422


def test_user_confirmed_skill_without_ledger_evidence_is_not_claimed_as_proof(client):
    complete_onboarding(client, RESUME)
    before = client.get("/api/profile").json()
    update = client.patch(
        "/api/profile",
        json={
            "identity": before["profile"]["identity"],
            "skills": [*before["profile"]["skills"], "QuantumLang"],
            "role_families": before["profile"]["role_families"],
            "highlights": before["profile"]["highlights"],
        },
    )
    assert update.status_code == 200, update.text
    plan = update.json()["search_plan"]["plan"]

    match = client.app.state.container.matching.score(
        {
            "title": plan["target_roles"][0],
            "company": "Example",
            "description": "The role requires QuantumLang.",
            "location": plan["locations"][0],
            "work_mode": None,
            "posted_at": None,
        },
        "verified_24h",
        plan,
    )

    assert match["factors"]["skill_fit"] == 0
    assert all(reason["code"] != "skill_evidence" for reason in match["reasons"])
