from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx

from app.artifacts import ArtifactVault
from app.config import Settings
from app.connectors import (
    AshbyConnector,
    FixtureConnector,
    GoldmanSachsConnector,
    GreenhouseConnector,
    LeverConnector,
    SalesforceConnector,
    SmartRecruitersConnector,
)
from app.connectors.base import (
    ConnectorFetchResult,
    JobCandidate,
    OfficialConnector,
)
from app.db import Database
from app.observability import logger
from app.security import UnsafeUrl, validate_outbound_url
from app.services.matching import MatchingService
from app.services.job_sources import SOURCE_CATALOG as OFFICIAL_SOURCE_CATALOG
from app.services.profile import ProfileService
from app.services.preference_intelligence import (
    LOCATION_ALIASES,
    canonical_location,
    excluded_term_matches,
)
from app.services.search_plan import SearchPlanService, normalize_search_plan
from app.services.requirements import analyze_job_description, match_requirements
from app.utils import (
    json_dumps,
    json_loads,
    new_id,
    normalize_space,
    parse_utc_datetime,
    stable_hash,
    tokenize,
    utcnow,
)


class DomainRequestPacer:
    def __init__(self, minimum_interval_seconds: float):
        self.minimum_interval_seconds = max(0.0, minimum_interval_seconds)
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_request: Dict[str, float] = {}

    async def run(self, domain: str, operation):
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            elapsed = loop.time() - self._last_request.get(domain, 0.0)
            wait_for = self.minimum_interval_seconds - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            # Pace request starts without holding the per-domain lock for the
            # entire network response. With dozens of official boards sharing an
            # ATS API host, serializing response bodies made a search take minutes.
            self._last_request[domain] = loop.time()
        return await operation()


SOURCE_CATALOG = OFFICIAL_SOURCE_CATALOG


COMPANY_SPECIFIC_ROLE_ALIASES = {
    "salesforce": {
        "associate member of technical staff",
        "amts",
        "member of technical staff",
        "mts",
    },
    "goldman sachs": {
        "new analyst",
        "engineering analyst",
        "software engineering analyst",
        "technology analyst",
        "analyst",
    },
    "jpmorgan": {"technology analyst", "software engineer program"},
    "jp morgan": {"technology analyst", "software engineer program"},
    "morgan stanley": {"technology analyst"},
    "blackrock": {"technology analyst", "analyst"},
    "citi": {"applications development programmer analyst", "technology analyst"},
    "infosys": {
        "specialist programmer",
        "digital specialist engineer",
        "systems engineer",
    },
    "tata consultancy services": {"assistant system engineer", "graduate engineer trainee"},
    "tcs": {"assistant system engineer", "graduate engineer trainee"},
    "wipro": {"project engineer"},
    "cognizant": {"programmer analyst trainee", "genc"},
    "accenture": {"associate software engineer", "application development associate"},
    "capgemini": {"analyst", "software engineer"},
    "hcl": {"graduate engineer trainee"},
    "oracle": {"applications developer 1", "software developer 1"},
}

TECHNICAL_IMPLEMENTATION_TERMS = {
    "api",
    "backend",
    "code",
    "coding",
    "computer science",
    "developer",
    "devops",
    "frontend",
    "full stack",
    "generative ai",
    "infrastructure",
    "java",
    "javascript",
    "kubernetes",
    "llm",
    "machine learning",
    "microservices",
    "ml",
    "platform",
    "python",
    "react",
    "rest",
    "sql",
    "spring",
    "typescript",
}

INDIA_LOCATION_MARKERS = {
    "ahmedabad",
    "bangalore",
    "bengaluru",
    "bhubaneswar",
    "chandigarh",
    "chennai",
    "coimbatore",
    "delhi",
    "goa",
    "gurgaon",
    "gurugram",
    "hyderabad",
    "india",
    "indore",
    "jaipur",
    "kochi",
    "kolkata",
    "lucknow",
    "mumbai",
    "mysore",
    "mysuru",
    "nagpur",
    "noida",
    "pune",
    "surat",
    "thiruvananthapuram",
    "trivandrum",
    "vadodara",
    "visakhapatnam",
    "vizag",
}

APPLY_HOSTS = {
    "greenhouse": {"job-boards.greenhouse.io", "boards.greenhouse.io"},
    "lever": {"jobs.lever.co"},
    "ashby": {"jobs.ashbyhq.com"},
    "smartrecruiters": {"jobs.smartrecruiters.com", "careers.smartrecruiters.com"},
    "company_portal": set(),
    "fixture": {"jobs.example.com"},
    "manual": set(),
}

SOURCE_HOSTS = {
    "greenhouse": {"boards-api.greenhouse.io", "job-boards.greenhouse.io"},
    "lever": {"api.lever.co", "jobs.lever.co"},
    "ashby": {"api.ashbyhq.com", "jobs.ashbyhq.com"},
    "smartrecruiters": {
        "api.smartrecruiters.com",
        "jobs.smartrecruiters.com",
        "careers.smartrecruiters.com",
    },
    "company_portal": {"higher.gs.com", "a.sfdcstatic.com"},
    "fixture": {"jobs.example.com"},
    "manual": set(),
}


def allowed_apply_hosts(
    connector_id: str,
    source_family: str,
    fixture_jobs_enabled: bool = False,
) -> set[str]:
    if fixture_jobs_enabled and connector_id.startswith("fixture-"):
        return {"jobs.example.com"}
    hosts = set(APPLY_HOSTS.get(source_family, set()))
    source = next(
        (item for item in SOURCE_CATALOG if item["id"] == connector_id),
        None,
    )
    if source:
        hosts.update(source.get("apply_hosts", []))
    return hosts


def allowed_source_hosts(
    connector_id: str,
    source_family: str,
    fixture_jobs_enabled: bool = False,
) -> set[str]:
    if fixture_jobs_enabled and connector_id.startswith("fixture-"):
        return {"jobs.example.com"}
    hosts = set(SOURCE_HOSTS.get(source_family, set()))
    source = next(
        (item for item in SOURCE_CATALOG if item["id"] == connector_id),
        None,
    )
    if source:
        hosts.add(source["domain"])
        hosts.update(source.get("source_hosts", []))
    return hosts


def validate_official_candidate_url(url: str, allowed_hosts: set[str]) -> str:
    """Validate ATS links while permitting official boards to use custom domains."""

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    known_host = any(
        hostname == host.casefold() or hostname.endswith("." + host.casefold())
        for host in allowed_hosts
    )
    if known_host:
        return validate_outbound_url(
            url,
            allowed_hosts=allowed_hosts,
            resolve_dns=False,
        )
    if parsed.scheme != "https":
        raise UnsafeUrl("Custom official application hosts must use HTTPS")
    # Custom domains come directly from the official ATS payload. DNS validation
    # keeps those links useful (Okta and Stripe are examples) without opening SSRF
    # access to loopback, private, link-local, or metadata-network destinations.
    return validate_outbound_url(url, allowed_hosts=None, resolve_dns=True)


