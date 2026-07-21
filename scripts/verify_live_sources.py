#!/usr/bin/env python3
"""Run a bounded, read-only contract check against representative official ATS APIs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.connectors import (  # noqa: E402
    AshbyConnector,
    GreenhouseConnector,
    LeverConnector,
    SmartRecruitersConnector,
)
from app.connectors.base import ConnectorFetchResult, OfficialConnector  # noqa: E402
from app.security import validate_outbound_url  # noqa: E402
from app.services.search import SOURCE_CATALOG, allowed_apply_hosts  # noqa: E402


DEFAULT_SOURCE_IDS = (
    "greenhouse-phonepe",
    "lever-binance",
    "ashby-openai",
    "smartrecruiters-bosch-india-software",
)


def build_connector(source: dict[str, Any], smartrecruiters_detail_limit: int) -> OfficialConnector:
    config = dict(source["config"])
    if source["type"] == "smartrecruiters":
        config["detail_limit"] = smartrecruiters_detail_limit
    args = (source["id"], source["name"], source["company"], config)
    connector_types = {
        "greenhouse": GreenhouseConnector,
        "lever": LeverConnector,
        "ashby": AshbyConnector,
        "smartrecruiters": SmartRecruitersConnector,
    }
    return connector_types[source["type"]](*args)


async def verify_source(
    source: dict[str, Any],
    timeout_seconds: float,
    smartrecruiters_detail_limit: int,
) -> dict[str, Any]:
    connector = build_connector(source, smartrecruiters_detail_limit)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        ) as client:
            result = ConnectorFetchResult.coerce(await connector.fetch(client))
    except Exception as exc:  # Live diagnostics must preserve the exact source failure.
        return {
            "source_id": source["id"],
            "family": source["type"],
            "status": "failed",
            "error": f"{exc.__class__.__name__}: {exc}",
        }

    invalid: list[dict[str, str]] = []
    posted_with_evidence = 0
    for candidate in result.candidates:
        try:
            validate_outbound_url(
                candidate.apply_url,
                allowed_hosts=allowed_apply_hosts(
                    candidate.connector_id,
                    candidate.source_family,
                )
                or None,
                resolve_dns=False,
            )
            if not candidate.title.strip() or not candidate.company.strip():
                raise ValueError("title or company is empty")
            if candidate.source_family != source["type"]:
                raise ValueError("source family changed during normalization")
        except Exception as exc:
            invalid.append(
                {
                    "external_id": candidate.external_id,
                    "error": str(exc),
                }
            )
        if candidate.posted_at and candidate.posted_semantics:
            posted_with_evidence += 1

    return {
        "source_id": source["id"],
        "family": source["type"],
        "status": "passed" if result.candidates and not invalid else "failed",
        "candidate_count": len(result.candidates),
        "complete": result.complete,
        "completeness": result.completeness,
        "posted_with_evidence": posted_with_evidence,
        "invalid_candidates": invalid,
        "sample": [
            {
                "external_id": item.external_id,
                "title": item.title,
                "location": item.location,
                "posted_at": item.posted_at,
                "posted_semantics": item.posted_semantics,
                "apply_url": item.apply_url,
            }
            for item in result.candidates[:2]
        ],
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    by_id = {source["id"]: source for source in SOURCE_CATALOG}
    missing = [source_id for source_id in args.source if source_id not in by_id]
    if missing:
        raise SystemExit(f"Unknown source id(s): {', '.join(missing)}")
    results = await asyncio.gather(
        *(
            verify_source(
                by_id[source_id],
                args.timeout,
                args.smartrecruiters_detail_limit,
            )
            for source_id in args.source
        )
    )
    return {
        "mode": "read_only_live_contract_check",
        "source_count": len(results),
        "passed": sum(item["status"] == "passed" for item in results),
        "failed": sum(item["status"] == "failed" for item in results),
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--smartrecruiters-detail-limit", type=int, default=5)
    args = parser.parse_args()
    args.source = args.source or list(DEFAULT_SOURCE_IDS)
    report = asyncio.run(run(args))
    print(json.dumps(report, indent=2))
    raise SystemExit(1 if report["failed"] else 0)


if __name__ == "__main__":
    main()
