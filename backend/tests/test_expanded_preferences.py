from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from app.connectors.base import JobCandidate
from app.main import build_container
from app.schemas import PreferenceUpdateRequest
from app.utils import json_dumps, new_id, stable_hash, utcnow

from test_integration import RESUME, complete_onboarding


def preference_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_roles": ["Backend Engineer"],
        "preferred_locations": ["India"],
    }
    payload.update(overrides)
    return payload


def activate_profile(container) -> None:
    profile = {
        "role_families": ["Backend Engineer"],
        "skills": ["SQL"],
        "approved_evidence_ids": [],
    }
    container.database.execute(
        """
        INSERT INTO profile_snapshots(
            id, version, profile_json, capsule, status
        ) VALUES (?, ?, ?, 'Backend engineer with SQL experience.', 'active')
        """,
        (new_id(), stable_hash(profile), json_dumps(profile)),
    )


def candidate(*, company: str = "Razorpay Technologies") -> JobCandidate:
    return JobCandidate(
        connector_id="greenhouse-razorpay",
        external_id="backend-1",
        title="Backend Engineer",
        company=company,
        description="Build SQL and Kafka services for fintech payment systems.",
        location="Bengaluru, India",
        work_mode="hybrid",
        employment_type="Full-time",
        posted_at=(utcnow() - timedelta(hours=2)).isoformat(),
        posted_semantics="first_published",
        apply_url="https://boards-api.greenhouse.io/razorpay/jobs/1",
        source_url="https://boards-api.greenhouse.io/razorpay/jobs/1",
        source_family="greenhouse",
        raw={},
    )


def strict_plan(**overrides: Any) -> Dict[str, Any]:
    plan: Dict[str, Any] = {
        "target_roles": ["Backend Engineer"],
        "role_aliases": ["Backend Engineer"],
        "locations": ["India"],
        "excluded_locations": [],
        "work_modes": ["hybrid"],
        "seniority_tolerance": "0 to 2 years",
        "excluded_keywords": [],
        "excluded_companies": [],
        "preferred_industries": [],
        "preferred_companies": [],
        "priority_skills": [],
        "freshness_hours": 48,
        "source_families": ["greenhouse"],
    }
    plan.update(overrides)
    return plan


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("preferred_industries", ["  "]),
        ("preferred_companies", ["\t"]),
        ("excluded_companies", ["\n"]),
        ("priority_skills", [""]),
        ("employment_types", ["  "]),
        ("salary_min", -0.01),
        ("salary_currency", "usd"),
        ("salary_currency", "USDX"),
        ("salary_period", "fortnightly"),
    ],
)
def test_expanded_preference_validation_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        PreferenceUpdateRequest.model_validate(preference_payload(**{field: value}))


def test_expanded_preference_validation_normalizes_typed_values():
    request = PreferenceUpdateRequest.model_validate(
        preference_payload(
            preferred_industries=["  Fintech  ", "fintech", "Developer Tools"],
            preferred_companies=["  Razorpay  "],
            excluded_companies=["  Acme   Holdings "],
            priority_skills=[" Apache   Kafka "],
            employment_types=[" Full-time "],
            salary_min=1_200_000,
            salary_currency="INR",
            salary_period="yearly",
        )
    )

    assert request.preferred_industries == ["Fintech", "Developer Tools"]
    assert request.preferred_companies == ["Razorpay"]
    assert request.excluded_companies == ["Acme Holdings"]
    assert request.priority_skills == ["Apache Kafka"]
    assert request.employment_types == ["Full-time"]
    assert request.salary_min == 1_200_000
    assert request.salary_currency == "INR"
    assert request.salary_period == "yearly"


def test_unspecified_expanded_preferences_compile_to_neutral_values(settings):
    container = build_container(settings)
    activate_profile(container)

    plan = container.plans.compile()["plan"]

    for field in (
        "preferred_industries",
        "preferred_companies",
        "excluded_companies",
        "priority_skills",
        "employment_types",
    ):
        assert plan[field] == []
    assert plan["salary_min"] is None
    assert plan["salary_currency"] is None
    assert plan["salary_period"] is None


