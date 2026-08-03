from __future__ import annotations

import asyncio
from datetime import timedelta
import json
import subprocess

import httpx
import pytest

from app.connectors.official_ats import (
    GoldmanSachsConnector,
    GreenhouseConnector,
    SalesforceConnector,
)
from app.config import Settings
from app.main import build_container
from app.security import LocalRateLimiter, UnsafeUrl, validate_outbound_url
from app.services.resume import ResumeService
from app.services.runtime import RuntimeGateway
from app.services.search import (
    DomainRequestPacer,
    allowed_apply_hosts,
    allowed_source_hosts,
    classify_freshness,
)
from app.utils import estimate_tokens, utcnow


def test_freshness_classification_is_evidence_based():
    assert classify_freshness((utcnow() - timedelta(hours=2)).isoformat(), True) == "verified_24h"
    assert classify_freshness((utcnow() - timedelta(hours=30)).isoformat(), True) == "verified_48h"
    assert classify_freshness((utcnow() - timedelta(days=4)).isoformat(), True) == "older_live"
    assert classify_freshness(None, True) == "live_date_unverified"
    assert classify_freshness((utcnow() - timedelta(hours=2)).isoformat(), False) == "uncertain"
    assert classify_freshness((utcnow() + timedelta(hours=2)).isoformat(), True) == "live_date_unverified"


def test_outbound_url_guard_blocks_local_networks():
    with pytest.raises(UnsafeUrl):
        validate_outbound_url("http://127.0.0.1/private")
    with pytest.raises(UnsafeUrl):
        validate_outbound_url("http://169.254.169.254/latest/meta-data")
    assert (
        validate_outbound_url(
            "https://jobs.lever.co/example/123",
            allowed_hosts={"jobs.lever.co"},
            resolve_dns=False,
        )
        == "https://jobs.lever.co/example/123"
    )


def test_token_estimation_is_bounded_and_nonzero():
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello") >= 1
    assert estimate_tokens("a" * 4000) == 1000


def test_local_rate_limiter_returns_retry_after():
    limiter = LocalRateLimiter(limit=2, window_seconds=60)
    assert limiter.retry_after("session") is None
    assert limiter.retry_after("session") is None
    assert limiter.retry_after("session") is not None


