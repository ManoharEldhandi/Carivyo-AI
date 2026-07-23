from __future__ import annotations

from datetime import timedelta

from app.connectors.base import JobCandidate
from app.main import build_container
from app.services.job_sources import SOURCE_CATALOG
from app.services.search_plan import SearchPlanService
from app.utils import utcnow


def candidate(**overrides) -> JobCandidate:
    values = {
        "connector_id": "greenhouse-phonepe",
        "external_id": "job-1",
        "title": "Software Engineer",
        "company": "Example",
        "description": "Build Python APIs and production software systems.",
        "location": "Hyderabad, India",
        "work_mode": None,
        "employment_type": None,
        "posted_at": None,
        "posted_semantics": None,
        "apply_url": "https://job-boards.greenhouse.io/example/jobs/1",
        "source_url": "https://job-boards.greenhouse.io/example/jobs/1",
        "source_family": "greenhouse",
        "raw": {},
    }
    values.update(overrides)
    return JobCandidate(**values)


def broad_plan(**overrides):
    plan = {
        "target_roles": ["Software Engineer", "AI Engineer"],
        "role_aliases": SearchPlanService._role_aliases(
            ["Software Engineer", "AI Engineer"]
        ),
        "role_policy": "expanded_early_career",
        "locations": ["Hyderabad", "Bengaluru", "Remote India"],
        "excluded_locations": [],
        "location_policy": "preference_order",
        "work_modes": ["remote", "hybrid"],
        "employment_types": ["full_time"],
        "metadata_policy": "include_unknown",
        "seniority_tolerance": "0 to 2 years",
        "seniority_policy": "early_career",
        "excluded_keywords": [],
        "excluded_companies": [],
        "freshness_hours": 48,
        "freshness_policy": "ranking",
        "source_families": ["greenhouse"],
    }
    plan.update(overrides)
    return plan


def test_catalog_has_more_than_one_hundred_unique_official_company_boards():
    assert len(SOURCE_CATALOG) >= 100
    assert len({source["id"] for source in SOURCE_CATALOG}) == len(SOURCE_CATALOG)
    assert {source["type"] for source in SOURCE_CATALOG} == {
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "salesforce",
        "goldman",
    }
    assert all(source["company"] and source["config"] for source in SOURCE_CATALOG)


def test_unknown_metadata_and_missing_salary_do_not_reject_a_live_official_job(settings):
    search = build_container(settings).search
    reasons = search._candidate_rejection_reasons(candidate(), broad_plan())

    assert "work_mode_outside_policy" not in reasons
    assert "employment_type_outside_policy" not in reasons
    assert "freshness_outside_policy" not in reasons
    assert reasons == []


def test_older_official_job_is_ranked_but_explicit_freshness_override_is_strict(settings):
    search = build_container(settings).search
    older = candidate(
        posted_at=(utcnow() - timedelta(days=8)).isoformat(),
        posted_semantics="first_published",
    )

    assert "freshness_outside_policy" not in search._candidate_rejection_reasons(
        older, broad_plan()
    )
    assert "freshness_outside_policy" in search._candidate_rejection_reasons(
        older, broad_plan(freshness_policy="strict")
    )


def test_company_specific_early_career_titles_require_the_right_scope(settings):
    search = build_container(settings).search
    salesforce = candidate(
        title="AMTS",
        company="Salesforce",
        description="Build distributed cloud platform software.",
    )
    goldman_engineering = candidate(
        title="Analyst",
        company="Goldman Sachs",
        description="Develop Java services and APIs for our engineering platform.",
    )
    goldman_finance = candidate(
        title="Analyst",
        company="Goldman Sachs",
        description="Perform financial reporting and investment analysis.",
    )

    assert "role_outside_policy" not in search._candidate_rejection_reasons(
        salesforce, broad_plan(role_aliases=[])
    )
    assert "role_outside_policy" not in search._candidate_rejection_reasons(
        goldman_engineering, broad_plan(role_aliases=[])
    )
    assert "role_outside_policy" in search._candidate_rejection_reasons(
        goldman_finance, broad_plan(role_aliases=[])
    )


def test_ranked_location_keeps_unknowns_but_rejects_clear_foreign_only_roles(settings):
    search = build_container(settings).search
    unknown = candidate(location="Unspecified")
    foreign = candidate(location="San Francisco, United States")

    assert "location_outside_policy" not in search._candidate_rejection_reasons(
        unknown, broad_plan()
    )
    assert "location_outside_policy" in search._candidate_rejection_reasons(
        foreign, broad_plan()
    )


def test_clear_senior_titles_remain_out_of_early_career_results(settings):
    search = build_container(settings).search
    senior = candidate(title="Senior Software Engineer")
    level_three = candidate(title="Software Development Engineer III")

    assert "seniority_outside_policy" in search._candidate_rejection_reasons(
        senior, broad_plan(seniority_tolerance="3 to 5 years")
    )
    assert "seniority_outside_policy" in search._candidate_rejection_reasons(
        level_three, broad_plan(seniority_tolerance="3 to 5 years")
    )