def upgrade_official_url(url: str) -> str:
    """Prefer the HTTPS form of an official ATS-provided application route."""

    parsed = urlparse(url)
    if parsed.scheme == "http" and parsed.hostname:
        return parsed._replace(scheme="https").geturl()
    return url


class SearchService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        vault: ArtifactVault,
        profiles: ProfileService,
        plans: SearchPlanService,
        matching: MatchingService,
    ):
        self.settings = settings
        self.database = database
        self.vault = vault
        self.profiles = profiles
        self.plans = plans
        self.matching = matching
        self.log = logger("search")
        self.seed_connectors()

    def seed_connectors(self) -> None:
        with self.database.transaction() as connection:
            for source in SOURCE_CATALOG:
                connection.execute(
                    """
                    INSERT INTO connectors(
                        id, connector_type, name, source_domain, config_json,
                        trust_tier, enabled, parser_version
                    ) VALUES (?, ?, ?, ?, ?, 'official', 1, '1.0')
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        config_json = excluded.config_json,
                        enabled = excluded.enabled,
                        parser_version = excluded.parser_version
                    """,
                    (
                        source["id"],
                        source["type"],
                        source["name"],
                        source["domain"],
                        json_dumps({**source["config"], "company": source["company"]}),
                    ),
                )
            if self.settings.fixture_jobs_path:
                for family in ("greenhouse", "lever", "ashby", "smartrecruiters"):
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO connectors(
                            id, connector_type, name, source_domain, config_json,
                            trust_tier, enabled, parser_version
                        ) VALUES (?, ?, ?, 'fixture.local', '{}', 'fixture', 1, '1.0')
                        """,
                        (f"fixture-{family}", family, f"Fixture {family}"),
                    )

    def create_run(
        self,
        temporary_instruction: Optional[str] = None,
        *,
        reason: str = "manual",
    ) -> Dict[str, Any]:
        plan = (
            self.plans.compile_temporary(temporary_instruction)
            if temporary_instruction
            else self.plans.compile()
        )
        run_id = new_id()
        self.database.execute(
            """
            INSERT INTO search_runs(id, plan_id, status, stage, coverage_json)
            VALUES (?, ?, 'queued', 'queued', ?)
            """,
            (run_id, plan["id"], json_dumps({"trigger": reason})),
        )
        return {"id": run_id, "plan": plan}

    async def run(self, run_id: str) -> None:
        row = self.database.fetch_one(
            """
            SELECT sr.*, sp.plan_json, sp.profile_version, sp.preference_version
            FROM search_runs sr
            JOIN search_plans sp ON sp.id = sr.plan_id
            WHERE sr.id = ?
            """,
            (run_id,),
        )
        if not row:
            raise KeyError("Search run not found")
        plan = normalize_search_plan(json_loads(row["plan_json"], {}))
        self.database.execute(
            "UPDATE search_runs SET status = 'running', stage = 'fetching' WHERE id = ?",
            (run_id,),
        )

        try:
            await self._execute_run(run_id, row, plan)
        except Exception as exc:
            self._mark_run_failed(run_id, exc)

    async def _execute_run(
        self,
        run_id: str,
        row: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> None:

        connectors = self._connectors()
        previous_coverage = json_loads(row.get("coverage_json"), {})
        coverage: Dict[str, Any] = {
            "trigger": previous_coverage.get("trigger", "manual"),
            "sources": [],
            "families": {
                family: 0 for family in plan.get("source_families", [])
            },
            "errors": [],
        }
        candidates: List[JobCandidate] = []
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        limits = httpx.Limits(max_connections=self.settings.connector_concurrency)
        semaphore = asyncio.Semaphore(self.settings.connector_concurrency)
        pacer = DomainRequestPacer(self.settings.connector_min_interval_seconds)

        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
        ) as client:
            async def fetch(connector: OfficialConnector) -> Tuple[OfficialConnector, Any]:
                async with semaphore:
                    async def operation() -> Tuple[OfficialConnector, Any]:
                        try:
                            return connector, await asyncio.wait_for(
                                connector.fetch(client),
                                timeout=self.settings.connector_deadline_seconds,
                            )
                        except Exception as exc:
                            return connector, exc

                    return await pacer.run(connector.source_domain, operation)

            results = await asyncio.gather(*(fetch(connector) for connector in connectors))

        for connector, result in results:
            if isinstance(result, Exception):
                error_message = str(result).strip() or type(result).__name__
                coverage["errors"].append(
                    {"connector": connector.connector_id, "error": error_message}
                )
                coverage["sources"].append(
                    {"connector": connector.connector_id, "status": "failed", "count": 0}
                )
                self.database.execute(
                    """
                    UPDATE connectors
                    SET health = 'degraded', last_checked_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (connector.connector_id,),
                )
                continue
            fetch_result = ConnectorFetchResult.coerce(result)
            fetched_candidates = fetch_result.candidates
            closed_count = self._reconcile_source_observation(
                fetched_candidates,
                connector.connector_id,
                complete=(
                    fetch_result.complete
                    and fetch_result.completeness.get(
                        "absence_authoritative", True
                    )
                ),
            )
            eligible, rejected = self._filter_candidates(fetched_candidates, plan)
            selected = eligible[: self.settings.max_jobs_per_source]
            candidates.extend(selected)
            coverage.setdefault("rejections", {})
            for reason, count in rejected.items():
                coverage["rejections"][reason] = (
                    coverage["rejections"].get(reason, 0) + count
                )
            if selected:
                for candidate in selected:
                    coverage["families"][candidate.source_family] = (
                        coverage["families"].get(candidate.source_family, 0) + 1
                    )
            else:
                coverage["families"].setdefault(connector.family, 0)
            coverage["sources"].append(
                {
                    "connector": connector.connector_id,
                    "status": "ok" if fetch_result.complete else "partial",
                    "complete": fetch_result.complete,
                    "completeness": fetch_result.completeness,
                    "fetched": len(fetched_candidates),
                    "eligible": len(eligible),
                    "selected": len(selected),
                    "rejected": len(fetched_candidates) - len(eligible),
                    "rejected_by_reason": rejected,
                    "closed_since_previous_observation": closed_count,
                }
            )
            self.database.execute(
                """
                UPDATE connectors
                SET health = ?, last_checked_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    "healthy" if fetch_result.complete else "degraded",
                    connector.connector_id,
                ),
            )

        deduped = self._deduplicate(candidates)
        self.database.execute(
            """
            UPDATE search_runs
            SET stage = 'normalizing', discovered_count = ?, coverage_json = ?
            WHERE id = ?
            """,
            (len(deduped), json_dumps(coverage), run_id),
        )
        snapshot_path = self.vault.write_text(
            f"search-runs/{run_id}/normalized.json",
            json.dumps([item.to_dict() for item in deduped], ensure_ascii=False, indent=2),
        )
        self.database.execute(
            "UPDATE search_runs SET stage = 'processing' WHERE id = ?",
            (run_id,),
        )

        verified = 0
        ranked = 0
        candidate_failures = 0
        freshness_counts: Dict[str, int] = {}
        for candidate in deduped:
            try:
                job_id, freshness = await asyncio.to_thread(
                    self._persist_candidate,
                    candidate,
                    row["profile_version"],
                    row["preference_version"],
                    plan,
                    snapshot_path,
                )
                verified += 1
                ranked += 1
                self.database.execute(
                    """
                    INSERT OR REPLACE INTO search_run_jobs(run_id, job_id, ordinal)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, job_id, ranked - 1),
                )
                freshness_counts[freshness] = freshness_counts.get(freshness, 0) + 1
            except Exception as exc:
                candidate_failures += 1
                coverage["errors"].append(
                    {
                        "connector": candidate.connector_id,
                        "external_id": candidate.external_id,
                        "error": str(exc),
                    }
                )
        coverage["freshness"] = freshness_counts
        coverage["candidate_processing"] = {
            "attempted": len(deduped),
            "succeeded": verified,
            "failed": candidate_failures,
        }
        failed_sources = len(
            [source for source in coverage["sources"] if source["status"] == "failed"]
        )
        partial_sources = len(
            [source for source in coverage["sources"] if source["status"] == "partial"]
        )
        successful_sources = len(coverage["sources"]) - failed_sources
        status = "complete"
        error: Optional[str] = None
        if successful_sources == 0:
            status = "failed"
            error = "Every official source failed"
        elif candidate_failures and verified == 0:
            status = "failed"
            error = (
                f"All {candidate_failures} selected candidate(s) failed processing"
            )
        elif failed_sources or partial_sources or candidate_failures:
            status = "partial"
            if candidate_failures:
                error = f"{candidate_failures} selected candidate(s) failed processing"
            elif partial_sources:
                error = (
                    f"{partial_sources} official source(s) returned incomplete results"
                )
        final_stage = "failed" if status == "failed" else "complete"
        self.database.execute(
            """
            UPDATE search_runs
            SET status = ?, stage = ?, verified_count = ?,
                ranked_count = ?, coverage_json = ?, finished_at = CURRENT_TIMESTAMP,
                error = ?
            WHERE id = ?
            """,
            (
                status,
                final_stage,
                verified,
                ranked,
                json_dumps(coverage),
                error,
                run_id,
            ),
        )
        self.log.info(
            "search_run_complete",
            run_id=run_id,
            status=status,
            discovered=len(deduped),
            verified=verified,
            ranked=ranked,
        )

    def _mark_run_failed(self, run_id: str, exc: Exception) -> None:
        row = self.database.fetch_one(
            "SELECT stage, coverage_json FROM search_runs WHERE id = ?",
            (run_id,),
        )
        if not row:
            return
        failed_stage = str(row.get("stage") or "unknown")
        detail = normalize_space(str(exc)) or exc.__class__.__name__
        error = (
            f"Search run failed during {failed_stage}: "
            f"{exc.__class__.__name__}: {detail}"
        )[:2000]
        coverage = json_loads(row.get("coverage_json"), {})
        coverage.setdefault("errors", []).append(
            {
                "stage": failed_stage,
                "error": error,
                "kind": "run_failure",
            }
        )
        self.database.execute(
            """
            UPDATE search_runs
            SET status = 'failed', stage = 'failed', coverage_json = ?,
                error = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json_dumps(coverage), error, run_id),
        )
        self.log.error(
            "search_run_failed",
            run_id=run_id,
            stage=failed_stage,
            error=error,
        )

    def _reconcile_source_observation(
        self,
        candidates: Sequence[JobCandidate],
        connector_id: str,
        complete: bool = True,
    ) -> int:
        """Close persisted listings absent from a successful complete board response."""
        if not complete:
            return 0
        observed: Dict[str, set[str]] = {}
        for candidate in candidates:
            observed.setdefault(candidate.connector_id, set()).add(candidate.external_id)
        if not observed and not connector_id.startswith("fixture"):
            observed[connector_id] = set()
        closed = 0
        for connector_id, external_ids in observed.items():
            rows = self.database.fetch_all(
                "SELECT id, external_id, apply_url FROM jobs WHERE connector_id = ?",
                (connector_id,),
            )
            for row in rows:
                if row["external_id"] in external_ids:
                    continue
                latest = self.database.fetch_one(
                    """
                    SELECT live_state FROM job_verifications
                    WHERE job_id = ?
                    ORDER BY checked_at DESC, rowid DESC LIMIT 1
                    """,
                    (row["id"],),
                )
                if latest and latest["live_state"] == "closed":
                    continue
                self.database.execute(
                    """
                    INSERT INTO job_verifications(
                        id, job_id, live_state, freshness_class,
                        posting_evidence_json, http_status, apply_host,
                        verifier_version, error
                    ) VALUES (?, ?, 'closed', 'closed', ?, 404, ?, '1.1', ?)
                    """,
                    (
                        new_id(),
                        row["id"],
                        json_dumps(
                            {
                                "official_listing_present": False,
                                "reconciled_from_complete_board_response": True,
                            }
                        ),
                        urlparse(row["apply_url"]).hostname or "",
                        "Listing was absent from the latest successful official board response",
                    ),
                )
                closed += 1
        return closed

    def _connectors(self) -> List[OfficialConnector]:
        if self.settings.fixture_jobs_path:
            return [FixtureConnector(self.settings.fixture_jobs_path)]
        connectors: List[OfficialConnector] = []
        for source in SOURCE_CATALOG:
            args = (
                source["id"],
                source["name"],
                source["company"],
                source["config"],
            )
            if source["type"] == "greenhouse":
                connectors.append(GreenhouseConnector(*args))
            elif source["type"] == "lever":
                connectors.append(LeverConnector(*args))
            elif source["type"] == "ashby":
                connectors.append(AshbyConnector(*args))
            elif source["type"] == "smartrecruiters":
                connectors.append(SmartRecruitersConnector(*args))
            elif source["type"] == "salesforce":
                connectors.append(SalesforceConnector(*args))
            elif source["type"] == "goldman":
                connectors.append(GoldmanSachsConnector(*args))
        return connectors

    def _filter_candidates(
        self, candidates: Sequence[JobCandidate], plan: Dict[str, Any]
    ) -> Tuple[List[JobCandidate], Dict[str, int]]:
        selected: List[JobCandidate] = []
        rejected: Dict[str, int] = {}
        for candidate in candidates:
            reasons = self._candidate_rejection_reasons(candidate, plan)
            if reasons:
                for reason in reasons:
                    rejected[reason] = rejected.get(reason, 0) + 1
                continue
            selected.append(candidate)
        return sorted(
            selected,
            key=lambda item: (item.posted_at is not None, item.posted_at or ""),
            reverse=True,
        ), rejected

    def _candidate_rejection_reasons(
        self,
        candidate: JobCandidate,
        plan: Dict[str, Any],
    ) -> List[str]:
        reasons: List[str] = []
        title = normalize_space(candidate.title).casefold()
        aliases: List[str] = []
        for alias in plan.get("role_aliases", []):
            normalized_alias = normalize_space(str(alias)).casefold()
            if normalized_alias and normalized_alias not in aliases:
                aliases.append(normalized_alias)
        role_match = any(self._role_alias_matches(title, alias) for alias in aliases)
        if plan.get("role_policy", "strict") == "expanded_early_career":
            role_match = role_match or self._company_role_matches(candidate)
        if not role_match:
            reasons.append("role_outside_policy")

        location_policy = plan.get("location_policy", "strict")
        if location_policy == "strict" and not self._location_allowed(candidate, plan):
            reasons.append("location_outside_policy")
        elif location_policy != "strict" and self._location_hard_conflict(candidate, plan):
            reasons.append("location_outside_policy")

        work_modes = plan.get("work_modes", [])
        metadata_policy = plan.get("metadata_policy", "strict")
        if (
            work_modes
            and candidate.work_mode
            and candidate.work_mode not in work_modes
        ) or (
            work_modes and not candidate.work_mode and metadata_policy == "strict"
        ):
            reasons.append("work_mode_outside_policy")

        employment_types = plan.get("employment_types", [])
        if employment_types:
            candidate_employment = self._canonical_employment_type(
                candidate.employment_type
            )
            if (
                candidate_employment
                and candidate_employment not in employment_types
            ) or (
                not candidate_employment and metadata_policy == "strict"
            ):
                reasons.append("employment_type_outside_policy")

        excluded = [
            normalize_space(term).casefold()
            for term in plan.get("excluded_keywords", [])
            if term
        ]
        if any(
            excluded_term_matches(candidate.title, candidate.description, term)
            for term in excluded
        ):
            reasons.append("excluded_keyword")

        company = normalize_space(candidate.company).casefold()
        excluded_companies = [
            normalize_space(term).casefold()
            for term in plan.get("excluded_companies", [])
            if term
        ]
        if any(
            self._contains_phrase(company, term) for term in excluded_companies
        ):
            reasons.append("excluded_company")

        if self._seniority_outside_policy(candidate, plan):
            reasons.append("seniority_outside_policy")

        if plan.get("freshness_policy", "strict") == "strict":
            freshness = classify_freshness(candidate.posted_at, live=True)
            if freshness == "live_date_unverified" or not self._within_freshness_window(
                candidate.posted_at,
                int(plan.get("freshness_hours", 48)),
            ):
                reasons.append("freshness_outside_policy")

        if candidate.source_family not in plan.get("source_families", []):
            reasons.append("source_outside_policy")
        if not candidate.apply_url or not candidate.source_url:
            reasons.append("official_direct_link_missing")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _canonical_employment_type(value: Optional[str]) -> str:
        normalized = normalize_space(value or "").casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "fulltime": "full_time",
            "full_time": "full_time",
            "parttime": "part_time",
            "part_time": "part_time",
            "contractor": "contract",
            "contract": "contract",
            "temporary": "contract",
            "intern": "internship",
            "internship": "internship",
        }
        return aliases.get(normalized, "")

    @staticmethod
    def _role_alias_matches(title: str, alias: str) -> bool:
        if SearchService._contains_phrase(title, alias):
            return True
        alias_tokens = tokenize(alias)
        title_tokens = tokenize(title)
        if len(alias_tokens) < 2:
            return False
        positions: List[int] = []
        cursor = 0
        for token in alias_tokens:
            try:
                index = title_tokens.index(token, cursor)
            except ValueError:
                return False
            positions.append(index)
            cursor = index + 1
        bridge_tokens = set(title_tokens[positions[0] : positions[-1] + 1]) - set(
            alias_tokens
        )
        return bridge_tokens.issubset(
            {
                "application",
                "applications",
                "development",
                "platform",
                "services",
                "software",
                "systems",
                "web",
            }
        )

    @classmethod
    def _company_role_matches(cls, candidate: JobCandidate) -> bool:
        title = normalize_space(candidate.title).casefold()
        company = normalize_space(candidate.company).casefold()
        description = normalize_space(candidate.description).casefold()
        for company_name, aliases in COMPANY_SPECIFIC_ROLE_ALIASES.items():
            if not cls._contains_phrase(company, company_name):
                continue
            for alias in aliases:
                if not cls._contains_phrase(title, alias):
                    continue
                # A bare analyst title is meaningful at several employers, but it
                # must contain an implementation signal. A division or a job
                # function labelled "Engineering" alone is organizational
                # metadata, not proof that the role writes software.
                if alias == "analyst" and not any(
                    cls._contains_phrase(f"{title} {description}", term)
                    for term in TECHNICAL_IMPLEMENTATION_TERMS
                ):
                    continue
                return True
        return False

    @staticmethod
    def _contains_phrase(haystack: str, phrase: str) -> bool:
        normalized_phrase = normalize_space(phrase).casefold()
        if not normalized_phrase:
            return False
        pattern = re.escape(normalized_phrase).replace(r"\ ", r"\s+")
        return bool(re.search(rf"(?<!\w){pattern}(?!\w)", haystack.casefold()))

    @staticmethod
    def _location_allowed(candidate: JobCandidate, plan: Dict[str, Any]) -> bool:
        location = normalize_space(candidate.location).casefold()
        mode = (candidate.work_mode or "").casefold()

        def mentions(label: str) -> bool:
            canonical = canonical_location(label)
            aliases = LOCATION_ALIASES.get(canonical, (canonical.casefold(),))
            return any(
                SearchService._contains_phrase(location, alias) for alias in aliases
            )

        for excluded in plan.get("excluded_locations", []):
            if mentions(str(excluded)):
                return False

        for preferred in plan.get("locations", []):
            if SearchService._location_matches_preference(
                location,
                mode,
                str(preferred),
            ):
                return True
        return False

    @staticmethod
    def _location_hard_conflict(candidate: JobCandidate, plan: Dict[str, Any]) -> bool:
        """Reject explicit exclusions and obvious foreign-only roles, not unknowns."""

        location = normalize_space(candidate.location).casefold()
        if not location:
            return False
        for excluded in plan.get("excluded_locations", []):
            canonical = canonical_location(str(excluded))
            aliases = LOCATION_ALIASES.get(canonical, (canonical.casefold(),))
            if any(SearchService._contains_phrase(location, alias) for alias in aliases):
                return True

        preferences = [canonical_location(str(value)) for value in plan.get("locations", [])]
        india_scoped = any(
            value in {"India", "Remote India", "Hyderabad", "Bengaluru"}
            for value in preferences
        )
        if not india_scoped:
            return False
        if any(
            SearchService._contains_phrase(location, marker)
            for marker in INDIA_LOCATION_MARKERS
        ):
            return False
        if (candidate.work_mode or "").casefold() == "remote":
            if location in {"remote", "home based", "unspecified", "multiple locations"}:
                return False
            if any(
                SearchService._contains_phrase(location, marker)
                for marker in ("worldwide", "global", "apac", "asia")
            ):
                return False
        if location in {"unspecified", "multiple locations", "various locations"}:
            return False
        # Once a posting states a concrete non-India location, it is a real
        # geography conflict rather than missing metadata.
        return True

    @staticmethod
    def _location_matches_preference(
        location: str,
        work_mode: str,
        preferred: str,
    ) -> bool:
        normalized_location = normalize_space(location).casefold()

        def mentions(label: str) -> bool:
            canonical_label = canonical_location(label)
            aliases = LOCATION_ALIASES.get(
                canonical_label,
                (canonical_label.casefold(),),
            )
            return any(
                SearchService._contains_phrase(normalized_location, alias)
                for alias in aliases
            )

        canonical = canonical_location(preferred)
        if canonical == "Remote India":
            return work_mode.casefold() == "remote" and mentions("India")
        if canonical == "India":
            return mentions("India")
        return mentions(canonical)

    @staticmethod
    def _seniority_outside_policy(
        candidate: JobCandidate,
        plan: Dict[str, Any],
    ) -> bool:
        max_years = SearchService._maximum_seniority_years(
            str(plan.get("seniority_tolerance") or "")
        )
        title = candidate.title.casefold()
        senior_title = bool(
            re.search(
                r"\b(?:senior|sr\.?|staff|principal|lead|manager|director|architect|"
                r"vice president|executive director|pmts|lmts|smts)\b",
                title,
            )
        )
        if (
            SearchService._contains_phrase(candidate.company, "goldman sachs")
            and normalize_space(str(candidate.raw.get("corporateTitle") or "")).casefold()
            not in {"", "analyst"}
        ):
            return True
        early_career = plan.get("seniority_policy") == "early_career"
        if early_career and (
            senior_title
            or re.search(r"\b(?:sde|engineer|developer)\s*(?:iii|iv|v|3|4|5)\b", title)
        ):
            return True
        if max_years is None:
            return False
        required_years = SearchService._minimum_required_experience(
            candidate.description
        )
        effective_max_years = min(max_years, 3) if early_career else max_years
        if required_years is not None and required_years > effective_max_years:
            return True
        if max_years > 4:
            return False
        return senior_title

    @staticmethod
    def _maximum_seniority_years(tolerance: str) -> Optional[int]:
        normalized = normalize_space(tolerance).casefold()
        if not normalized:
            return None
        years = [
            int(value)
            for value in re.findall(r"\b(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", normalized)
            if int(value) < 50
        ]
        if years:
            return max(years)
        if re.search(r"\b(?:fresher|new[ -]grad(?:uate)?|entry[ -]level)\b", normalized):
            return 0
        return None

    @staticmethod
    def _minimum_required_experience(description: str) -> Optional[int]:
        normalized = normalize_space(description).casefold()
        if not normalized:
            return None

        values: List[int] = []
        occupied: List[Tuple[int, int]] = []
        experience_suffix = (
            r"\s*(?:of\s+)?(?:[a-z0-9+#./-]+\s+){0,8}"
            r"(?:experience|engineering|development|building|working)\b"
        )
        range_pattern = re.compile(
            rf"\b(\d{{1,2}})\s*(?:-|–|—|to)\s*(\d{{1,2}})"
            rf"\s*(?:years?|yrs?)\b{experience_suffix}"
        )
        for match in range_pattern.finditer(normalized):
            minimum = int(match.group(1))
            maximum = int(match.group(2))
            if minimum <= maximum < 50:
                values.append(minimum)
                occupied.append(match.span())

        patterns = (
            re.compile(
                r"\b(?:at\s+least|minimum(?:\s+of)?)\s+(\d{1,2})\s*\+?"
                r"\s*(?:years?|yrs?)\b"
            ),
            re.compile(r"\b(\d{1,2})\s*\+\s*(?:years?|yrs?)\b"),
            re.compile(
                rf"\b(\d{{1,2}})\s*(?:years?|yrs?)\b{experience_suffix}"
            ),
            re.compile(
                r"\b(?:minimum|required|relevant|professional)\s+experience"
                r"(?:\s+required)?\s*(?:is|of|:|-)\s*(\d{1,2})"
                r"\s*(?:years?|yrs?)\b"
            ),
        )
        for pattern in patterns:
            for match in pattern.finditer(normalized):
                if any(
                    match.start() < end and match.end() > start
                    for start, end in occupied
                ):
                    continue
                value = int(match.group(1))
                if value < 50:
                    values.append(value)
        return min(values) if values else None

    @staticmethod
    def _within_freshness_window(
        posted_at: Optional[str],
        freshness_hours: int,
    ) -> bool:
        if not posted_at:
            return False
        posted = parse_utc_datetime(posted_at)
        if posted is None:
            return False
        age_hours = (utcnow() - posted).total_seconds() / 3600
        return -0.1 <= age_hours <= freshness_hours

    @staticmethod
    def _canonical_key(candidate: JobCandidate) -> str:
        normalized = "|".join(
            [
                re.sub(r"\W+", "", candidate.company.casefold()),
                re.sub(r"\W+", "", candidate.title.casefold()),
                re.sub(r"\W+", "", candidate.location.casefold()),
            ]
        )
        return stable_hash(normalized)

    def _deduplicate(self, candidates: Iterable[JobCandidate]) -> List[JobCandidate]:
        result: Dict[str, JobCandidate] = {}
        for candidate in candidates:
            key = self._canonical_key(candidate)
            previous = result.get(key)
            if previous is None or (candidate.posted_at or "") > (previous.posted_at or ""):
                result[key] = candidate
        return list(result.values())

    def _persist_candidate(
        self,
        candidate: JobCandidate,
        profile_version: str,
        preference_version: str,
        plan: Dict[str, Any],
        raw_path: Path,
    ) -> Tuple[str, str]:
        if not candidate.apply_url:
            raise ValueError("Official apply URL is missing")
        candidate.apply_url = upgrade_official_url(candidate.apply_url)
        hosts = allowed_apply_hosts(
            candidate.connector_id,
            candidate.source_family,
            fixture_jobs_enabled=bool(self.settings.fixture_jobs_path),
        )
        validate_official_candidate_url(candidate.apply_url, hosts)
        if not candidate.source_url:
            raise ValueError("Official source URL is missing")
        candidate.source_url = upgrade_official_url(candidate.source_url)
        source_hosts = allowed_source_hosts(
            candidate.connector_id,
            candidate.source_family,
            fixture_jobs_enabled=bool(self.settings.fixture_jobs_path),
        )
        validate_official_candidate_url(candidate.source_url, source_hosts)
        freshness = classify_freshness(candidate.posted_at, live=True)
        if plan.get("freshness_policy", "strict") == "strict":
            if freshness == "live_date_unverified" or not self._within_freshness_window(
                candidate.posted_at,
                int(plan.get("freshness_hours", 48)),
            ):
                raise ValueError("Job is outside the active freshness contract")
        canonical_key = self._canonical_key(candidate)
        existing = self.database.fetch_one(
            "SELECT id FROM jobs WHERE connector_id = ? AND external_id = ?",
            (candidate.connector_id, candidate.external_id),
        )
        job_id = existing["id"] if existing else new_id()
        verification_id = new_id()
        job = {
            "id": job_id,
            "title": normalize_space(candidate.title),
            "company": normalize_space(candidate.company),
            "description": candidate.description,
            "location": normalize_space(candidate.location),
            "work_mode": candidate.work_mode,
            "posted_at": candidate.posted_at,
            "employment_type": candidate.employment_type,
            "salary": self._extract_salary(candidate),
        }
        match = self.matching.score(job, freshness, plan)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO jobs(
                    id, connector_id, external_id, canonical_key, title, company,
                    description, description_hash, location, work_mode,
                    employment_type, posted_at, posted_semantics, apply_url,
                    source_url, source_family, salary_json, raw_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(connector_id, external_id) DO UPDATE SET
                    canonical_key = excluded.canonical_key,
                    title = excluded.title,
                    company = excluded.company,
                    description = excluded.description,
                    description_hash = excluded.description_hash,
                    location = excluded.location,
                    work_mode = excluded.work_mode,
                    employment_type = excluded.employment_type,
                    posted_at = excluded.posted_at,
                    posted_semantics = excluded.posted_semantics,
                    apply_url = excluded.apply_url,
                    source_url = excluded.source_url,
                    source_family = excluded.source_family,
                    salary_json = excluded.salary_json,
                    raw_path = excluded.raw_path,
                    last_seen_at = CURRENT_TIMESTAMP
                """,
                (
                    job_id,
                    candidate.connector_id,
                    candidate.external_id,
                    canonical_key,
                    job["title"],
                    job["company"],
                    job["description"],
                    stable_hash(job["description"]),
                    job["location"],
                    job["work_mode"],
                    candidate.employment_type,
                    candidate.posted_at,
                    candidate.posted_semantics,
                    candidate.apply_url,
                    candidate.source_url,
                    candidate.source_family,
                    json_dumps(job["salary"]) if job["salary"] else None,
                    str(raw_path),
                ),
            )
            connection.execute(
                """
                INSERT INTO job_verifications(
                    id, job_id, live_state, freshness_class,
                    posting_evidence_json, http_status, apply_host,
                    verifier_version
                ) VALUES (?, ?, 'live', ?, ?, NULL, ?, '1.1')
                """,
                (
                    verification_id,
                    job_id,
                    freshness,
                    json_dumps(
                        {
                            "source_family": candidate.source_family,
                            "posted_at": candidate.posted_at,
                            "posted_semantics": candidate.posted_semantics,
                            "official_listing_present": True,
                            "official_board_response_success": True,
                            "apply_url_host_validated": True,
                            "apply_url_http_status_checked": False,
                        }
                    ),
                    urlparse(candidate.apply_url).hostname or "",
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO job_source_observations(
                    id, job_id, connector_id, external_id, source_family,
                    payload_hash, candidate_json, source_url, apply_url,
                    posted_at, parser_version, raw_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    job_id,
                    candidate.connector_id,
                    candidate.external_id,
                    candidate.source_family,
                    stable_hash(candidate.raw),
                    json_dumps(candidate.to_dict()),
                    candidate.source_url,
                    candidate.apply_url,
                    candidate.posted_at,
                    getattr(
                        self._connector_for_job({"connector_id": candidate.connector_id}),
                        "parser_version",
                        "1.0",
                    ),
                    str(raw_path),
                ),
            )
            connection.execute(
                """
                INSERT INTO match_results(
                    id, job_id, profile_version, preference_version, score,
                    tier, factors_json, reasons_json, risks_json, evidence_ids_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, profile_version, preference_version) DO UPDATE SET
                    score = excluded.score,
                    tier = excluded.tier,
                    factors_json = excluded.factors_json,
                    reasons_json = excluded.reasons_json,
                    risks_json = excluded.risks_json,
                    evidence_ids_json = excluded.evidence_ids_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    new_id(),
                    job_id,
                    profile_version,
                    preference_version,
                    match["score"],
                    match["tier"],
                    json_dumps(match["factors"]),
                    json_dumps(match["reasons"]),
                    json_dumps(match["risks"]),
                    json_dumps(match["evidence_ids"]),
                ),
            )
        return job_id, freshness

    @staticmethod
    def _extract_salary(candidate: JobCandidate) -> Optional[Dict[str, Any]]:
        """Keep source-provided compensation when present; absence stays unknown."""

        raw = candidate.raw if isinstance(candidate.raw, dict) else {}
        for key in ("salaryRange", "salary", "compensation"):
            value = raw.get(key)
            if isinstance(value, dict) and value:
                result = {
                    field: value.get(field)
                    for field in ("min", "max", "currency", "interval", "period")
                    if value.get(field) is not None
                }
                if result:
                    return result
            if isinstance(value, str) and normalize_space(value):
                return {"text": normalize_space(value)}
        for key in ("compensationTierSummary", "salaryDescription"):
            value = raw.get(key)
            if isinstance(value, str) and normalize_space(value):
                return {"text": normalize_space(value)}
        return None

    def run_status(self, run_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM search_runs WHERE id = ?",
            (run_id,),
        )
        if not row:
            raise KeyError("Search run not found")
        return {**row, "coverage": json_loads(row["coverage_json"], {})}

    def list_jobs(self, include_hidden: bool = False) -> List[Dict[str, Any]]:
        profile = self.profiles.active_profile()
        if not profile:
            return []
        preference_version = self.profiles.preference_version()
        result_plan = self._latest_result_plan()
        if result_plan is None:
            return []
        rows = self.database.fetch_all(
            """
            SELECT
                j.*,
                v.live_state,
                v.freshness_class,
                v.posting_evidence_json,
                v.checked_at AS verified_at,
                m.score,
                m.tier,
                m.factors_json,
                m.reasons_json,
                m.risks_json,
                m.evidence_ids_json,
                (
                    SELECT ae.event_type
                    FROM activity_events ae
                    WHERE ae.job_id = j.id
                    ORDER BY ae.created_at DESC
                    LIMIT 1
                ) AS latest_feedback
            FROM jobs j
            JOIN search_run_jobs srj ON srj.job_id = j.id AND srj.run_id = ?
            JOIN job_verifications v ON v.id = (
                SELECT id FROM job_verifications
                WHERE job_id = j.id
                ORDER BY checked_at DESC, rowid DESC
                LIMIT 1
            )
            JOIN match_results m ON m.job_id = j.id
                AND m.profile_version = ?
                AND m.preference_version = ?
            """,
            (result_plan["run_id"], profile["version"], preference_version),
        )
        jobs = [self._hydrate_job(row) for row in rows]
        plan = result_plan["plan"]
        jobs = [job for job in jobs if self._job_meets_active_contract(job, plan)]
        if not include_hidden:
            jobs = [job for job in jobs if job.get("latest_feedback") != "hide"]
        locations = plan.get("locations", [])
        if isinstance(locations, str):
            locations = [locations]

        def location_index(job: Dict[str, Any]) -> int:
            for index, location in enumerate(locations):
                if self._location_matches_preference(
                    job["location"],
                    job.get("work_mode") or "",
                    str(location),
                ):
                    return index
            return len(locations) + 1

        freshness_order = {
            "verified_24h": 0,
            "verified_48h": 1,
            "live_date_unverified": 2,
            "older_live": 3,
            "uncertain": 4,
            "closed": 5,
        }
        def posted_timestamp(job: Dict[str, Any]) -> float:
            posted = parse_utc_datetime(job.get("posted_at"))
            return posted.timestamp() if posted else 0.0

        # The queue needs only its compact, persisted match reasons. Full
        # requirement-to-evidence analysis belongs to the explicit detail
        # request below; recalculating it for every visible card makes a large
        # local queue unnecessarily slow.
        jobs.sort(
            key=lambda job: (
                -float(job["score"]),
                location_index(job),
                freshness_order.get(job["freshness_class"], 9),
                -posted_timestamp(job),
            )
        )
        return jobs

    def search_contract(self) -> Dict[str, Any]:
        result_plan = self._latest_result_plan()
        plan = result_plan["plan"] if result_plan else self.plans.active()["plan"]
        return {
            "target_roles": plan.get("target_roles", []),
            "locations": plan.get("locations", []),
            "work_modes": plan.get("work_modes", []),
            "employment_types": plan.get("employment_types", []),
            "excluded_keywords": plan.get("excluded_keywords", []),
            "excluded_locations": plan.get("excluded_locations", []),
            "freshness_hours": int(plan.get("freshness_hours", 48)),
            "location_policy": plan.get("location_policy", "strict"),
            "role_policy": plan.get("role_policy", "strict"),
            "freshness_policy": plan.get("freshness_policy", "strict"),
            "metadata_policy": plan.get("metadata_policy", "strict"),
            "seniority_policy": plan.get("seniority_policy", "strict"),
            "source_policy": plan.get("source_policy", "official_direct"),
            "temporary_override": plan.get("temporary_override"),
        }

    def _latest_result_plan(self) -> Optional[Dict[str, Any]]:
        row = self.database.fetch_one(
            """
            SELECT sr.id AS run_id, sp.plan_json
            FROM search_runs AS sr
            JOIN search_plans AS sp ON sp.id = sr.plan_id
            WHERE sr.status IN ('complete', 'partial')
            ORDER BY sr.started_at DESC, sr.rowid DESC
            LIMIT 1
            """
        )
        if not row:
            return None
        return {
            "run_id": row["run_id"],
            "plan": normalize_search_plan(json_loads(row["plan_json"], {})),
        }

    def latest_coverage(self) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM search_runs ORDER BY started_at DESC, rowid DESC LIMIT 1"
        )
        if not row:
            return {"status": "not_run", "coverage": {}}
        return {
            "run_id": row["id"],
            "status": row["status"],
            "coverage": json_loads(row["coverage_json"], {}),
            "finished_at": row["finished_at"],
        }

    def _job_meets_active_contract(
        self,
        job: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> bool:
        if job.get("live_state") != "live":
            return False
        freshness = classify_freshness(job.get("posted_at"), live=True)
        if plan.get("freshness_policy", "strict") == "strict":
            if freshness == "live_date_unverified" or not self._within_freshness_window(
                job.get("posted_at"),
                int(plan.get("freshness_hours", 48)),
            ):
                return False
        job["freshness_class"] = freshness
        candidate = JobCandidate(
            connector_id=job["connector_id"],
            external_id=job["external_id"],
            title=job["title"],
            company=job["company"],
            description=job["description"],
            location=job["location"],
            work_mode=job.get("work_mode"),
            employment_type=job.get("employment_type"),
            posted_at=job.get("posted_at"),
            posted_semantics=job.get("posted_semantics"),
            apply_url=job["apply_url"],
            source_url=job["source_url"],
            source_family=job["source_family"],
            raw={},
        )
        return not self._candidate_rejection_reasons(candidate, plan)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            """
            SELECT
                j.*, v.live_state, v.freshness_class,
                v.posting_evidence_json, v.checked_at AS verified_at,
                m.score, m.tier, m.factors_json, m.reasons_json,
                m.risks_json, m.evidence_ids_json
            FROM jobs j
            JOIN job_verifications v ON v.id = (
                SELECT id FROM job_verifications WHERE job_id = j.id
                ORDER BY checked_at DESC, rowid DESC LIMIT 1
            )
            JOIN match_results m ON m.job_id = j.id
            WHERE j.id = ?
            ORDER BY m.created_at DESC
            LIMIT 1
            """,
            (job_id,),
        )
        if not row:
            raise KeyError("Job not found")
        job = self._hydrate_job(row)
        job["why_this_job"] = self._why_this_job(job)
        return job

    def _why_this_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Explain a recommendation without turning JD demand into candidate proof."""

        evidence = self.profiles.approved_evidence()
        profile = self.profiles.active_profile() or {"profile": {}}
        sections: Dict[str, List[str]] = {
            "skills": [str(value) for value in profile["profile"].get("skills", [])],
            "experience": [],
            "projects": [],
            "achievements": [],
        }
        for claim in evidence:
            category = str(claim.get("category") or "")
            target = category if category in sections else "experience"
            sections[target].append(str(claim.get("text") or ""))
        quality = analyze_job_description(job.get("description", ""), job.get("title", ""))
        alignment = match_requirements(quality["requirements"], sections)

        def evidence_ids_for(item: Dict[str, Any]) -> List[str]:
            terms = [str(term).casefold() for term in item.get("matched_entities", [])]
            terms.extend(str(term).casefold() for term in item.get("matched_terms", [])[:4])
            return [
                claim["id"]
                for claim in evidence
                if any(term and term in str(claim.get("text") or "").casefold() for term in terms)
            ][:5]

        proven = []
        unknowns = []
        gaps = []
        for item in alignment["requirements"]:
            status = item["match_status"]
            entry = {
                "requirement": item["text"],
                "priority": item["priority"],
                "evidence_ids": evidence_ids_for(item),
            }
            if status == "direct":
                proven.append(entry)
            elif status in {"listed_only", "transferable"}:
                unknowns.append(
                    {
                        **entry,
                        "note": (
                            "Listed in the profile; verify demonstrated use before claiming it."
                            if status == "listed_only"
                            else "Related evidence exists, but this exact requirement is not proven."
                        ),
                    }
                )
            elif item["priority"] == "required":
                gaps.append({**entry, "note": "No approved evidence currently supports this requirement."})

        priority_codes = {
            "role_alignment",
            "preferred_company",
            "preferred_industry",
            "priority_skill",
            "location_fit",
            "freshness",
            "feedback_learning",
        }
        priority_alignment = [
            reason["text"]
            for reason in job.get("reasons", [])
            if reason.get("code") in priority_codes
        ]
        for risk in job.get("risks", []):
            unknowns.append({"requirement": risk, "priority": "review", "evidence_ids": [], "note": "Check the official listing before applying."})
        return {
            "summary": (
                f"{len(proven)} proven requirement match(es), {len(gaps)} genuine gap(s), "
                f"and {len(unknowns)} item(s) to verify."
            ),
            "proven": proven[:6],
            "priority_alignment": priority_alignment[:5],
            "unknowns": unknowns[:6],
            "gaps": gaps[:6],
            "requirement_quality": {
                "status": quality["status"],
                "confidence": quality["confidence"],
                "count": quality["requirement_count"],
            },
        }

    def verify(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        # Official-listing presence is established during the connector fetch. The
        # MVP revalidation gate also rejects records that have aged past 24 hours
        # since their last official observation.
        last_seen = parse_utc_datetime(job.get("last_seen_at"))
        if last_seen is None:
            raise ValueError("The official observation timestamp is invalid")
        age = utcnow() - last_seen
        live = age.total_seconds() <= 24 * 3600
        freshness = classify_freshness(job.get("posted_at"), live=live)
        self.database.execute(
            """
            INSERT INTO job_verifications(
                id, job_id, live_state, freshness_class, posting_evidence_json,
                http_status, apply_host, verifier_version, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '1.0', ?)
            """,
            (
                new_id(),
                job_id,
                "live" if live else "uncertain",
                freshness,
                json_dumps(
                    {
                        "revalidated_from_cached_official_observation": True,
                        "last_seen_at": job["last_seen_at"],
                    }
                ),
                200 if live else None,
                urlparse(job["apply_url"]).hostname or "",
                None if live else "Official source observation is older than 24 hours",
            ),
        )
        return self.get_job(job_id)

    async def revalidate(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        connector = self._connector_for_job(job)
        if connector is None:
            return self.verify(job_id)
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.request_timeout_seconds),
                follow_redirects=False,
            ) as client:
                current = await connector.fetch_job(
                    client,
                    job["external_id"],
                )
        except Exception as exc:
            error_message = str(exc).strip() or type(exc).__name__
            self.database.execute(
                """
                INSERT INTO job_verifications(
                    id, job_id, live_state, freshness_class,
                    posting_evidence_json, apply_host, verifier_version, error
                ) VALUES (?, ?, 'uncertain', 'uncertain', ?, ?, '1.0', ?)
                """,
                (
                    new_id(),
                    job_id,
                    json_dumps({"official_revalidation_attempted": True}),
                    urlparse(job["apply_url"]).hostname or "",
                    error_message,
                ),
            )
            return self.get_job(job_id)
        if current is None:
            self.database.execute(
                """
                INSERT INTO job_verifications(
                    id, job_id, live_state, freshness_class,
                    posting_evidence_json, http_status, apply_host,
                    verifier_version, error
                ) VALUES (?, ?, 'closed', 'closed', ?, 404, ?, '1.0', ?)
                """,
                (
                    new_id(),
                    job_id,
                    json_dumps(
                        {
                            "official_listing_present": False,
                            "official_direct_detail_checked": (
                                connector.family == "smartrecruiters"
                            ),
                        }
                    ),
                    urlparse(job["apply_url"]).hostname or "",
                    "The role is no longer present in the official source",
                ),
            )
            return self.get_job(job_id)

        current.apply_url = upgrade_official_url(current.apply_url)
        current.source_url = upgrade_official_url(current.source_url)
        validate_official_candidate_url(
            current.apply_url,
            allowed_apply_hosts(
                current.connector_id,
                current.source_family,
                fixture_jobs_enabled=bool(self.settings.fixture_jobs_path),
            ),
        )
        validate_official_candidate_url(
            current.source_url,
            allowed_source_hosts(
                current.connector_id,
                current.source_family,
                fixture_jobs_enabled=bool(self.settings.fixture_jobs_path),
            ),
        )
        previous_hash = job["description_hash"]
        new_hash = stable_hash(current.description)
        freshness = classify_freshness(current.posted_at, live=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET title = ?, company = ?, description = ?, description_hash = ?,
                    location = ?, work_mode = ?, employment_type = ?,
                    posted_at = ?, posted_semantics = ?, apply_url = ?,
                    source_url = ?, last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    current.title,
                    current.company,
                    current.description,
                    new_hash,
                    current.location,
                    current.work_mode,
                    current.employment_type,
                    current.posted_at,
                    current.posted_semantics,
                    current.apply_url,
                    current.source_url,
                    job_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO job_verifications(
                    id, job_id, live_state, freshness_class,
                    posting_evidence_json, http_status, apply_host,
                    verifier_version
                ) VALUES (?, ?, 'live', ?, ?, NULL, ?, '1.1')
                """,
                (
                    new_id(),
                    job_id,
                    freshness,
                    json_dumps(
                        {
                            "official_listing_present": True,
                            "posted_at": current.posted_at,
                            "posted_semantics": current.posted_semantics,
                            "description_changed": previous_hash != new_hash,
                            "official_board_response_success": True,
                            "official_direct_detail_checked": (
                                connector.family == "smartrecruiters"
                            ),
                            "apply_url_host_validated": True,
                            "apply_url_http_status_checked": False,
                        }
                    ),
                    urlparse(current.apply_url).hostname or "",
                ),
            )
        result = self.get_job(job_id)
        result["description_changed"] = previous_hash != new_hash
        return result

    def _connector_for_job(self, job: Dict[str, Any]) -> Optional[OfficialConnector]:
        if self.settings.fixture_jobs_path:
            return FixtureConnector(self.settings.fixture_jobs_path)
        source = next(
            (
                item
                for item in SOURCE_CATALOG
                if item["id"] == job["connector_id"]
            ),
            None,
        )
        if not source:
            return None
        args = (
            source["id"],
            source["name"],
            source["company"],
            source["config"],
        )
        if source["type"] == "greenhouse":
            return GreenhouseConnector(*args)
        if source["type"] == "lever":
            return LeverConnector(*args)
        if source["type"] == "ashby":
            return AshbyConnector(*args)
        if source["type"] == "smartrecruiters":
            return SmartRecruitersConnector(*args)
        if source["type"] == "salesforce":
            return SalesforceConnector(*args)
        if source["type"] == "goldman":
            return GoldmanSachsConnector(*args)
        return None

    def feedback(self, job_id: str, action: str, reason: Optional[str]) -> Dict[str, Any]:
        self.get_job(job_id)
        self.database.execute(
            """
            INSERT INTO activity_events(id, event_type, job_id, reason)
            VALUES (?, ?, ?, ?)
            """,
            (new_id(), action, job_id, reason),
        )
        return {"job_id": job_id, "action": action}

    @staticmethod
    def _hydrate_job(row: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(row)
        for field, default in (
            ("posting_evidence_json", {}),
            ("factors_json", {}),
            ("reasons_json", []),
            ("risks_json", []),
            ("evidence_ids_json", []),
            ("salary_json", None),
        ):
            result[field.removesuffix("_json")] = json_loads(result.get(field), default)
            result.pop(field, None)
        return result


def classify_freshness(posted_at: Optional[str], live: bool) -> str:
    if not live:
        return "uncertain"
    if not posted_at:
        return "live_date_unverified"
    posted = parse_utc_datetime(posted_at)
    if posted is None:
        return "live_date_unverified"
    age_hours = (utcnow() - posted).total_seconds() / 3600
    if age_hours < -0.1:
        return "live_date_unverified"
    if age_hours <= 24:
        return "verified_24h"
    if age_hours <= 48:
        return "verified_48h"
    return "older_live"
