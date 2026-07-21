from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from app.connectors.base import JobCandidate, infer_work_mode
from app.main import build_container
from app.schemas import PreferenceUpdateRequest
from app.services.search import SearchService, classify_freshness
from app.services.preference_intelligence import interpret_preference_message
from app.utils import json_dumps, new_id, utcnow


def candidate(
    *,
    external_id: str = "candidate-1",
    title: str = "Backend Engineer",
    description: str = "Build reliable Python APIs and services.",
    location: str = "Hyderabad, India",
    work_mode: str | None = "hybrid",
    posted_hours_ago: float = 2,
) -> JobCandidate:
    return JobCandidate(
        connector_id="greenhouse-phonepe",
        external_id=external_id,
        title=title,
        company="Example",
        description=description,
        location=location,
        work_mode=work_mode,
        employment_type="Full-time",
        posted_at=(utcnow() - timedelta(hours=posted_hours_ago)).isoformat(),
        posted_semantics="first_published",
        apply_url="https://boards-api.greenhouse.io/example/jobs/1",
        source_url="https://boards-api.greenhouse.io/example/jobs/1",
        source_family="greenhouse",
        raw={},
    )


def strict_plan(**overrides: Any) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "target_roles": ["Backend Engineer"],
        "role_aliases": ["Backend Engineer"],
        "locations": ["India"],
        "excluded_locations": [],
        "work_modes": [],
        "seniority_tolerance": "Fresher to 2 years",
        "excluded_keywords": [],
        "freshness_hours": 48,
        "source_families": ["greenhouse"],
    }
    plan.update(overrides)
    return plan


@pytest.fixture()
def search(settings):
    return build_container(settings).search


@pytest.mark.parametrize("blank_field", ["target_roles", "preferred_locations"])
def test_preference_validation_rejects_blank_scope_values(blank_field: str):
    payload = {
        "target_roles": ["Backend Engineer"],
        "preferred_locations": ["India"],
    }
    payload[blank_field] = [" \t\n "]

    with pytest.raises(ValidationError, match="cannot contain blank values"):
        PreferenceUpdateRequest.model_validate(payload)


def test_preference_validation_normalizes_scope_whitespace():
    request = PreferenceUpdateRequest(
        target_roles=["  Backend   Platform\tEngineer  "],
        preferred_locations=["  Remote\n India  "],
    )

    assert request.target_roles == ["Backend Platform Engineer"]
    assert request.preferred_locations == ["Remote India"]


def test_whitespace_alias_can_never_match_a_title(search):
    reasons = search._candidate_rejection_reasons(
        candidate(title="Unrelated Data Analyst"),
        strict_plan(role_aliases=["", " \t "]),
    )

    assert "role_outside_policy" in reasons


def test_software_engineer_alias_rejects_software_quality_engineer(search):
    reasons = search._candidate_rejection_reasons(
        candidate(title="Software Quality Engineer"),
        strict_plan(
            target_roles=["Software Engineer"],
            role_aliases=["Software Engineer"],
        ),
    )

    assert "role_outside_policy" in reasons


def test_backend_engineer_alias_allows_backend_software_engineer(search):
    reasons = search._candidate_rejection_reasons(
        candidate(title="Backend Software Engineer"),
        strict_plan(role_aliases=["Backend Engineer"]),
    )

    assert "role_outside_policy" not in reasons


def test_exclusion_parser_splits_or_joined_role_terms():
    interpreted = interpret_preference_message(
        "Avoid sales or support roles",
        {"excluded_keywords": []},
    )

    exclusion = next(
        item for item in interpreted["updates"] if item["key"] == "excluded_keywords"
    )
    assert exclusion["value"] == ["sales", "support"]


