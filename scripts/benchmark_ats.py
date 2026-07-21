#!/usr/bin/env python3
"""Run the legally safe, anonymized Carivyo ATS benchmark corpus."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.ats import ATSAnalyzer  # noqa: E402


def run_benchmark(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    analyzer = ATSAnalyzer()
    true_positive = false_positive = false_negative = true_negative = 0
    cases: List[Dict[str, Any]] = []
    repeatable = 0
    for fixture in payload["cases"]:
        first = analyzer.analyze(
            fixture["resume_text"], fixture.get("metadata"), fixture.get("job_description", "")
        )
        second = analyzer.analyze(
            fixture["resume_text"], fixture.get("metadata"), fixture.get("job_description", "")
        )
        repeatable += int(first == second)
        checks = {check["id"]: check for check in first["checks"]}
        for check_id, expected_issue in fixture.get("labels", {}).items():
            observed_issue = checks[check_id]["status"] in {"warning", "fail"}
            if expected_issue and observed_issue:
                true_positive += 1
            elif expected_issue:
                false_negative += 1
            elif observed_issue:
                false_positive += 1
            else:
                true_negative += 1
        cases.append(
            {
                "id": fixture["id"],
                "overall_score": first["overall_score"],
                "readiness": first["report_summary"]["readiness"],
                "labeled_checks": len(fixture.get("labels", {})),
            }
        )

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    return {
        "benchmark_version": payload["benchmark_version"],
        "analyzer_version": analyzer.version,
        "case_count": len(cases),
        "repeatability": round(repeatable / len(cases), 4) if cases else 0.0,
        "labeled_issue_precision": round(precision, 4),
        "labeled_issue_recall": round(recall, 4),
        "confusion": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "false_negative": false_negative,
            "true_negative": true_negative,
        },
        "vendor_agreement": None,
        "vendor_agreement_reason": (
            "No proprietary vendor labels are committed. Authorized comparisons remain "
            "development-only until an anonymized licensed corpus exists."
        ),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=ROOT / "backend" / "tests" / "fixtures" / "ats_benchmark.json",
    )
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.fixtures), indent=2))


if __name__ == "__main__":
    main()
