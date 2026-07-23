from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.connectors.base import (
    ConnectorError,
    ConnectorFetchResult,
    ConnectorNotFound,
    JobCandidate,
    OfficialConnector,
    clean_description,
    infer_work_mode,
    parse_iso,
)
from app.utils import utcnow


class GreenhouseConnector(OfficialConnector):
    family = "greenhouse"
    source_domain = "boards-api.greenhouse.io"

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        token = self.config["board_token"]
        payload = await self.request_json(
            client,
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
        )
        jobs = []
        for item in payload.get("jobs", []):
            location_value = item.get("location")
            location = (
                location_value.get("name")
                if isinstance(location_value, dict)
                else location_value
            ) or "Unspecified"
            employment = item.get("employment")
            employment_type = (
                employment.get("name") if isinstance(employment, dict) else None
            )
            jobs.append(
                JobCandidate(
                    connector_id=self.connector_id,
                    external_id=str(item["id"]),
                    title=item.get("title") or "Untitled role",
                    company=item.get("company_name") or self.company,
                    description=clean_description(item.get("content")),
                    location=location,
                    work_mode=infer_work_mode(location),
                    employment_type=employment_type,
                    posted_at=parse_iso(item.get("first_published")),
                    posted_semantics="first_published"
                    if item.get("first_published")
                    else None,
                    apply_url=item.get("absolute_url") or "",
                    source_url=item.get("absolute_url") or "",
                    source_family=self.family,
                    raw=item,
                )
            )
        return ConnectorFetchResult(candidates=jobs)


class LeverConnector(OfficialConnector):
    family = "lever"
    source_domain = "api.lever.co"

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        site = self.config["site"]
        payload = await self.request_json(
            client,
            f"https://api.lever.co/v0/postings/{site}?mode=json",
        )
        jobs = []
        for item in payload if isinstance(payload, list) else []:
            categories = item.get("categories") or {}
            location = categories.get("location") or item.get("country") or "Unspecified"
            created_at = item.get("createdAt")
            posted_at = None
            if isinstance(created_at, (int, float)):
                posted_at = datetime.fromtimestamp(
                    created_at / 1000, tz=timezone.utc
                ).isoformat()
            jobs.append(
                JobCandidate(
                    connector_id=self.connector_id,
                    external_id=str(item["id"]),
                    title=item.get("text") or "Untitled role",
                    company=self.company,
                    description=clean_description(
                        item.get("descriptionPlain"),
                        item.get("openingPlain"),
                        "\n".join(
                            part.get("text", "")
                            for part in item.get("lists", [])
                            if isinstance(part, dict)
                        ),
                        item.get("additionalPlain"),
                    ),
                    location=location,
                    work_mode=infer_work_mode(
                        location, item.get("workplaceType") or categories.get("commitment")
                    ),
                    employment_type=categories.get("commitment"),
                    posted_at=posted_at,
                    posted_semantics="createdAt" if posted_at else None,
                    apply_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                    source_url=item.get("hostedUrl") or item.get("applyUrl") or "",
                    source_family=self.family,
                    raw=item,
                )
            )
        return ConnectorFetchResult(candidates=jobs)


class AshbyConnector(OfficialConnector):
    family = "ashby"
    source_domain = "api.ashbyhq.com"

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        board = self.config["board"]
        payload = await self.request_json(
            client,
            f"https://api.ashbyhq.com/posting-api/job-board/{board}",
        )
        jobs = []
        for item in payload.get("jobs", []):
            if item.get("isListed") is False:
                continue
            location = item.get("location") or "Unspecified"
            jobs.append(
                JobCandidate(
                    connector_id=self.connector_id,
                    external_id=str(item["id"]),
                    title=item.get("title") or "Untitled role",
                    company=self.company,
                    description=clean_description(
                        item.get("descriptionPlain"), item.get("descriptionHtml")
                    ),
                    location=location,
                    work_mode=infer_work_mode(
                        location,
                        "remote" if item.get("isRemote") else item.get("workplaceType"),
                    ),
                    employment_type=item.get("employmentType"),
                    posted_at=parse_iso(item.get("publishedAt")),
                    posted_semantics="publishedAt" if item.get("publishedAt") else None,
                    apply_url=item.get("applyUrl") or item.get("jobUrl") or "",
                    source_url=item.get("jobUrl") or item.get("applyUrl") or "",
                    source_family=self.family,
                    raw=item,
                )
            )
        return ConnectorFetchResult(candidates=jobs)


