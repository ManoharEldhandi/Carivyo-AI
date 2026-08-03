from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.services.resume import ResumeRunBlocked, ResumeService
from app.utils import json_dumps, stable_hash

from test_integration import RESUME, complete_onboarding


def _create_pending_run(client) -> Dict[str, Any]:
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]
    response = client.post(
        f"/api/jobs/{job['id']}/resume-runs",
        json={
            "custom_instructions": "Keep one page and emphasize backend APIs."
        },
    )
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "needs_user_review"
    return run


def test_job_specific_resume_blocks_partial_discovery_metadata(client, monkeypatch):
    complete_onboarding(client, RESUME)
    job = client.get("/api/jobs").json()["jobs"][0]

    async def partial_revalidation(_job_id: str) -> Dict[str, Any]:
        return {
            **job,
            "description": "Backend Engineer. Python experience preferred.",
            "live_state": "live",
        }

    monkeypatch.setattr(
        client.app.state.container.search,
        "revalidate",
        partial_revalidation,
    )
    response = client.post(
        f"/api/jobs/{job['id']}/resume-runs",
        json={"custom_instructions": "Emphasize backend evidence."},
    )

    assert response.status_code == 409
    assert "complete responsibilities and qualifications" in response.json()["detail"]


@pytest.fixture()
def pending_run(client) -> Dict[str, Any]:
    return _create_pending_run(client)


