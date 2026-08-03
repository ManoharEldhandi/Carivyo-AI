from __future__ import annotations

from app.services.extraction import build_evidence
from app.services.hiring_agent import LocalHiringAgent
from app.services.resume import ResumeService
from test_resume_approval_integrity import _create_pending_run


def _model_payload():
    return {
        "technical_fit": 20,
        "experience_evidence": 18,
        "project_impact": 15,
        "job_alignment": 16,
        "completeness_clarity": 8,
        "summary": "Evidence directly supports the role.",
    }


def test_local_hiring_agent_is_evidence_bound_and_advisory(settings, monkeypatch):
    from app.main import build_container

    container = build_container(settings)
    agent = LocalHiringAgent(container.database, container.runtime)
    monkeypatch.setattr(container.runtime, "local_model", lambda: "local-test")
    monkeypatch.setattr(
        container.runtime,
        "run_structured",
        lambda *_args, **_kwargs: {
            "provider": "ollama",
            "model": "local-test",
            "data": _model_payload(),
            "input_tokens": 100,
            "output_tokens": 80,
            "cache_read_tokens": 0,
            "usage_kind": "measured",
            "latency_ms": 10,
        },
    )

    result = agent.evaluate(
        run_id="run-1",
        claims=[{"id": "e1", "category": "experience", "text": "Built APIs."}],
        requirements=[
            {
                "requirement_id": "r1",
                "requirement": "Build APIs",
                "category": "technical_skill",
                "priority": "responsibility",
                "classification": "direct",
            }
        ],
        section_inventory=[
            {"id": "experience", "expected": True, "present": True, "claim_count": 1}
        ],
        deterministic_ats_score=80,
    )

    assert result["status"] == "complete"
    assert result["authoritative"] is False
    assert result["provider"] == "ollama"
    assert result["score"] > 0
    assert result["raw_model_score"] == 77
    baselines = {
        item["id"]: item["deterministic_baseline"]
        for item in result["dimensions"]
    }
    assert len(set(baselines.values())) > 1
    assert "independently" in result["score_basis"].casefold()
    assert all(
        set(dimension["evidence_ids"]) <= {"e1"}
        for dimension in result["dimensions"]
    )


def test_resume_run_includes_complete_sections_and_local_decision_support(
    client,
    monkeypatch,
):
    service = client.app.state.container.hiring_agent
    service.enabled = True
    runtime = client.app.state.container.runtime
    monkeypatch.setattr(runtime, "local_model", lambda: "local-test")
    monkeypatch.setattr(
        runtime,
        "run_structured",
        lambda *_args, **_kwargs: {
            "provider": "ollama",
            "model": "local-test",
            "data": _model_payload(),
            "input_tokens": 100,
            "output_tokens": 80,
            "cache_read_tokens": 0,
            "usage_kind": "measured",
            "latency_ms": 10,
        },
    )

    run = _create_pending_run(client)
    result = run["result"]

    assert result["validation"]["section_completeness_ok"] is True
    assert result["validation"]["parser_consensus_ok"] is True
    assert len(result["artifacts"]["render_pages"]) == result["validation"]["page_count"]
    assert result["validation"]["visual_details"]["validated_page_count"] == result["validation"]["page_count"]
    expected = {
        item["id"] for item in result["section_inventory"] if item["expected"]
    }
    present = {
        item["id"] for item in result["section_inventory"] if item["present"]
    }
    assert expected == present
    assert {"summary", "experience", "projects", "skills", "education"} <= present
    assert result["hiring_evaluation"]["status"] == "complete"
    dimensions = result["hiring_evaluation"]["dimensions"]
    assert len(dimensions) == 5
    assert len({item["deterministic_baseline"] for item in dimensions}) > 1


def test_extraction_recognizes_and_preserves_extended_resume_sections():
    text = """
Alex Candidate
alex@example.com
PROFESSIONAL SUMMARY
Backend engineer building reliable systems.
PROFESSIONAL EXPERIENCE
Engineer | Example Co | 2025 - Present
• Built a reliable API.
PROJECTS
Example — API Platform https://github.com/example/api
• Added deterministic validation.
TECHNICAL SKILLS
Languages: Python, Go
CERTIFICATIONS
Cloud Engineering Certificate
VOLUNTEER EXPERIENCE
• Mentored student developers.
PUBLICATIONS
Reliable APIs in Practice
LANGUAGES
English, Telugu
EDUCATION
Bachelor of Technology in Computer Science
""".strip()

    claims, _summary = build_evidence(text)
    categories = {claim["category"] for claim in claims}

    assert {
        "summary",
        "experience",
        "projects",
        "skills",
        "certifications",
        "volunteer",
        "publications",
        "languages",
        "education",
    } <= categories

    for index, claim in enumerate(claims):
        claim.update(id=str(index), artifact_id="artifact", confidence=1.0)
    selected = ResumeService._select_evidence(
        {"title": "Backend Engineer", "description": "Build reliable Python APIs"},
        claims,
        [],
    )
    assert categories - {"identity"} <= {claim["category"] for claim in selected}