def test_devops_role_exclusion_is_title_scoped(search):
    plan = strict_plan(excluded_keywords=["devops"])
    software = candidate(
        title="Backend Engineer",
        description="Collaborate with the DevOps team to ship Python services.",
    )
    devops = candidate(
        title="DevOps Engineer",
        description="Build deployment automation.",
    )

    assert "excluded_keyword" not in search._candidate_rejection_reasons(
        software, plan
    )
    assert "excluded_keyword" in search._candidate_rejection_reasons(devops, plan)


@pytest.mark.parametrize("preference", ["India", "Remote India"])
def test_indiana_never_matches_india_preferences(preference: str):
    indiana = candidate(
        location="Indianapolis, Indiana, United States",
        work_mode="remote" if preference == "Remote India" else "onsite",
    )

    assert not SearchService._location_allowed(
        indiana,
        strict_plan(locations=[preference]),
    )
    assert SearchService._location_allowed(
        candidate(location="Hyderabad, India", work_mode="remote"),
        strict_plan(locations=[preference]),
    )


def test_location_aliases_keep_priority_order_and_matching_score(search):
    plan = strict_plan(locations=["Bengaluru", "Hyderabad"])
    bangalore = candidate(location="Bangalore, India")
    assert SearchService._location_allowed(bangalore, plan)

    score, reason, risk = search.matching._location_score(
        "Bangalore, India",
        "hybrid",
        ["Bengaluru", "Hyderabad"],
    )
    assert score == 15.0
    assert "preference #1" in reason
    assert risk == ""


def test_sde_i_compiles_to_software_engineer_title_alias(settings):
    container = build_container(settings)
    profile = {
        "role_families": ["SDE I"],
        "skills": ["Python"],
        "approved_evidence_ids": [],
    }
    container.database.execute(
        """
        INSERT INTO profile_snapshots(id, version, profile_json, capsule, status)
        VALUES (?, ?, ?, 'SDE profile', 'active')
        """,
        (new_id(), new_id(), json_dumps(profile)),
    )
    container.preferences.set_many(
        [
            {"key": "target_roles", "value": ["SDE I"], "kind": "hard"},
            {"key": "preferred_locations", "value": ["India"], "kind": "hard"},
        ]
    )
    plan = container.plans.compile()["plan"]
    assert "software engineer" in [alias.casefold() for alias in plan["role_aliases"]]
    reasons = container.search._candidate_rejection_reasons(
        candidate(title="Software Engineer I"),
        plan,
    )
    assert "role_outside_policy" not in reasons


def test_role_exclusion_does_not_reject_incidental_description_language(search):
    software_role = candidate(
        title="Software Engineer I",
        description="Build Python services and participate in production support.",
    )
    support_role = candidate(
        external_id="candidate-support",
        title="Technical Support Engineer",
        description="Resolve customer incidents.",
    )
    plan = strict_plan(
        role_aliases=["Software Engineer", "Support Engineer"],
        excluded_keywords=["support"],
    )

    assert "excluded_keyword" not in search._candidate_rejection_reasons(
        software_role, plan
    )
    assert "excluded_keyword" in search._candidate_rejection_reasons(
        support_role, plan
    )


def test_freshness_uses_exact_configured_hours_and_keeps_labels(search):
    thirteen_hours_old = candidate(posted_hours_ago=13)
    thirty_hours_old = candidate(posted_hours_ago=30)
    sixty_hours_old = candidate(posted_hours_ago=60)

    assert classify_freshness(thirteen_hours_old.posted_at, live=True) == "verified_24h"
    assert "freshness_outside_policy" in search._candidate_rejection_reasons(
        thirteen_hours_old,
        strict_plan(freshness_hours=12),
    )

    assert classify_freshness(thirty_hours_old.posted_at, live=True) == "verified_48h"
    assert "freshness_outside_policy" not in search._candidate_rejection_reasons(
        thirty_hours_old,
        strict_plan(freshness_hours=36),
    )

    assert classify_freshness(sixty_hours_old.posted_at, live=True) == "older_live"
    assert "freshness_outside_policy" not in search._candidate_rejection_reasons(
        sixty_hours_old,
        strict_plan(freshness_hours=72),
    )


