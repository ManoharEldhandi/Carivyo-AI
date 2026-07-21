from __future__ import annotations

import sqlite3
from pathlib import Path

from app.db import Database
from app.services.ats import (
    ANALYZER_VERSION,
    CATEGORY_WEIGHTS,
    CHECK_WEIGHTS,
    ATSAnalyzer,
    analyze_resume,
)


JOB_DESCRIPTION = """
Backend Engineer
We are looking for a Backend Engineer to build Python and FastAPI services using
PostgreSQL, Redis, Docker, Kubernetes, and AWS. The engineer will design REST APIs,
communicate with stakeholders, collaborate across functions, own production
reliability, and mentor teammates.
""".strip()


STRONG_RESUME = """
AVERY CANDIDATE
Backend Engineer
avery.candidate@example.com | +91 90000 00000
https://www.linkedin.com/in/avery-candidate | https://github.com/avery-candidate

SUMMARY
Backend engineer building reliable APIs and data systems.

SKILLS
Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS, REST

EXPERIENCE
Backend Engineer, Example Labs | Jan 2024 - Present
- Built Python and FastAPI services that handled 2 million requests per month.
- Reduced PostgreSQL query latency by 42% through indexes and cache-aware access.
- Led a 4-engineer reliability project using Docker, Kubernetes, Redis, and AWS.
- Collaborated with stakeholders and mentored 2 teammates on production reviews.

PROJECTS
- Designed a REST API deployment pipeline that cut release time from 40 to 12 minutes.

EDUCATION
Bachelor of Technology in Computer Science | 2020 - 2024
""".strip()


WEAK_RESUME = """
Candidate
candidate@example.com

OBJECTIVE
I want a job and I am responsible for work.

EXPERIENCE
Responsible for work.
Responsible for work.
Responsible for work.

EDUCATION
College
""".strip()


STRONG_METADATA = {
    "filename": "Avery_Candidate_Resume.pdf",
    "file_format": "pdf",
    "size_bytes": 180_000,
    "column_count": 1,
    "has_tables": False,
    "has_text_boxes": False,
    "image_only": False,
    "job_title": "Backend Engineer",
    "linkedin_url": "https://www.linkedin.com/in/avery-candidate",
}


def test_contract_has_exactly_27_versioned_transparent_checks():
    result = analyze_resume(STRONG_RESUME, STRONG_METADATA, JOB_DESCRIPTION)

    assert result["analyzer_version"] == ANALYZER_VERSION
    assert len(result["checks"]) == 27
    assert len({check["id"] for check in result["checks"]}) == 27
    assert len(result["category_summaries"]) == 7
    assert sum(CHECK_WEIGHTS.values()) == 100
    assert sum(CATEGORY_WEIGHTS.values()) == 100
    assert all(
        set(check) == {
            "id",
            "label",
            "category",
            "status",
            "score",
            "max_score",
            "evidence",
            "suggestion",
        }
        for check in result["checks"]
    )
    assert "No universal ATS score exists" in result["disclaimer"]
    assert result["scoring"]["configured_max_score"] == 100


def test_score_is_deterministic_and_bounded():
    analyzer = ATSAnalyzer()
    first = analyzer.analyze(STRONG_RESUME, STRONG_METADATA, JOB_DESCRIPTION)
    second = analyzer.analyze(STRONG_RESUME, STRONG_METADATA, JOB_DESCRIPTION)

    assert first == second
    assert 0 <= first["overall_score"] <= 100
    assert 0 <= first["parse_rate"] <= 100
    assert all(0 <= check["score"] <= check["max_score"] for check in first["checks"])


def test_report_exposes_evidence_bound_alignment_and_recruiter_review():
    result = analyze_resume(STRONG_RESUME, STRONG_METADATA, JOB_DESCRIPTION)

    assert result["report_summary"]["readiness"] in {
        "strong",
        "review",
        "needs_focus",
        "blocked",
    }
    assert sum(result["report_summary"]["status_counts"].values()) == 27
    assert result["job_alignment"]["available"] is True
    assert "Python" in result["job_alignment"]["hard_skills"]["matched"]
    assert result["methodology"]["human_review_required"] is True
    for probe in result["recruiter_insights"]["interview_probes"]:
        assert probe["evidence"] in STRONG_RESUME
        assert "invent" not in probe["question"].casefold()
    assert "never invent" in result["recruiter_insights"]["safe_fix_policy"].casefold()