@pytest.mark.asyncio
async def test_greenhouse_accepts_non_object_employment_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jobs": [
                    {
                        "id": 123,
                        "title": "Backend Engineer",
                        "location": {"name": "Bengaluru"},
                        "employment": "employment_required",
                        "first_published": "2026-07-17T00:00:00Z",
                        "absolute_url": "https://job-boards.greenhouse.io/example/jobs/123",
                        "content": "<p>Build APIs.</p>",
                    }
                ]
            },
        )

    connector = GreenhouseConnector(
        "greenhouse-example",
        "Example",
        "Example",
        {"board_token": "example"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jobs = await connector.fetch(client)

    assert jobs[0].employment_type is None
    assert jobs[0].posted_semantics == "first_published"


def test_source_specific_official_apply_host_is_allowlisted():
    hosts = allowed_apply_hosts("greenhouse-stripe", "greenhouse")
    assert "stripe.com" in hosts
    assert (
        validate_outbound_url(
            "https://stripe.com/jobs/listing/example",
            allowed_hosts=hosts,
            resolve_dns=False,
        )
        == "https://stripe.com/jobs/listing/example"
    )


def test_official_source_hosts_are_separate_from_apply_hosts():
    assert "boards-api.greenhouse.io" in allowed_source_hosts(
        "greenhouse-phonepe", "greenhouse"
    )
    assert "jobs.smartrecruiters.com" in allowed_source_hosts(
        "smartrecruiters-bosch-india-software", "smartrecruiters"
    )
    assert "attacker.example" not in allowed_source_hosts(
        "greenhouse-phonepe", "greenhouse"
    )


@pytest.mark.asyncio
async def test_salesforce_official_export_parses_company_roles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "a.sfdcstatic.com"
        return httpx.Response(
            200,
            json={
                "Fetch_Timestamp": "2026-07-23T16:01+00:00",
                "Count": 1,
                "Report_Entry": [
                    {
                        "Job_Requisition_Ref_ID": "JR330400",
                        "Job_Posting_Title": "Software Engineering AMTS (College Grad)",
                        "Job_Description": "<p>Build cloud platform software.</p>",
                        "Job_Requisition_Primary_Location": "India - Hyderabad",
                        "Time_Type": "Full time",
                        "External_Job_Posting_Start_Date": "2026-07-22",
                        "External_Job_Posting_Site": "https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/example",
                    }
                ],
            },
        )

    connector = SalesforceConnector(
        "salesforce-official-careers",
        "Salesforce official careers",
        "Salesforce",
        {"feed_url": "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.fetch(client)

    assert result.complete is True
    assert result[0].title == "Software Engineering AMTS (College Grad)"
    assert result[0].company == "Salesforce"
    assert result[0].source_family == "company_portal"


@pytest.mark.asyncio
async def test_goldman_official_graphql_parses_india_analyst_roles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["operationName"] == "GetRoles"
        return httpx.Response(
            200,
            json={
                "data": {
                    "roleSearch": {
                        "totalCount": 1,
                        "items": [
                            {
                                "roleId": "12345",
                                "corporateTitle": "Analyst",
                                "jobTitle": "Engineering - Software Engineer - Analyst",
                                "jobFunction": "Software Engineering",
                                "status": "Active",
                                "division": "Engineering Division",
                                "skills": ["Java", "Python"],
                                "locations": [
                                    {
                                        "primary": True,
                                        "city": "Hyderabad",
                                        "state": "Telangana",
                                        "country": "India",
                                    }
                                ],
                                "jobType": {"description": "Full time"},
                                "externalSource": {"sourceId": "12345"},
                            }
                        ],
                    }
                }
            },
        )

    connector = GoldmanSachsConnector(
        "goldman-sachs-higher",
        "Goldman Sachs Higher",
        "Goldman Sachs",
        {
            "graphql_url": "https://api-higher.gs.com/gateway/api/v1/graphql",
            "country": "India",
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await connector.fetch(client)

    assert result.complete is True
    assert result[0].external_id == "12345"
    assert result[0].location == "Hyderabad, Telangana, India"
    assert "Software Engineering" in result[0].description
    assert result[0].apply_url == "https://higher.gs.com/roles/12345"


@pytest.mark.asyncio
async def test_goldman_revalidation_fetches_full_official_role_description():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["operationName"] == "GetRoleById"
        assert payload["variables"] == {
            "externalSourceId": "165704",
            "externalSourceFetch": True,
        }
        return httpx.Response(
            200,
            json={
                "data": {
                    "role": {
                        "roleId": "165704_GS_MID_CAREER",
                        "corporateTitle": "Analyst",
                        "jobTitle": "Engineering - Data Platform - Analyst - Bengaluru",
                        "jobFunction": "Software Engineering",
                        "division": "Engineering",
                        "descriptionHtml": (
                            "<h2>Responsibilities</h2><p>Build reliable Python services "
                            "and data pipelines with engineering partners.</p>"
                            "<h2>Qualifications</h2><p>Experience with SQL, cloud "
                            "platforms, testing, and production support is required.</p>"
                        ),
                        "skillset": None,
                        "locations": [
                            {
                                "primary": True,
                                "city": "Bengaluru",
                                "state": "Karnataka",
                                "country": "India",
                            }
                        ],
                        "jobType": {"description": "Full time"},
                        "compensation": None,
                        "applyActive": True,
                        "status": "POSTED",
                        "externalSource": {
                            "externalApplicationUrl": "https://example.invalid/apply",
                            "applyInExternalSource": True,
                            "sourceId": "165704",
                            "secondarySourceId": "secondary",
                        },
                    }
                }
            },
        )

    connector = GoldmanSachsConnector(
        "goldman-sachs-higher",
        "Goldman Sachs Higher",
        "Goldman Sachs",
        {"graphql_url": "https://api-higher.gs.com/gateway/api/v1/graphql"},
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        job = await connector.fetch_job(client, "165704_GS_MID_CAREER")

    assert job is not None
    assert len(job.description) > 150
    assert "Qualifications" in job.description
    assert job.external_id == "165704_GS_MID_CAREER"
    assert job.apply_url == "https://higher.gs.com/roles/165704_GS_MID_CAREER"


def test_only_controlled_runtime_adapters_are_reported_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
):
    def fake_which(name: str):
        if name in {"codex", "claude"}:
            return f"/usr/local/bin/{name}"
        return None

    monkeypatch.setattr("app.services.runtime.shutil.which", fake_which)
    def fake_run(*args, **kwargs):
        command = args[0]
        stdout = (
            "Logged in using ChatGPT\n"
            if command[-2:] == ["login", "status"]
            else "codex-cli 1.0.0\n"
        )
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout=stdout, stderr=""
        )

    monkeypatch.setattr("app.services.runtime.subprocess.run", fake_run)
    providers = RuntimeGateway(
        Settings(project_root=tmp_path, data_dir=tmp_path / "data")
    ).discover()
    by_id = {provider.id: provider for provider in providers}
    assert by_id["codex"].available is True
    assert by_id["codex"].supports_sessions is True
    assert by_id["claude"].available is False
    assert by_id["claude"].supports_sessions is False
    assert "adapter is enabled" in (by_id["claude"].detail or "")


def test_codex_session_identifier_parser():
    assert (
        RuntimeGateway._codex_session_id(
            '{"type":"thread.started","thread_id":"session-123"}\n'
        )
        == "session-123"
    )
    assert RuntimeGateway._codex_session_id("not-json\n") is None


def test_chat_reuses_persisted_codex_session(settings, monkeypatch: pytest.MonkeyPatch):
    container = build_container(settings)
    calls = []

    monkeypatch.setattr(container.runtime, "resolve_provider", lambda provider: "codex")
    monkeypatch.setattr(
        container.runtime,
        "selection",
        lambda: {
            "provider": "codex",
            "model": "gpt-5.6-terra",
            "reasoning_effort": "low",
        },
    )

    def fake_run_chat(
        prompt: str,
        provider: str,
        session_id: str | None,
        session_key: str | None,
    ):
        calls.append(
            {
                "prompt": prompt,
                "provider": provider,
                "session_id": session_id,
                "session_key": session_key,
            }
        )
        return {
            "provider": "codex",
            "model": "gpt-5.6-terra",
            "content": "Grounded response.",
            "input_tokens": 20,
            "output_tokens": 4,
            "cache_read_tokens": 0,
            "usage_kind": "estimated",
            "latency_ms": 1,
            "provider_session_id": session_id or "session-123",
            "session_reused": bool(session_id),
        }

    monkeypatch.setattr(container.runtime, "run_chat", fake_run_chat)

    first = container.chat.send(
        "Help me think through my next role.",
        None,
        None,
        "jobs",
        "auto",
        True,
    )
    second = container.chat.send(
        "What should I prioritize?",
        first["conversation_id"],
        None,
        "jobs",
        "auto",
        True,
    )

    assert calls[0]["session_id"] is None
    assert calls[1]["session_id"] == "session-123"
    assert calls[0]["session_key"] == calls[1]["session_key"] == first["conversation_id"]
    assert calls[0]["prompt"].count("Help me think through my next role.") == 1
    assert "existing Carivyo conversation context" in calls[1]["prompt"]
    assert len(calls[1]["prompt"]) < len(calls[0]["prompt"])
    assert second["usage"]["session_reused"] is True
    assert second["usage"]["context"][0]["name"] == "session_delta"
    stored = container.database.fetch_one(
        "SELECT provider, provider_session_id FROM conversations WHERE id = ?",
        (first["conversation_id"],),
    )
    assert stored == {"provider": "codex", "provider_session_id": "session-123"}


@pytest.mark.asyncio
async def test_domain_request_pacer_serializes_same_domain():
    pacer = DomainRequestPacer(0.02)
    starts = []

    async def operation():
        starts.append(asyncio.get_running_loop().time())
        return "ok"

    results = await asyncio.gather(
        pacer.run("api.example.test", operation),
        pacer.run("api.example.test", operation),
    )

    assert results == ["ok", "ok"]
    assert starts[1] - starts[0] >= 0.015


def test_tailor_mode_requires_a_supported_editable_base():
    evidence = [
        {
            "artifact_id": "artifact-1",
            "category": "experience",
            "text": "Built a service.",
        }
    ]
    assert (
        ResumeService._mode_for_base(
            {
                "artifact_id": "artifact-1",
                "editable_kind": "text",
                "usable_for_tailoring": 1,
            },
            evidence,
        )
        == "tailor"
    )
    assert (
        ResumeService._mode_for_base(
            {
                "artifact_id": "artifact-1",
                "editable_kind": "tex",
                "usable_for_tailoring": 1,
            },
            evidence,
        )
        == "build"
    )


def test_base_selection_prefers_relevant_editable_evidence():
    job = {
        "title": "Backend Engineer",
        "description": "Build Python APIs and PostgreSQL services.",
    }
    bases = [
        {
            "id": "frontend-base",
            "artifact_id": "artifact-frontend",
            "track": "Frontend Engineer",
            "editable_kind": "text",
            "usable_for_tailoring": 1,
        },
        {
            "id": "backend-base",
            "artifact_id": "artifact-backend",
            "track": "Backend Engineer",
            "editable_kind": "text",
            "usable_for_tailoring": 1,
        },
    ]
    evidence = [
        {
            "id": "claim-frontend",
            "artifact_id": "artifact-frontend",
            "category": "experience",
            "text": "Built React interfaces.",
        },
        {
            "id": "claim-backend",
            "artifact_id": "artifact-backend",
            "category": "experience",
            "text": "Built Python APIs backed by PostgreSQL.",
        },
    ]

    selected, rationale = ResumeService._select_base(job, bases, evidence)

    assert selected["id"] == "backend-base"
    assert rationale["score"] > 0
    assert rationale["evaluated_base_count"] == 2


def test_requirement_map_does_not_hide_atomic_gaps():
    description = (
        "Build Python and FastAPI services, design REST APIs, work with "
        "PostgreSQL, Docker, and AWS. Candidates should have 0-2 years of "
        "software engineering experience and strong backend fundamentals."
    )
    evidence = [
        {
            "id": "claim-backend",
            "text": "Built Python and FastAPI services with PostgreSQL.",
        },
        {
            "id": "claim-skills",
            "text": "Python, FastAPI, PostgreSQL, Docker, AWS",
        },
    ]

    mapped = ResumeService._requirement_evidence_map(description, evidence)
    by_requirement = {
        item["requirement"].casefold(): item["classification"]
        for item in mapped
    }

    assert len(mapped) >= 6
    assert any("work with aws" in key for key in by_requirement)
    assert any(
        "0-2 years" in key and value == "unsupported"
        for key, value in by_requirement.items()
    )
    assert not any(
        "python" in key and "aws" in key
        for key in by_requirement
    )