def test_jd_minimum_experience_above_tolerance_is_rejected(search):
    too_senior = candidate(
        description=(
            "Required qualifications: 5+ years of backend engineering experience."
        )
    )
    within_tolerance = candidate(
        external_id="candidate-2",
        description="Required qualifications: 1-2 years of professional experience.",
    )

    assert SearchService._minimum_required_experience(
        "Minimum experience required: 6 years."
    ) == 6
    assert "seniority_outside_policy" in search._candidate_rejection_reasons(
        too_senior,
        strict_plan(),
    )
    assert "seniority_outside_policy" not in search._candidate_rejection_reasons(
        within_tolerance,
        strict_plan(),
    )


def test_ambiguous_locations_are_not_inferred_as_onsite():
    assert infer_work_mode("Hyderabad, India") is None
    assert infer_work_mode("Hyderabad, India", "Full-time") is None
    assert infer_work_mode("Office Park, Hyderabad") is None
    assert infer_work_mode("Hyderabad", "office-based") == "onsite"
    assert infer_work_mode("Remote - India", "Full-time") == "remote"


def queue_run(search, plan: Dict[str, Any]) -> str:
    plan_id = new_id()
    run_id = new_id()
    search.database.execute(
        """
        INSERT INTO search_plans(
            id, version, profile_version, preference_version, plan_json, status
        ) VALUES (?, ?, 'profile-v1', 'preferences-v1', ?, 'active')
        """,
        (plan_id, new_id(), json_dumps(plan)),
    )
    search.database.execute(
        """
        INSERT INTO search_runs(id, plan_id, status, stage)
        VALUES (?, ?, 'queued', 'queued')
        """,
        (run_id, plan_id),
    )
    return run_id


async def test_outer_run_failure_is_persisted_with_useful_error(search, monkeypatch):
    run_id = queue_run(search, strict_plan())

    def fail_connector_setup():
        raise RuntimeError("connector setup exploded")

    monkeypatch.setattr(search, "_connectors", fail_connector_setup)

    await search.run(run_id)
    state = search.run_status(run_id)

    assert state["status"] == "failed"
    assert state["stage"] == "failed"
    assert state["finished_at"] is not None
    assert "connector setup exploded" in state["error"]
    assert state["coverage"]["errors"][-1]["kind"] == "run_failure"


class StaticConnector:
    connector_id = "greenhouse-phonepe"
    source_domain = "boards-api.greenhouse.io"
    family = "greenhouse"

    def __init__(self, candidates: List[JobCandidate]):
        self.candidates = candidates

    async def fetch(self, _client):
        return self.candidates


async def test_candidate_processing_error_makes_run_partial(search, monkeypatch):
    candidates = [
        candidate(external_id="persisted", title="Backend Software Engineer"),
        candidate(external_id="broken", title="Backend Platform Engineer"),
    ]
    run_id = queue_run(search, strict_plan())
    monkeypatch.setattr(search, "_connectors", lambda: [StaticConnector(candidates)])

    def persist(current: JobCandidate, *_args):
        if current.external_id == "broken":
            raise RuntimeError("candidate persistence exploded")
        return "job-1", "verified_24h"

    monkeypatch.setattr(search, "_persist_candidate", persist)
    original_execute = search.database.execute

    def execute(query, params=()):
        if "search_run_jobs" in query:
            return None
        return original_execute(query, params)

    monkeypatch.setattr(search.database, "execute", execute)

    await search.run(run_id)
    state = search.run_status(run_id)

    assert state["status"] == "partial"
    assert state["stage"] == "complete"
    assert state["verified_count"] == 1
    assert "1 selected candidate(s) failed processing" == state["error"]
    assert state["coverage"]["candidate_processing"] == {
        "attempted": 2,
        "succeeded": 1,
        "failed": 1,
    }
    assert any(
        error.get("external_id") == "broken"
        and "candidate persistence exploded" in error["error"]
        for error in state["coverage"]["errors"]
    )