def test_wrapped_bullets_and_header_title_are_not_misclassified():
    resume = """
AVERY CANDIDATE
Software Engineer
avery@example.com

SUMMARY
Backend engineer working on services.

SKILLS
Python, FastAPI

EXPERIENCE
Software Engineer | Example Labs | Jan 2025 - Present
• Implemented a Python service with validation and logging for internal users,
  reducing repeated manual checks without changing the approved evidence.
• Supported release reviews and documented API behavior for engineering teams.

PROJECTS
• Built a FastAPI project with deterministic tests and structured error handling.

EDUCATION
Bachelor of Technology | 2021 - 2025
""".strip()
    result = analyze_resume(
        resume,
        {**STRONG_METADATA, "job_title": "Backend Software Engineer"},
        JOB_DESCRIPTION,
    )
    action_check = next(
        check for check in result["checks"] if check["id"] == "action_verbs"
    )
    title_check = next(
        check for check in result["checks"] if check["id"] == "tailored_title"
    )

    assert action_check["status"] == "pass"
    assert "3/3" in action_check["evidence"][0]
    assert title_check["status"] == "warning"
    assert "2/3" in title_check["evidence"][1]


def test_matching_strong_resume_scores_above_weak_resume():
    strong = analyze_resume(STRONG_RESUME, STRONG_METADATA, JOB_DESCRIPTION)
    weak = analyze_resume(
        WEAK_RESUME,
        {
            "filename": "resume final final.pdf",
            "file_format": "pdf",
            "size_bytes": 9_000_000,
            "column_count": 3,
            "has_tables": True,
            "has_text_boxes": True,
            "image_only": False,
            "job_title": "Backend Engineer",
            "linkedin_url": "https://www.linkedin.com/in/candidate",
        },
        JOB_DESCRIPTION,
    )

    assert strong["overall_score"] > weak["overall_score"]
    assert strong["overall_score"] - weak["overall_score"] >= 25


def test_does_not_infer_age_from_education_or_employment_dates():
    result = analyze_resume(
        STRONG_RESUME.replace("2020 - 2024", "1998 - 2002"),
        STRONG_METADATA,
        JOB_DESCRIPTION,
    )
    sensitive_check = next(
        check for check in result["checks"] if check["id"] == "age_date_bias"
    )

    assert sensitive_check["status"] == "pass"
    assert "does not infer age" in result["protected_trait_policy"]
    assert "age" not in result

    explicit = analyze_resume("Avery Candidate\nDOB: 01/01/1980\navery@example.com")
    explicit_check = next(
        check for check in explicit["checks"] if check["id"] == "age_date_bias"
    )
    assert explicit_check["status"] == "warning"
    assert any("date of birth" in evidence for evidence in explicit_check["evidence"])


def test_empty_or_malformed_input_is_graceful_and_renormalized():
    empty = analyze_resume(None, metadata="malformed", jd_text=None)
    malformed = analyze_resume(b"\xff\xfe\x00")

    for result in (empty, malformed):
        assert len(result["checks"]) == 27
        assert len(result["category_summaries"]) == 7
        assert 0 <= result["overall_score"] <= 100
        assert 0 <= result["parse_rate"] <= 100
        assert result["scoring"]["applicable_max_score"] <= 100
        assert result["scoring"]["not_applicable_check_ids"]
    assert empty["overall_score"] == 0
    assert empty["parse_rate"] == 0
    assert "parse_rate" in empty["critical_failures"]


def test_migration_creates_run_scoped_ats_analysis_table(tmp_path: Path):
    database = Database(
        tmp_path / "carivyo.db",
        Path(__file__).resolve().parents[1] / "app" / "migrations",
    )
    database.initialize()

    with sqlite3.connect(database.path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(ats_analyses)")
        }
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(ats_analyses)"
        ).fetchall()
        indexes = connection.execute("PRAGMA index_list(ats_analyses)").fetchall()

    assert {
        "id",
        "run_id",
        "analyzer_version",
        "score",
        "analysis_json",
        "created_at",
        "updated_at",
    } <= columns
    assert any(row[2] == "resume_runs" and row[3] == "run_id" for row in foreign_keys)
    assert len(indexes) >= 2