class SmartRecruitersConnector(OfficialConnector):
    """Official SmartRecruiters public Posting API connector."""

    family = "smartrecruiters"
    source_domain = "api.smartrecruiters.com"
    parser_version = "1.0"
    max_page_size = 100
    max_pages = 20
    max_detail_requests = 200
    detail_concurrency = 4

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        company_identifier = self.config["company_identifier"]
        page_size = max(
            1,
            min(self.max_page_size, int(self.config.get("limit", self.max_page_size))),
        )
        page_limit = max(
            1,
            min(self.max_pages, int(self.config.get("max_pages", self.max_pages))),
        )
        base_params: Dict[str, Any] = {"limit": page_size}
        for key in ("q", "country", "region", "city", "department"):
            if self.config.get(key):
                base_params[key] = self.config[key]

        list_url = (
            "https://api.smartrecruiters.com/v1/companies/"
            f"{company_identifier}/postings"
        )
        summaries: List[Dict[str, Any]] = []
        seen_ids: set[str] = set()
        partial_reasons: List[str] = []
        total_found: Optional[int] = None
        offset = 0
        pages_fetched = 0
        reached_end = False

        for _ in range(page_limit):
            payload = await self.request_json(
                client,
                list_url,
                params={**base_params, "offset": offset},
            )
            if not isinstance(payload, dict) or not isinstance(
                payload.get("content"), list
            ):
                raise ConnectorError(
                    f"{self.name} returned an invalid SmartRecruiters summary page"
                )
            content = payload["content"]
            pages_fetched += 1
            page_total = self._total_found(payload.get("totalFound"))
            if page_total is not None:
                if total_found is not None and page_total != total_found:
                    partial_reasons.append("total_changed_during_pagination")
                total_found = max(total_found or 0, page_total)

            for item in content:
                if not isinstance(item, dict) or not item.get("id"):
                    partial_reasons.append("invalid_summary")
                    continue
                external_id = str(item["id"])
                if external_id in seen_ids:
                    partial_reasons.append("duplicate_summary")
                    continue
                seen_ids.add(external_id)
                summaries.append(item)

            consumed = len(content)
            offset += consumed
            if total_found is not None and offset >= total_found:
                reached_end = True
                break
            if consumed < page_size:
                reached_end = total_found is None or offset >= total_found
                if not reached_end:
                    partial_reasons.append("summary_count_mismatch")
                break
            if consumed == 0:
                break

        if not reached_end:
            partial_reasons.append("pagination_bound_reached")
        if total_found is not None and offset != total_found:
            partial_reasons.append("summary_count_mismatch")

        # Details carry the authoritative active state, direct URLs, and JD. The
        # newest summaries are selected when a configured fan-out bound is hit.
        summaries = sorted(
            (item for item in summaries if isinstance(item, dict) and item.get("id")),
            key=lambda item: parse_iso(item.get("releasedDate")) or "",
            reverse=True,
        )
        detail_limit = max(
            1,
            min(
                self.max_detail_requests,
                int(self.config.get("detail_limit", 40)),
            ),
        )
        selected_summaries = summaries[:detail_limit]
        if len(selected_summaries) < len(summaries):
            partial_reasons.append("detail_limit_reached")
        semaphore = asyncio.Semaphore(self.detail_concurrency)

        async def detail(item: Dict[str, Any]) -> Any:
            async with semaphore:
                try:
                    return await self.request_json(
                        client,
                        (
                            "https://api.smartrecruiters.com/v1/companies/"
                            f"{company_identifier}/postings/{item['id']}"
                        ),
                    )
                except Exception as exc:
                    return exc

        details = await asyncio.gather(
            *(detail(item) for item in selected_summaries)
        )
        jobs: List[JobCandidate] = []
        detail_failures = 0
        inactive_details = 0
        for summary, item in zip(selected_summaries, details):
            if isinstance(item, Exception) or not isinstance(item, dict):
                detail_failures += 1
                continue
            try:
                candidate = self._candidate_from_detail(item, summary)
            except (AttributeError, KeyError, TypeError, ValueError):
                detail_failures += 1
                partial_reasons.append("detail_parse_failed")
                continue
            if candidate is None:
                inactive_details += 1
                continue
            jobs.append(candidate)
        if detail_failures:
            partial_reasons.append("detail_fetch_failed")

        partial_reasons = list(dict.fromkeys(partial_reasons))
        complete = not partial_reasons
        absence_authoritative = not any(
            self.config.get(key)
            for key in ("q", "country", "region", "city", "department")
        )
        return ConnectorFetchResult(
            candidates=jobs,
            complete=complete,
            metadata={
                "pages_fetched": pages_fetched,
                "page_size": page_size,
                "page_limit": page_limit,
                "total_found": total_found,
                "summaries_fetched": len(summaries),
                "details_attempted": len(selected_summaries),
                "details_succeeded": len(selected_summaries) - detail_failures,
                "detail_failures": detail_failures,
                "inactive_details": inactive_details,
                "partial_reasons": partial_reasons,
                "absence_authoritative": absence_authoritative,
            },
        )

    async def fetch_job(
        self,
        client: httpx.AsyncClient,
        external_id: str,
    ) -> Optional[JobCandidate]:
        company_identifier = self.config["company_identifier"]
        try:
            item = await self.request_json(
                client,
                (
                    "https://api.smartrecruiters.com/v1/companies/"
                    f"{company_identifier}/postings/{external_id}"
                ),
            )
        except ConnectorNotFound:
            return None
        if not isinstance(item, dict):
            raise ConnectorError(
                f"{self.name} returned invalid SmartRecruiters job detail"
            )
        return self._candidate_from_detail(item, {"id": external_id})

    @staticmethod
    def _total_found(value: Any) -> Optional[int]:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    def _candidate_from_detail(
        self,
        item: Dict[str, Any],
        summary: Dict[str, Any],
    ) -> Optional[JobCandidate]:
        summary_id = str(summary["id"])
        if item.get("id") is not None and str(item["id"]) != summary_id:
            raise ValueError("SmartRecruiters detail ID did not match its summary")
        if item.get("active") is False:
            return None
        location_data = item.get("location") or summary.get("location") or {}
        if not isinstance(location_data, dict):
            location_data = {}
        location = location_data.get("fullLocation") or ", ".join(
            str(location_data.get(key) or "").strip()
            for key in ("city", "region", "country")
            if str(location_data.get(key) or "").strip()
        ) or "Unspecified"
        explicit_mode = (
            "remote"
            if location_data.get("remote") is True
            else "hybrid"
            if location_data.get("hybrid") is True
            else "onsite"
            if location_data.get("remote") is False
            and location_data.get("hybrid") is False
            else None
        )
        sections = ((item.get("jobAd") or {}).get("sections") or {})
        description_parts = []
        if isinstance(sections, dict):
            for key in (
                "jobDescription",
                "qualifications",
                "additionalInformation",
                "companyDescription",
            ):
                section = sections.get(key)
                if isinstance(section, dict):
                    description_parts.append(section.get("text"))
        employment = item.get("typeOfEmployment") or {}
        company = item.get("company") or {}
        posting_url = item.get("postingUrl") or ""
        apply_url = item.get("applyUrl") or posting_url
        released_date = item.get("releasedDate") or summary.get("releasedDate")
        return JobCandidate(
            connector_id=self.connector_id,
            external_id=str(item.get("id") or summary_id),
            title=item.get("name") or summary.get("name") or "Untitled role",
            company=(
                company.get("name") if isinstance(company, dict) else None
            )
            or self.company,
            description=clean_description(*description_parts),
            location=location,
            work_mode=explicit_mode or infer_work_mode(location),
            employment_type=(
                employment.get("label") if isinstance(employment, dict) else None
            ),
            posted_at=parse_iso(released_date),
            posted_semantics="releasedDate" if released_date else None,
            apply_url=apply_url,
            source_url=posting_url or apply_url,
            source_family=self.family,
            raw=item,
        )


