from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import respx

from app.config import Settings
from app.connectors.base import ConnectorFetchResult
from app.connectors.official_ats import SmartRecruitersConnector
from app.main import build_container
from app.utils import json_dumps, new_id, stable_hash


def smartrecruiters_detail(job_id: str) -> dict:
    return {
        "id": job_id,
        "name": f"Software Engineer {job_id}",
        "active": True,
        "releasedDate": "2026-07-18T05:00:00.000Z",
        "company": {"name": "Bosch"},
        "location": {"fullLocation": "Bengaluru, India", "hybrid": True},
        "typeOfEmployment": {"label": "Full-time"},
        "postingUrl": f"https://jobs.smartrecruiters.com/BoschGroup/{job_id}",
        "applyUrl": f"https://jobs.smartrecruiters.com/BoschGroup/{job_id}?oga=true",
        "jobAd": {
            "sections": {
                "jobDescription": {"text": "<p>Build Python services.</p>"},
            }
        },
    }


@respx.mock
async def test_smartrecruiters_uses_public_list_and_detail_provenance():
    list_route = respx.get(
        "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings",
        params={"limit": 100, "offset": 0, "q": "software", "country": "in"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "totalFound": 1,
                "content": [
                    {
                        "id": "job-1",
                        "name": "Software Engineer",
                        "releasedDate": "2026-07-18T05:00:00.000Z",
                        "location": {"city": "Bengaluru", "country": "in"},
                    }
                ],
            },
        )
    )
    detail_route = respx.get(
        "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/job-1"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "job-1",
                "name": "Software Engineer",
                "active": True,
                "releasedDate": "2026-07-18T05:00:00.000Z",
                "company": {"name": "Bosch"},
                "location": {
                    "fullLocation": "Bengaluru, India",
                    "remote": False,
                    "hybrid": True,
                },
                "typeOfEmployment": {"label": "Full-time"},
                "postingUrl": "https://jobs.smartrecruiters.com/BoschGroup/job-1",
                "applyUrl": "https://jobs.smartrecruiters.com/BoschGroup/job-1?oga=true",
                "jobAd": {
                    "sections": {
                        "jobDescription": {"text": "<p>Build Python services.</p>"},
                        "qualifications": {"text": "<p>Know FastAPI.</p>"},
                    }
                },
            },
        )
    )
    connector = SmartRecruitersConnector(
        "smartrecruiters-bosch",
        "Bosch",
        "Bosch",
        {"company_identifier": "BoschGroup", "q": "software", "country": "in"},
    )

    async with httpx.AsyncClient() as client:
        jobs = await connector.fetch(client)

    assert list_route.called and detail_route.called
    assert jobs.complete is True
    assert jobs.completeness["absence_authoritative"] is False
    assert jobs.completeness["pages_fetched"] == 1
    assert jobs.completeness["total_found"] == 1
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_family == "smartrecruiters"
    assert job.location == "Bengaluru, India"
    assert job.work_mode == "hybrid"
    assert job.employment_type == "Full-time"
    assert job.posted_semantics == "releasedDate"
    assert job.apply_url.endswith("?oga=true")
    assert "Build Python services" in job.description
    assert "Know FastAPI" in job.description


@respx.mock
async def test_smartrecruiters_paginates_all_summaries_and_reports_completeness():
    list_url = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"
    first_page = respx.get(
        list_url,
        params={"limit": 2, "offset": 0, "country": "in"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "totalFound": 3,
                "content": [
                    {"id": "job-1", "releasedDate": "2026-07-18T05:00:00Z"},
                    {"id": "job-2", "releasedDate": "2026-07-18T04:00:00Z"},
                ],
            },
        )
    )
    second_page = respx.get(
        list_url,
        params={"limit": 2, "offset": 2, "country": "in"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "totalFound": 3,
                "content": [
                    {"id": "job-3", "releasedDate": "2026-07-18T03:00:00Z"},
                ],
            },
        )
    )
    for job_id in ("job-1", "job-2", "job-3"):
        respx.get(
            f"https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/{job_id}"
        ).mock(return_value=httpx.Response(200, json=smartrecruiters_detail(job_id)))
    connector = SmartRecruitersConnector(
        "smartrecruiters-bosch",
        "Bosch",
        "Bosch",
        {
            "company_identifier": "BoschGroup",
            "country": "in",
            "limit": 2,
            "detail_limit": 3,
        },
    )

    async with httpx.AsyncClient() as client:
        result = await connector.fetch(client)

    assert first_page.called and second_page.called
    assert result.complete is True
    assert result.completeness == {
        "pages_fetched": 2,
        "page_size": 2,
        "page_limit": 20,
        "total_found": 3,
        "summaries_fetched": 3,
        "details_attempted": 3,
        "details_succeeded": 3,
        "detail_failures": 0,
        "inactive_details": 0,
        "partial_reasons": [],
        "absence_authoritative": False,
        "complete": True,
    }
    assert {job.external_id for job in result} == {"job-1", "job-2", "job-3"}