def test_expanded_preferences_persist_with_provenance_and_compile(client):
    complete_onboarding(client, RESUME)
    update = client.patch(
        "/api/preferences",
        json=preference_payload(
            preferred_locations=["Bengaluru", "Remote India"],
            work_modes=["remote", "hybrid"],
            seniority_tolerance="0 to 2 years",
            excluded_keywords=["sales"],
            excluded_locations=["United States"],
            preferred_industries=["Fintech", "Developer Tools"],
            preferred_companies=["Razorpay", "Postman"],
            excluded_companies=["Acme Payments"],
            priority_skills=["Kafka", "FastAPI"],
            employment_types=["Full-time", "Contract"],
            salary_min=1_200_000,
            salary_currency="INR",
            salary_period="yearly",
        ),
    )

    assert update.status_code == 200, update.text
    response = update.json()
    changed = {item["key"]: item for item in response["changed"]}
    assert changed["preferred_companies"]["source"] == "explicit"
    assert changed["preferred_companies"]["kind"] == "soft"
    assert changed["excluded_companies"]["kind"] == "negative"
    assert changed["employment_types"]["kind"] == "hard"

    expected = {
        "preferred_industries": ["Fintech", "Developer Tools"],
        "preferred_companies": ["Razorpay", "Postman"],
        "excluded_companies": ["Acme Payments"],
        "priority_skills": ["Kafka", "FastAPI"],
        "employment_types": ["Full-time", "Contract"],
        "salary_min": 1_200_000,
        "salary_currency": "INR",
        "salary_period": "yearly",
    }
    plan = response["search_plan"]["plan"]
    expected_plan = {**expected, "employment_types": ["full_time", "contract"]}
    assert {key: plan[key] for key in expected_plan} == expected_plan

    # Older clients do not erase expanded fields when they omit them from PATCH.
    second_update = client.patch(
        "/api/preferences",
        json=preference_payload(preferred_locations=["India"]),
    )
    assert second_update.status_code == 200, second_update.text
    saved = {
        item["key"]: item["value"]
        for item in client.get("/api/preferences").json()["preferences"]
    }
    assert {key: saved[key] for key in expected} == expected
    second_plan = second_update.json()["search_plan"]["plan"]
    assert {key: second_plan[key] for key in expected_plan} == expected_plan


def test_employment_type_is_a_hard_gate_when_configured(settings):
    container = build_container(settings)
    activate_profile(container)
    full_time = candidate()
    contract = candidate()
    contract.employment_type = "Contract"
    unknown = candidate()
    unknown.employment_type = None

    accepted, rejected = container.search._filter_candidates(
        [full_time, contract, unknown],
        strict_plan(employment_types=["full_time"]),
    )

    assert accepted == [full_time]
    assert rejected["employment_type_outside_policy"] == 2


def test_excluded_company_is_a_hard_rejection_even_with_soft_matches(settings):
    container = build_container(settings)
    activate_profile(container)
    plan = strict_plan(
        excluded_companies=["Razorpay"],
        preferred_companies=["Razorpay"],
        preferred_industries=["Fintech"],
        priority_skills=["Kafka"],
    )
    excluded = candidate()

    ranking = container.matching.score(
        {
            "title": excluded.title,
            "company": excluded.company,
            "description": excluded.description,
            "location": excluded.location,
            "work_mode": excluded.work_mode,
            "posted_at": excluded.posted_at,
        },
        "verified_24h",
        plan,
    )
    accepted, rejected = container.search._filter_candidates([excluded], plan)

    assert ranking["factors"]["preference_fit"] == 10.0
    assert accepted == []
    assert rejected["excluded_company"] == 1


def test_soft_preferences_add_bounded_explainable_ranking_evidence(settings):
    container = build_container(settings)
    activate_profile(container)
    plan = strict_plan(
        preferred_companies=["Razorpay"],
        preferred_industries=["Fintech"],
        priority_skills=["Kafka"],
    )
    matching_job = {
        "title": "Backend Engineer",
        "company": "Razorpay Technologies",
        "description": "Build SQL and Kafka services for fintech payment systems.",
        "location": "Bengaluru, India",
        "work_mode": "hybrid",
        "posted_at": utcnow().isoformat(),
    }
    other_job = {
        **matching_job,
        "company": "Other Company",
        "description": "Build SQL services for logistics operations.",
    }

    matching = container.matching.score(matching_job, "verified_24h", plan)
    other = container.matching.score(other_job, "verified_24h", plan)
    neutral = container.matching.score(
        other_job,
        "verified_24h",
        strict_plan(),
    )

    assert matching["score"] > other["score"]
    assert matching["score"] <= 100
    assert matching["factors"]["preference_fit"] == 10.0
    assert other["factors"]["preference_fit"] == 4.0
    assert neutral["factors"]["preference_fit"] == 10.0
    reason_codes = {reason["code"] for reason in matching["reasons"]}
    assert {
        "preferred_company",
        "preferred_industry",
        "priority_skill",
    }.issubset(reason_codes)
    assert all(
        reason["job_span"]
        for reason in matching["reasons"]
        if reason["code"] in reason_codes - {"role_alignment"}
    )