class SalesforceConnector(OfficialConnector):
    """Salesforce's official, timestamped public careers export."""

    family = "company_portal"
    source_domain = "a.sfdcstatic.com"
    parser_version = "1.0"

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        payload = await self.request_json(client, self.config["feed_url"])
        entries = payload.get("Report_Entry", []) if isinstance(payload, dict) else []
        jobs: List[JobCandidate] = []
        invalid = 0
        for item in entries if isinstance(entries, list) else []:
            if not isinstance(item, dict):
                invalid += 1
                continue
            external_id = str(item.get("Job_Requisition_Ref_ID") or "").strip()
            apply_url = str(item.get("External_Job_Posting_Site") or "").strip()
            if not external_id or not apply_url:
                invalid += 1
                continue
            location = str(
                item.get("Job_Requisition_Primary_Location") or "Unspecified"
            )
            posted = item.get("External_Job_Posting_Start_Date")
            jobs.append(
                JobCandidate(
                    connector_id=self.connector_id,
                    external_id=external_id,
                    title=item.get("Job_Posting_Title") or "Untitled role",
                    company=self.company,
                    description=clean_description(item.get("Job_Description")),
                    location=location,
                    work_mode=infer_work_mode(location),
                    employment_type=item.get("Time_Type") or item.get("Employee_Type"),
                    posted_at=parse_iso(posted),
                    posted_semantics=(
                        "External_Job_Posting_Start_Date" if posted else None
                    ),
                    apply_url=apply_url,
                    source_url=apply_url,
                    source_family=self.family,
                    raw=item,
                )
            )
        complete = invalid == 0 and isinstance(entries, list)
        return ConnectorFetchResult(
            candidates=jobs,
            complete=complete,
            metadata={
                "feed_timestamp": payload.get("Fetch_Timestamp")
                if isinstance(payload, dict)
                else None,
                "reported_count": payload.get("Count")
                if isinstance(payload, dict)
                else None,
                "invalid_entries": invalid,
                "absence_authoritative": complete,
            },
        )