@respx.mock
async def test_smartrecruiters_detail_bound_marks_result_partial():
    list_url = "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"
    respx.get(list_url, params={"limit": 100, "offset": 0}).mock(
        return_value=httpx.Response(
            200,
            json={
                "totalFound": 3,
                "content": [
                    {"id": "job-1", "releasedDate": "2026-07-18T05:00:00Z"},
                    {"id": "job-2", "releasedDate": "2026-07-18T04:00:00Z"},
                    {"id": "job-3", "releasedDate": "2026-07-18T03:00:00Z"},
                ],
            },
        )
    )
    for job_id in ("job-1", "job-2"):
        respx.get(
            f"https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/{job_id}"
        ).mock(return_value=httpx.Response(200, json=smartrecruiters_detail(job_id)))
    connector = SmartRecruitersConnector(
        "smartrecruiters-bosch",
        "Bosch",
        "Bosch",
        {"company_identifier": "BoschGroup", "detail_limit": 2},
    )

    async with httpx.AsyncClient() as client:
        result = await connector.fetch(client)

    assert result.complete is False
    assert result.completeness["summaries_fetched"] == 3
    assert result.completeness["details_attempted"] == 2
    assert result.completeness["partial_reasons"] == ["detail_limit_reached"]


def test_partial_connector_result_never_reconciles_missing_jobs(settings):
    search = build_container(settings).search
    job_id = new_id()
    search.database.execute(
        """
        INSERT INTO jobs(
            id, connector_id, external_id, canonical_key, title, company,
            description, description_hash, location, apply_url, source_url,
            source_family
        ) VALUES (?, 'smartrecruiters-bosch-india-software', 'known-job', 'known',
                  'Software Engineer', 'Bosch', 'Build APIs', ?, 'Bengaluru, India',
                  'https://jobs.smartrecruiters.com/BoschGroup/known-job',
                  'https://jobs.smartrecruiters.com/BoschGroup/known-job',
                  'smartrecruiters')
        """,
        (job_id, stable_hash("Build APIs")),
    )
    search.database.execute(
        """
        INSERT INTO job_verifications(
            id, job_id, live_state, freshness_class, posting_evidence_json,
            checked_at, apply_host, verifier_version
        ) VALUES (?, ?, 'live', 'verified_24h', '{}',
                  '2026-07-17T00:00:00+00:00',
                  'jobs.smartrecruiters.com', 'test')
        """,
        (new_id(), job_id),
    )

    closed = search._reconcile_source_observation(
        [],
        "smartrecruiters-bosch-india-software",
        complete=False,
    )

    latest = search.database.fetch_one(
        """
        SELECT live_state FROM job_verifications
        WHERE job_id = ? ORDER BY checked_at DESC, rowid DESC LIMIT 1
        """,
        (job_id,),
    )
    assert closed == 0
    assert latest["live_state"] == "live"


def test_filtered_complete_result_never_closes_jobs_outside_the_query(settings):
    search = build_container(settings).search
    job_id = new_id()
    search.database.execute(
        """
        INSERT INTO jobs(
            id, connector_id, external_id, canonical_key, title, company,
            description, description_hash, location, apply_url, source_url,
            source_family
        ) VALUES (?, 'smartrecruiters-bosch-india-software', 'still-live', 'known',
                  'Platform Engineer', 'Bosch', 'Build APIs', ?, 'Bengaluru, India',
                  'https://jobs.smartrecruiters.com/BoschGroup/still-live',
                  'https://jobs.smartrecruiters.com/BoschGroup/still-live',
                  'smartrecruiters')
        """,
        (job_id, stable_hash("Build APIs")),
    )
    search.database.execute(
        """
        INSERT INTO job_verifications(
            id, job_id, live_state, freshness_class, posting_evidence_json,
            apply_host, verifier_version
        ) VALUES (?, ?, 'live', 'verified_24h', '{}',
                  'jobs.smartrecruiters.com', 'test')
        """,
        (new_id(), job_id),
    )
    result = ConnectorFetchResult(
        candidates=[],
        complete=True,
        metadata={"absence_authoritative": False},
    )

    closed = search._reconcile_source_observation(
        result.candidates,
        "smartrecruiters-bosch-india-software",
        complete=result.complete
        and result.completeness.get("absence_authoritative", True),
    )

    assert closed == 0
    assert search.database.fetch_one(
        """
        SELECT live_state FROM job_verifications WHERE job_id = ?
        ORDER BY checked_at DESC, rowid DESC LIMIT 1
        """,
        (job_id,),
    )["live_state"] == "live"