def _write_json(path: Path, value: Dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _rebind_persisted_reports(
    client,
    run: Dict[str, Any],
    *,
    validation: Optional[Dict[str, Any]] = None,
    mutate_ats: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Model an attacker who updates every unkeyed persisted integrity copy."""

    container = client.app.state.container
    result_path = Path(run["result_path"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    validation_path = Path(result["artifacts"]["validation_report"])
    ats_path = Path(result["artifacts"]["ats_report"])
    ats_report = json.loads(ats_path.read_text(encoding="utf-8"))

    if validation is not None:
        _write_json(validation_path, validation)
        validation_hash = stable_hash(validation)
        validation_file_hash = container.vault.hash_file(validation_path)
        result["validation"] = validation
        result["provenance"]["validation_hash"] = validation_hash
        result["provenance"][
            "validation_report_file_hash"
        ] = validation_file_hash
        ats_report["bindings"]["validation_hash"] = validation_hash
        ats_report["bindings"][
            "validation_report_file_hash"
        ] = validation_file_hash

    if mutate_ats is not None:
        mutate_ats(ats_report)

    ats_report["bindings"].pop("analysis_hash", None)
    analysis_hash = stable_hash(ats_report)
    ats_report["bindings"]["analysis_hash"] = analysis_hash
    _write_json(ats_path, ats_report)

    result["ats_analysis"] = ats_report
    result["provenance"]["ats_analysis_hash"] = analysis_hash
    result["provenance"]["ats_report_file_hash"] = container.vault.hash_file(
        ats_path
    )
    _write_json(result_path, result)
    container.database.execute(
        """
        UPDATE ats_analyses
        SET analyzer_version = ?, score = ?, analysis_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE run_id = ?
        """,
        (
            ats_report["analyzer_version"],
            ats_report["overall_score"],
            json_dumps(ats_report),
            run["id"],
        ),
    )


def test_tampered_frozen_jd_cannot_be_approved(client, pending_run):
    jd_path = Path(pending_run["workspace_path"]) / "inputs" / "job-description.txt"
    jd_path.write_text(
        jd_path.read_text(encoding="utf-8") + "\nInjected requirement: admin access.",
        encoding="utf-8",
    )

    response = client.post(f"/api/resume-runs/{pending_run['id']}/approve")

    assert response.status_code == 409
    assert "job description hash does not match" in response.json()["detail"]


def test_persisted_validation_failure_cannot_be_approved(client, pending_run):
    validation = dict(pending_run["result"]["validation"])
    validation["evidence_ok"] = False
    _rebind_persisted_reports(client, pending_run, validation=validation)

    response = client.post(f"/api/resume-runs/{pending_run['id']}/approve")

    assert response.status_code == 409
    assert "Persisted validation failed: evidence_ok" in response.json()["detail"]


def test_ats_blocked_report_cannot_be_approved(client, pending_run):
    def block_report(report: Dict[str, Any]) -> None:
        report["report_summary"]["readiness"] = "blocked"
        report["critical_failures"] = ["parse_rate"]

    _rebind_persisted_reports(client, pending_run, mutate_ats=block_report)

    response = client.post(f"/api/resume-runs/{pending_run['id']}/approve")

    assert response.status_code == 409
    assert "ATS readiness is blocked" in response.json()["detail"]


def test_parse_rate_uses_extraction_counts_and_forgery_cannot_pass(
    client,
    monkeypatch,
):
    service = client.app.state.container.resumes
    original_analyze = service.ats.analyze
    observed_metadata = []

    def capture_metadata(resume_text, metadata, jd_text, **kwargs):
        observed_metadata.append(dict(metadata))
        return original_analyze(resume_text, metadata, jd_text, **kwargs)

    monkeypatch.setattr(service.ats, "analyze", capture_metadata)
    run = _create_pending_run(client)
    pdf_path = Path(run["result"]["artifacts"]["pdf"])
    source_path = Path(run["result"]["artifacts"]["editable_source"])
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages
    )
    source_text = source_path.read_text(encoding="utf-8")
    generation_metadata = observed_metadata[0]

    assert generation_metadata["extracted_char_count"] == len(extracted)
    assert generation_metadata["source_char_count"] == len(
        service._tex_visible_text(source_text)
    )
    assert generation_metadata["source_char_count"] != len(extracted)
    assert "extracted_characters" not in generation_metadata
    assert "source_characters" not in generation_metadata
    parser_validation = run["result"]["validation"]["parser_validation"]
    expected_rate = parser_validation["consensus_score"]
    assert run["result"]["ats_analysis"]["parse_rate"] == expected_rate
    assert parser_validation["status"] == "strong"
    assert set(parser_validation["parsers"]) == {
        "pypdf",
        "poppler_layout",
    }

    original_rate = run["result"]["ats_analysis"]["parse_rate"]

    def forge_parse_rate(report: Dict[str, Any]) -> None:
        report["parse_rate"] = 0.0 if original_rate else 100.0

    _rebind_persisted_reports(client, run, mutate_ats=forge_parse_rate)
    response = client.post(f"/api/resume-runs/{run['id']}/approve")

    assert response.status_code == 409
    assert "ATS analysis cannot be reproduced" in response.json()["detail"]


def test_handoff_reverification_rejects_post_approval_artifact_tampering(
    client,
    pending_run,
):
    approved = client.post(f"/api/resume-runs/{pending_run['id']}/approve")
    assert approved.status_code == 200, approved.text
    service = client.app.state.container.resumes
    verified = service.verify_ready_for_handoff(pending_run["id"])
    assert verified["status"] == "ready_to_apply"

    pdf_path = Path(approved.json()["result"]["artifacts"]["pdf"])
    with pdf_path.open("ab") as handle:
        handle.write(b"\n% post-approval tamper\n")

    with pytest.raises(ResumeRunBlocked, match="generated PDF changed"):
        service.verify_ready_for_handoff(pending_run["id"])

    handoff = client.post(
        f"/api/jobs/{pending_run['job_id']}/prepare-application",
        json={"resume_run_id": pending_run["id"], "notes": ""},
    )
    assert handoff.status_code == 409
    assert "generated PDF changed" in handoff.json()["detail"]


def test_revised_run_handoff_rechecks_frozen_revision_spec(client, pending_run):
    revised = client.post(
        f"/api/resume-runs/{pending_run['id']}/message",
        json={"message": "Move the strongest API evidence slightly earlier."},
    )
    assert revised.status_code == 200, revised.text
    assert revised.json()["result"]["variant"] == 2
    approved = client.post(f"/api/resume-runs/{pending_run['id']}/approve")
    assert approved.status_code == 200, approved.text
    service = client.app.state.container.resumes
    assert service.verify_ready_for_handoff(pending_run["id"])["status"] == (
        "ready_to_apply"
    )

    revision_path = (
        Path(pending_run["workspace_path"]) / "inputs" / "revision-2.json"
    )
    revision_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ResumeRunBlocked, match="revision specification is invalid"):
        service.verify_ready_for_handoff(pending_run["id"])


def test_revision_generation_failure_restores_previous_version(
    client, pending_run, monkeypatch
):
    service = client.app.state.container.resumes

    def fail_generation(*_args, **_kwargs):
        raise RuntimeError("controlled render failure")

    monkeypatch.setattr(service, "_generate", fail_generation)
    with pytest.raises(RuntimeError, match="controlled render failure"):
        service.revise(pending_run["id"], "Make one focused change.")

    restored = service.get(pending_run["id"])
    assert restored["status"] == pending_run["status"]
    assert restored["stage"] == pending_run["stage"]
    assert restored["error"] is None
    assert restored["result"]["variant"] == pending_run["result"]["variant"]
    assert not Path(pending_run["workspace_path"]).joinpath(
        "inputs", "revision-2.json"
    ).exists()


def test_resume_result_contains_same_jd_before_after_ats_comparison(pending_run):
    comparison = pending_run["result"]["ats_comparison"]

    assert comparison["current_score"] == pending_run["result"]["ats_analysis"][
        "overall_score"
    ]
    assert comparison["analyzer_version"] == pending_run["result"]["ats_analysis"][
        "analyzer_version"
    ]
    assert len(comparison["categories"]) == 7
    assert "same frozen JD" in comparison["baseline_scope"]


def test_visual_validation_is_a_real_raster_gate(tmp_path):
    valid = tmp_path / "valid.png"
    image = Image.new("L", (1224, 1584), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 90, 1050, 120), fill=0)
    draw.rectangle((80, 180, 900, 900), outline=80, width=4)
    image.save(valid)

    ok, details = ResumeService._validate_render(valid)
    assert ok is True
    assert details["method"] == "deterministic_raster_v1"
    assert details["human_inspected"] is False

    clipped = tmp_path / "clipped.png"
    image = Image.new("L", (1224, 1584), 255)
    ImageDraw.Draw(image).rectangle((0, 80, 800, 300), fill=0)
    image.save(clipped)
    ok, details = ResumeService._validate_render(clipped)
    assert ok is False
    assert details["reason"] == "possible_edge_clipping"

    blank = tmp_path / "blank.png"
    Image.new("L", (1224, 1584), 255).save(blank)
    ok, details = ResumeService._validate_render(blank)
    assert ok is False
    assert details["reason"] == "blank_page"