class GoldmanSachsConnector(OfficialConnector):
    """Goldman Sachs Higher official role-search GraphQL connector."""

    family = "company_portal"
    source_domain = "api-higher.gs.com"
    parser_version = "1.0"
    query = """
        query GetRoles($searchQueryInput: RoleSearchQueryInput!) {
          roleSearch(searchQueryInput: $searchQueryInput) {
            totalCount
            items {
              roleId corporateTitle jobTitle jobFunction status division skills
              locations { primary state country city }
              jobType { code description }
              externalSource { sourceId }
            }
          }
        }
    """

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        page_size = max(1, min(500, int(self.config.get("page_size", 250))))
        max_pages = max(1, min(10, int(self.config.get("max_pages", 4))))
        items: List[Dict[str, Any]] = []
        total_count: Optional[int] = None
        for page_number in range(max_pages):
            response = await client.post(
                self.config["graphql_url"],
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Origin": "https://higher.gs.com",
                    "User-Agent": "Carivyo/0.1 local job verifier",
                },
                json={
                    "operationName": "GetRoles",
                    "variables": {
                        "searchQueryInput": {
                            "page": {
                                "pageSize": page_size,
                                "pageNumber": page_number,
                            },
                            "sort": {
                                "sortStrategy": "RELEVANCE",
                                "sortOrder": "DESC",
                            },
                            "filters": [
                                {
                                    "filterCategoryType": "LOCATION",
                                    "filters": [
                                        {
                                            "filter": self.config.get(
                                                "country", "India"
                                            ),
                                            "subFilters": [],
                                        }
                                    ],
                                }
                            ],
                            "experiences": ["EARLY_CAREER", "PROFESSIONAL"],
                            "searchTerm": "",
                        }
                    },
                    "query": self.query,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("errors"):
                raise ConnectorError(f"{self.name} GraphQL returned errors")
            result = ((payload.get("data") or {}).get("roleSearch") or {})
            page_items = result.get("items") or []
            if not isinstance(page_items, list):
                raise ConnectorError(f"{self.name} returned invalid role items")
            items.extend(item for item in page_items if isinstance(item, dict))
            try:
                total_count = int(result.get("totalCount"))
            except (TypeError, ValueError):
                total_count = None
            if len(items) >= (total_count or 0) or len(page_items) < page_size:
                break

        jobs: List[JobCandidate] = []
        for item in items:
            role_id = str(item.get("roleId") or "").strip()
            if not role_id or str(item.get("status") or "").casefold() == "closed":
                continue
            locations = item.get("locations") or []
            location_item = next(
                (
                    value
                    for value in locations
                    if isinstance(value, dict) and value.get("primary")
                ),
                next((value for value in locations if isinstance(value, dict)), {}),
            )
            location = ", ".join(
                dict.fromkeys(
                    str(location_item.get(key) or "").strip()
                    for key in ("city", "state", "country")
                    if str(location_item.get(key) or "").strip()
                )
            ) or "Unspecified"
            skills = item.get("skills") or []
            if not isinstance(skills, list):
                skills = [str(skills)]
            description = clean_description(
                "\n".join(
                    [
                        f"Corporate title: {item.get('corporateTitle') or ''}",
                        f"Division: {item.get('division') or ''}",
                        f"Job function: {item.get('jobFunction') or ''}",
                        "Skills: " + ", ".join(str(value) for value in skills),
                    ]
                )
            )
            url = f"https://higher.gs.com/roles/{role_id}"
            job_type = item.get("jobType") or {}
            jobs.append(
                JobCandidate(
                    connector_id=self.connector_id,
                    external_id=role_id,
                    title=item.get("jobTitle") or "Untitled role",
                    company=self.company,
                    description=description,
                    location=location,
                    work_mode=infer_work_mode(location),
                    employment_type=(
                        job_type.get("description")
                        if isinstance(job_type, dict)
                        else None
                    ),
                    posted_at=None,
                    posted_semantics=None,
                    apply_url=url,
                    source_url=url,
                    source_family=self.family,
                    raw=item,
                )
            )
        complete = total_count is not None and len(items) >= total_count
        return ConnectorFetchResult(
            candidates=jobs,
            complete=complete,
            metadata={
                "total_found": total_count,
                "items_fetched": len(items),
                "absence_authoritative": complete,
            },
        )


class FixtureConnector(OfficialConnector):
    family = "fixture"
    source_domain = "fixture.local"

    def __init__(self, path: Path):
        super().__init__("fixture", "Test fixtures", "Fixture", {"path": str(path)})
        self.path = path

    async def fetch(self, client: httpx.AsyncClient) -> ConnectorFetchResult:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        jobs = []
        for item in payload:
            posted_at = (
                utcnow() - timedelta(hours=float(item.get("posted_hours_ago", 12)))
            ).isoformat()
            jobs.append(
                JobCandidate(
                    connector_id=item["connector_id"],
                    external_id=item["external_id"],
                    title=item["title"],
                    company=item["company"],
                    description=item["description"],
                    location=item["location"],
                    work_mode=item.get("work_mode"),
                    employment_type=item.get("employment_type", "Full-time"),
                    posted_at=posted_at if item.get("date_verified", True) else None,
                    posted_semantics=item.get("posted_semantics", "fixture_published"),
                    apply_url=item["apply_url"],
                    source_url=item.get("source_url", item["apply_url"]),
                    source_family=item["source_family"],
                    raw=item,
                )
            )
        return ConnectorFetchResult(candidates=jobs)
