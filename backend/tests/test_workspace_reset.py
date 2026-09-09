from pathlib import Path

from test_integration import RESUME, complete_onboarding


def test_reset_workspace_removes_activity_but_keeps_resume_master_for_review(client):
    complete_onboarding(client, RESUME)
    database = client.app.state.container.database
    artifact = database.fetch_one("SELECT * FROM source_artifacts")
    assert artifact is not None
    source_path = Path(artifact["source_path"])
    text_path = Path(artifact["text_path"])
    assert source_path.is_file()
    assert text_path.is_file()

    reset = client.delete("/api/data/reset-keep-masters")

    assert reset.status_code == 200, reset.text
    assert reset.json()["reset"] is True
    assert reset.json()["preserved_masters"] == 1
    assert client.get("/api/profile").json() == {"onboarding_required": True}
    assert database.fetch_one("SELECT COUNT(*) AS count FROM jobs")["count"] == 0
    assert database.fetch_one("SELECT COUNT(*) AS count FROM profile_snapshots")["count"] == 0
    assert database.fetch_one(
        "SELECT COUNT(*) AS count FROM evidence_claims WHERE approval = 'pending'"
    )["count"] > 0
    assert source_path.is_file()
    assert text_path.is_file()

    masters = client.get("/api/onboarding/saved-masters")
    assert masters.status_code == 200
    assert masters.json()["masters"] == [
        {
            "id": artifact["id"],
            "original_name": "resume.txt",
            "kind": "text",
            "size_bytes": len(RESUME.encode("utf-8")),
            "created_at": artifact["created_at"],
        }
    ]
    resumed = client.post(f"/api/onboarding/saved-masters/{artifact['id']}")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["session_id"]
    assert resumed.json()["summary"]["name"] == "Avery Candidate"
