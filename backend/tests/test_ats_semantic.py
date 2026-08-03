from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from app.artifacts import ArtifactVault
from app.db import Database
from app.services.ats import analyze_resume
from app.services.ats_semantic import (
    ATSSemanticReviewService,
    SemanticReviewInputError,
)
from app.services.runtime import RuntimeUnavailable
from app.utils import json_dumps, stable_hash


RESUME_TEXT = """
AVERY CANDIDATE
Backend Engineer
avery@example.com

SKILLS
Python, FastAPI, PostgreSQL

EXPERIENCE
Backend Engineer, Example Labs
- Built FastAPI services handling 2 million requests each month.
- Reduced PostgreSQL query latency by 42%.
""".strip()

JD_TEXT = """
Backend Engineer
Build Python and FastAPI services backed by PostgreSQL.
Own production reliability and communicate with stakeholders.
""".strip()

ATS_METADATA = {
    "filename": "Avery_Candidate_Resume.pdf",
    "file_format": "pdf",
    "size_bytes": 100_000,
    "column_count": 1,
    "has_tables": False,
    "has_text_boxes": False,
    "image_only": False,
    "job_title": "Backend Engineer",
}


class FakeRuntime:
    def __init__(self, outcomes: List[Any]):
        self.outcomes = list(outcomes)
        self.calls: List[Dict[str, Any]] = []

    def selection(self) -> Dict[str, str]:
        return {
            "provider": "fake",
            "model": "semantic-test-model",
            "reasoning_effort": "low",
        }

    def run_chat(self, prompt: str, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append({"prompt": prompt, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return {
            "provider": "fake",
            "model": kwargs.get("model") or "semantic-test-model",
            "content": outcome,
            "input_tokens": 17,
            "output_tokens": 11,
            "cache_read_tokens": 2,
            "usage_kind": "measured",
            "latency_ms": 4,
        }


def _response(
    *,
    resume_evidence: str = "Built FastAPI services handling 2 million requests each month.",
    jd_evidence: str = "Own production reliability",
) -> str:
    return json_dumps(
        {
            "findings": [
                {
                    "category": "job_tailoring",
                    "severity": "medium",
                    "claim": "The resume shows relevant API scale but not explicit reliability ownership.",
                    "resume_evidence": resume_evidence,
                    "jd_evidence": jd_evidence,
                    "recommendation": "If truthful, state the candidate's production reliability ownership.",
                    "confidence": 0.86,
                }
            ]
        }
    )


@pytest.fixture()
def semantic_context(tmp_path: Path) -> Dict[str, Any]:
    database = Database(
        tmp_path / "carivyo.db",
        Path(__file__).resolve().parents[1] / "app" / "migrations",
    )
    database.initialize()
    workspace = tmp_path / "resume-run"
    workspace.mkdir()
    database.execute(
        """
        INSERT INTO connectors(
            id, connector_type, name, source_domain, config_json,
            trust_tier, parser_version
        ) VALUES ('connector-1', 'fixture', 'Fixture', 'example.com', '{}',
                  'official', 'test-1')
        """
    )
    database.execute(
        """
        INSERT INTO jobs(
            id, connector_id, external_id, canonical_key, title, company,
            description, description_hash, location, apply_url, source_url,
            source_family
        ) VALUES (?, 'connector-1', 'external-1', 'job-key', 'Backend Engineer',
                  'Example Labs', ?, ?, 'Remote India', 'https://example.com/apply',
                  'https://example.com/job', 'fixture')
        """,
        ("job-1", JD_TEXT, stable_hash(JD_TEXT)),
    )
    database.execute(
        """
        INSERT INTO resume_runs(
            id, job_id, status, stage, mode, custom_instructions,
            workspace_path, jd_hash, profile_version
        ) VALUES (?, 'job-1', 'needs_user_review', 'review', 'build', '', ?, ?, 'p1')
        """,
        ("run-1", str(workspace), stable_hash(JD_TEXT)),
    )

    analysis = analyze_resume(RESUME_TEXT, ATS_METADATA, JD_TEXT)
    analysis["bindings"] = {
        "extracted_text_hash": stable_hash(RESUME_TEXT),
        "jd_hash": stable_hash(JD_TEXT),
    }
    analysis_hash = stable_hash(analysis)
    analysis["bindings"]["analysis_hash"] = analysis_hash
    database.execute(
        """
        INSERT INTO ats_analyses(
            id, run_id, analyzer_version, score, analysis_json
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "analysis-1",
            "run-1",
            analysis["analyzer_version"],
            analysis["overall_score"],
            json_dumps(analysis),
        ),
    )
    return {
        "database": database,
        "analysis": analysis,
        "analysis_hash": analysis_hash,
    }


def _review(service: ATSSemanticReviewService) -> Dict[str, Any]:
    return service.review_inputs(
        run_id="run-1",
        resume_text=RESUME_TEXT,
        jd_text=JD_TEXT,
        deterministic_analysis_id="analysis-1",
    )


def test_success_is_advisory_evidence_bound_and_keeps_deterministic_score(
    semantic_context: Dict[str, Any],
):
    database = semantic_context["database"]
    runtime = FakeRuntime([_response()])
    service = ATSSemanticReviewService(database, runtime)
    before = database.fetch_one(
        "SELECT score, analysis_json FROM ats_analyses WHERE id = 'analysis-1'"
    )

    review = _review(service)

    after = database.fetch_one(
        "SELECT score, analysis_json FROM ats_analyses WHERE id = 'analysis-1'"
    )
    assert review["status"] == "complete"
    assert review["provider"] == "fake"
    assert review["model"] == "semantic-test-model"
    assert review["attempt_count"] == 1
    assert review["deterministic_analysis_hash"] == semantic_context["analysis_hash"]
    assert review["response"]["authoritative"] is False
    assert review["response"]["deterministic_reference"]["authoritative"] is True
    assert review["response"]["deterministic_reference"]["overall_score"] == before[
        "score"
    ]
    finding = review["response"]["findings"][0]
    assert finding["ai_assisted"] is True
    assert finding["evidence_verification"]["status"] == "verified"
    assert finding["resume_evidence"] in RESUME_TEXT
    assert finding["jd_evidence"] in JD_TEXT
    assert before == after
    assert len(runtime.calls) == 1
    assert "deterministic ATS result is authoritative" in runtime.calls[0]["prompt"]


def test_malformed_json_retries_only_once_then_persists_failure(
    semantic_context: Dict[str, Any],
):
    runtime = FakeRuntime(["not json", "```json\n{}\n```"])
    service = ATSSemanticReviewService(semantic_context["database"], runtime)

    review = _review(service)

    assert review["status"] == "failed"
    assert review["attempt_count"] == 2
    assert review["error_code"] == "invalid_json"
    assert review["response"] is None
    assert review["input_tokens"] == 34
    assert len(runtime.calls) == 2


def test_hallucinated_evidence_is_rejected_and_never_published(
    semantic_context: Dict[str, Any],
):
    runtime = FakeRuntime(
        [
            _response(resume_evidence="Invented resume sentence"),
            _response(resume_evidence="Still invented resume evidence"),
        ]
    )
    service = ATSSemanticReviewService(semantic_context["database"], runtime)

    review = _review(service)

    assert review["status"] == "failed"
    assert review["error_code"] == "unverified_evidence"
    assert review["response"] is None
    assert review["attempt_count"] == 2


def test_repeat_request_is_idempotent_for_the_same_input_and_model(
    semantic_context: Dict[str, Any],
):
    runtime = FakeRuntime([_response()])
    service = ATSSemanticReviewService(semantic_context["database"], runtime)

    first = _review(service)
    second = _review(service)

    assert first["id"] == second["id"]
    assert first["input_hash"] == second["input_hash"]
    assert len(runtime.calls) == 1
    rows = semantic_context["database"].fetch_all(
        "SELECT id FROM ats_semantic_reviews WHERE run_id = 'run-1'"
    )
    assert rows == [{"id": first["id"]}]


def test_active_running_review_is_idempotent_and_stale_review_is_retried(
    semantic_context: Dict[str, Any],
):
    database = semantic_context["database"]
    blocked_runtime = FakeRuntime([])
    blocked_service = ATSSemanticReviewService(
        database, blocked_runtime, stale_after_seconds=30
    )
    analysis = database.fetch_one(
        "SELECT * FROM ats_analyses WHERE id = 'analysis-1'"
    )
    record = blocked_service._validated_analysis_record(analysis)
    run = blocked_service._completed_run("run-1")
    input_hash = stable_hash(
        {
            "run_id": "run-1",
            "resume_text": RESUME_TEXT,
            "jd_text": JD_TEXT,
            "deterministic_analysis_id": record["id"],
            "deterministic_analysis_hash": record["analysis_hash"],
            "review_version": blocked_service.REVIEW_VERSION,
        }
    )
    runtime_request = blocked_service._runtime_request("auto", None, None)
    idempotency_key = stable_hash(
        input_hash,
        runtime_request["provider"],
        runtime_request["model_key"],
        runtime_request["reasoning_effort"],
        blocked_service.REVIEW_VERSION,
    )
    stale_id, created = blocked_service._ensure_review_row(
        run_id=str(run["id"]),
        analysis_record=record,
        input_hash=input_hash,
        idempotency_key=idempotency_key,
        runtime_request=runtime_request,
    )
    assert created is True
    database.execute(
        "UPDATE ats_semantic_reviews SET updated_at = '2999-01-01 00:00:00' WHERE id = ?",
        (stale_id,),
    )
    active = _review(blocked_service)
    assert active["id"] == stale_id
    assert active["status"] == "running"
    assert blocked_runtime.calls == []
    database.execute(
        "UPDATE ats_semantic_reviews SET updated_at = '2000-01-01 00:00:00' WHERE id = ?",
        (stale_id,),
    )

    runtime = FakeRuntime([_response()])
    service = ATSSemanticReviewService(database, runtime, stale_after_seconds=30)
    review = _review(service)

    assert review["status"] == "complete"
    assert review["id"] != stale_id
    stale = database.fetch_one(
        "SELECT status, error_code FROM ats_semantic_reviews WHERE id = ?",
        (stale_id,),
    )
    assert stale == {"status": "failed", "error_code": "stale_run"}
    assert len(runtime.calls) == 1
    rows = database.fetch_all(
        "SELECT id, idempotency_key FROM ats_semantic_reviews ORDER BY id"
    )
    assert len(rows) == 2
    assert [row["idempotency_key"] for row in rows].count(idempotency_key) == 1


def test_runtime_failure_is_retried_once_and_persisted_without_sensitive_detail(
    semantic_context: Dict[str, Any],
):
    runtime = FakeRuntime(
        [
            RuntimeUnavailable("provider stderr contained token=do-not-store"),
            RuntimeUnavailable("provider stderr contained token=do-not-store"),
        ]
    )
    service = ATSSemanticReviewService(semantic_context["database"], runtime)

    review = _review(service)
    persisted = semantic_context["database"].fetch_one(
        "SELECT * FROM ats_semantic_reviews WHERE id = ?",
        (review["id"],),
    )

    assert review["status"] == "failed"
    assert review["error_code"] == "runtime_unavailable"
    assert review["error"] == "AI runtime was unavailable"
    assert "do-not-store" not in json.dumps(persisted)
    assert persisted["response_json"] is None
    assert persisted["completed_at"] is not None
    assert len(runtime.calls) == 2


def test_runtime_is_not_invoked_without_existing_deterministic_analysis(
    semantic_context: Dict[str, Any],
):
    runtime = FakeRuntime([_response()])
    service = ATSSemanticReviewService(semantic_context["database"], runtime)

    with pytest.raises(
        SemanticReviewInputError,
        match="Deterministic ATS analysis must exist",
    ):
        service.review_inputs(
            run_id="run-1",
            resume_text=RESUME_TEXT,
            jd_text=JD_TEXT,
            deterministic_analysis_id="missing-analysis",
        )

    assert runtime.calls == []


def test_completed_run_loads_the_exact_final_pdf_text_and_frozen_jd(
    semantic_context: Dict[str, Any],
):
    database = semantic_context["database"]
    run = database.fetch_one("SELECT * FROM resume_runs WHERE id = 'run-1'")
    workspace = Path(run["workspace_path"])
    inputs = workspace / "inputs"
    variants = workspace / "variants"
    inputs.mkdir()
    variants.mkdir()
    jd_path = inputs / "job-description.txt"
    jd_path.write_text(JD_TEXT, encoding="utf-8")
    pdf_path = variants / "resume1.pdf"
    document = canvas.Canvas(str(pdf_path))
    y = 780
    for line in RESUME_TEXT.splitlines():
        document.drawString(60, y, line)
        y -= 16
    document.save()
    extracted = "\n".join(
        page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages
    )

    analysis = analyze_resume(extracted, ATS_METADATA, JD_TEXT)
    analysis["bindings"] = {
        "extracted_text_hash": stable_hash(extracted),
        "jd_hash": stable_hash(JD_TEXT),
        "pdf_hash": ArtifactVault.hash_file(pdf_path),
    }
    analysis_hash = stable_hash(analysis)
    analysis["bindings"]["analysis_hash"] = analysis_hash
    database.execute(
        """
        UPDATE ats_analyses
        SET analyzer_version = ?, score = ?, analysis_json = ?
        WHERE id = 'analysis-1'
        """,
        (
            analysis["analyzer_version"],
            analysis["overall_score"],
            json_dumps(analysis),
        ),
    )
    result = {
        "variant": 1,
        "artifacts": {"pdf": str(pdf_path.resolve())},
        "ats_analysis": analysis,
        "provenance": {
            "pdf_hash": ArtifactVault.hash_file(pdf_path),
            "extracted_text_hash": stable_hash(extracted),
            "ats_analysis_hash": analysis_hash,
        },
    }
    result_path = workspace / "result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    database.execute(
        "UPDATE resume_runs SET result_path = ? WHERE id = 'run-1'",
        (str(result_path.resolve()),),
    )
    resume_evidence = "Built FastAPI services handling 2 million requests each month."
    runtime = FakeRuntime([_response(resume_evidence=resume_evidence)])
    service = ATSSemanticReviewService(database, runtime)

    review = service.review_run("run-1")

    assert review["status"] == "complete"
    assert review["deterministic_analysis_hash"] == analysis_hash
    assert review["response"]["findings"][0]["evidence_verification"][
        "status"
    ] == "verified"
    assert json.loads(runtime.calls[0]["prompt"].split("INPUT=", 1)[1])[
        "resume_text"
    ] == extracted


def test_migration_persists_required_semantic_review_metadata(tmp_path: Path):
    database = Database(
        tmp_path / "schema.db",
        Path(__file__).resolve().parents[1] / "app" / "migrations",
    )
    database.initialize()

    with sqlite3.connect(database.path) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(ats_semantic_reviews)")
        }
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(ats_semantic_reviews)"
        ).fetchall()

    assert {
        "run_id",
        "deterministic_analysis_id",
        "deterministic_analysis_hash",
        "input_hash",
        "provider",
        "model",
        "reasoning_effort",
        "status",
        "response_json",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "created_at",
        "updated_at",
        "completed_at",
        "error",
        "review_version",
        "prompt_version",
        "schema_version",
    } <= columns
    assert any(row[2] == "resume_runs" and row[3] == "run_id" for row in foreign_keys)
    assert any(
        row[2] == "ats_analyses" and row[3] == "deterministic_analysis_id"
        for row in foreign_keys
    )
