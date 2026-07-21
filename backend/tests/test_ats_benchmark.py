import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.benchmark_ats import run_benchmark


def test_anonymized_ats_benchmark_is_repeatable_and_labeled():
    result = run_benchmark(ROOT / "backend/tests/fixtures/ats_benchmark.json")

    assert result["case_count"] == 2
    assert result["repeatability"] == 1.0
    assert result["labeled_issue_precision"] >= 0.9
    assert result["labeled_issue_recall"] >= 0.9
    assert result["vendor_agreement"] is None