async def test_partial_connector_metadata_marks_search_run_partial(
    settings,
    monkeypatch,
):
    search = build_container(settings).search
    plan_id = new_id()
    run_id = new_id()
    search.database.execute(
        """
        INSERT INTO search_plans(
            id, version, profile_version, preference_version, plan_json, status
        ) VALUES (?, ?, 'profile-v1', 'preferences-v1', ?, 'active')
        """,
        (
            plan_id,
            new_id(),
            json_dumps(
                {
                    "source_families": ["smartrecruiters"],
                    "freshness_hours": 48,
                }
            ),
        ),
    )
    search.database.execute(
        """
        INSERT INTO search_runs(id, plan_id, status, stage)
        VALUES (?, ?, 'queued', 'queued')
        """,
        (run_id, plan_id),
    )

    class PartialConnector:
        connector_id = "smartrecruiters-bosch-india-software"
        source_domain = "api.smartrecruiters.com"
        family = "smartrecruiters"

        async def fetch(self, _client: Any) -> ConnectorFetchResult:
            return ConnectorFetchResult(
                candidates=[],
                complete=False,
                metadata={"partial_reasons": ["detail_limit_reached"]},
            )

    monkeypatch.setattr(search, "_connectors", lambda: [PartialConnector()])

    await search.run(run_id)

    state = search.run_status(run_id)
    source = state["coverage"]["sources"][0]
    assert state["status"] == "partial"
    assert source["status"] == "partial"
    assert source["complete"] is False
    assert source["completeness"]["partial_reasons"] == [
        "detail_limit_reached"
    ]
    assert source["closed_since_previous_observation"] == 0


@respx.mock
async def test_revalidate_known_smartrecruiters_job_uses_direct_detail(
    tmp_path: Path,
):
    settings = Settings(
        project_root=Path(__file__).resolve().parents[2],
        data_dir=tmp_path / "direct-detail-data",
        fixture_jobs_path=None,
        request_timeout_seconds=2,
    )
    search = build_container(settings).search
    job_id = new_id()
    description = "Old description"
    search.database.execute(
        """
        INSERT INTO jobs(
            id, connector_id, external_id, canonical_key, title, company,
            description, description_hash, location, work_mode, employment_type,
            posted_at, posted_semantics, apply_url, source_url, source_family
        ) VALUES (?, 'smartrecruiters-bosch-india-software', 'known-job', 'known',
                  'Software Engineer', 'Bosch', ?, ?, 'Bengaluru, India', 'hybrid',
                  'Full-time', '2026-07-18T05:00:00+00:00', 'releasedDate',
                  'https://jobs.smartrecruiters.com/BoschGroup/known-job',
                  'https://jobs.smartrecruiters.com/BoschGroup/known-job',
                  'smartrecruiters')
        """,
        (job_id, description, stable_hash(description)),
    )
    search.database.execute(
        """
        INSERT INTO job_verifications(
            id, job_id, live_state, freshness_class, posting_evidence_json,
            checked_at, apply_host, verifier_version
        ) VALUES (?, ?, 'live', 'verified_24h', '{}',
                  '2026-07-17T00:00:00+00:00',
                  'jobs.smartrecruiters.com', 'test')
        """,
        (new_id(), job_id),
    )
    search.database.execute(
        """
        INSERT INTO match_results(
            id, job_id, profile_version, preference_version, score, tier,
            factors_json, reasons_json, risks_json, evidence_ids_json
        ) VALUES (?, ?, 'profile-v1', 'preferences-v1', 90, 'excellent',
                  '{}', '[]', '[]', '[]')
        """,
        (new_id(), job_id),
    )
    detail_route = respx.get(
        "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings/known-job"
    ).mock(
        return_value=httpx.Response(
            200,
            json=smartrecruiters_detail("known-job"),
        )
    )
    list_route = respx.get(
        "https://api.smartrecruiters.com/v1/companies/BoschGroup/postings"
    ).mock(return_value=httpx.Response(500))

    result = await search.revalidate(job_id)

    assert detail_route.called
    assert not list_route.called
    assert result["live_state"] == "live"
    assert result["description_changed"] is True
    assert result["posting_evidence"]["official_direct_detail_checked"] is True
