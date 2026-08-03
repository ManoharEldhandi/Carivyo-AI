#!/usr/bin/env python3
"""Validate a Carivyo resume-run workspace without model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from pypdf import PdfReader


REQUIRED_FILES = (
    "inputs/job-description.txt",
    "inputs/run-spec.json",
    "reviews/requirement-evidence-map.json",
    "reviews/change-plan.json",
    "reviews/hiring-review.json",
    "reports/validation.json",
    "reports/ats-analysis.json",
    "result.json",
)
CRITICAL_VALIDATION_FLAGS = (
    "export_ok",
    "page_count_ok",
    "text_extraction_ok",
    "parser_consensus_ok",
    "links_ok",
    "identity_ok",
    "section_order_ok",
    "section_completeness_ok",
    "visual_ok",
    "evidence_ok",
)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: invalid JSON ({exc})") from exc


def confined(root: Path, value: str, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label}: path escapes run workspace") from exc
    return path


def validate(run_directory: Path) -> list[str]:
    errors: list[str] = []
    root = run_directory.expanduser().resolve()
    if not root.is_dir():
        return [f"run directory does not exist: {root}"]

    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            errors.append(f"missing required artifact: {relative}")
    if errors:
        return errors

    try:
        spec = load_json(root / "inputs/run-spec.json")
        result = load_json(root / "result.json")
        report = load_json(root / "reports/validation.json")
        ats_report = load_json(root / "reports/ats-analysis.json")
    except ValueError as exc:
        return [str(exc)]

    context = spec.get("context_policy", {})
    if context.get("scope") != "run_only":
        errors.append("context_policy.scope must be run_only")
    if context.get("ambient_context_allowed") is not False:
        errors.append("ambient candidate context must be disabled")
    if context.get("external_files_allowed") is not False:
        errors.append("external candidate files must be disabled")

    try:
        if confined(root, spec.get("output_directory", ""), "output_directory") != root:
            errors.append("output_directory must equal the run workspace")
        job = spec.get("job_snapshot", {})
        confined(root, job.get("description_path", ""), "job description")
        for index, base in enumerate(spec.get("base_resumes", [])):
            confined(root, base.get("source_path", ""), f"base[{index}].source_path")
            confined(root, base.get("text_path", ""), f"base[{index}].text_path")
        for kind, value in result.get("artifacts", {}).items():
            values = value if isinstance(value, list) else [value]
            if not values:
                errors.append(f"artifact.{kind} is empty")
            for index, item in enumerate(values):
                label = f"artifact.{kind}[{index}]" if isinstance(value, list) else f"artifact.{kind}"
                path = confined(root, item, label)
                if not path.is_file():
                    errors.append(f"{label} does not exist")
    except (TypeError, ValueError) as exc:
        errors.append(str(exc))

    evidence = spec.get("evidence_claims", [])
    approved_ids = {
        claim.get("id")
        for claim in evidence
        if claim.get("approval") == "approved" and claim.get("id")
    }
    if len(approved_ids) != len(evidence):
        errors.append("every evidence claim must be approved and uniquely identified")

    referenced_ids: set[str] = set()
    for group in result.get("coverage", {}).values():
        for item in group:
            referenced_ids.update(item.get("evidence_ids", []))
    for change in result.get("changes", []):
        referenced_ids.update(change.get("evidence_ids", []))
    unknown = sorted(referenced_ids - approved_ids)
    if unknown:
        errors.append(f"unapproved evidence references: {', '.join(unknown)}")

    validation = result.get("validation", {})
    if validation != report:
        errors.append("result validation does not match reports/validation.json")
    for flag in CRITICAL_VALIDATION_FLAGS:
        if flag == "section_completeness_ok" and spec.get("skill_version") != "5.0.0":
            continue
        if validation.get(flag) is not True:
            errors.append(f"critical validation gate failed: {flag}")
    if validation.get("change_budget_applicable"):
        change_percent = validation.get("change_percent")
        if not isinstance(change_percent, (int, float)) or change_percent > 25:
            errors.append("tailor-mode change budget exceeds 25 percent")

    ats_result = result.get("ats_analysis", {})
    if ats_result != ats_report:
        errors.append("result ATS analysis does not match reports/ats-analysis.json")
    checks = ats_report.get("checks", [])
    if len(checks) != 27 or len({check.get("id") for check in checks}) != 27:
        errors.append("ATS analysis must contain exactly 27 uniquely identified checks")
    score = ats_report.get("overall_score")
    if not isinstance(score, (int, float)) or not 0 <= score <= 100:
        errors.append("ATS analysis score must be between 0 and 100")
    if "No universal ATS score exists" not in ats_report.get("disclaimer", ""):
        errors.append("ATS analysis must carry the diagnostic-score disclaimer")
    assessment = ats_report.get("assessment", {})
    if assessment.get("legacy_score_deprecated") is not True:
        errors.append("ATS v2 must deprecate the legacy aggregate score")
    for perspective in ("compatibility", "evidence_alignment", "content_quality"):
        if not isinstance(assessment.get(perspective), dict):
            errors.append(f"ATS v2 perspective is missing: {perspective}")
    if ats_report.get("jd_quality", {}).get("status") != "complete":
        errors.append("job-specific ATS analysis requires a complete official JD")

    render_pages = result.get("artifacts", {}).get("render_pages", [])
    page_count = validation.get("page_count")
    if not isinstance(render_pages, list) or len(render_pages) != page_count:
        errors.append("every PDF page must have a bound visual render")
    visual_details = validation.get("visual_details", {})
    if visual_details.get("validated_page_count") != page_count:
        errors.append("every PDF page must pass visual validation")

    provenance = result.get("provenance", {})
    profile = spec.get("profile_snapshot", {})
    profile_hash = stable_hash(
        profile.get("version"),
        profile.get("profile"),
        profile.get("capsule"),
    )
    if profile.get("hash") != profile_hash:
        errors.append("profile snapshot hash does not match")
    instructions_hash = spec.get("custom_instructions_hash")
    variant = result.get("variant", 1)
    if isinstance(variant, int) and variant > 1:
        revision_path = root / f"inputs/revision-{variant}.json"
        if not revision_path.is_file():
            errors.append(f"missing revision contract: inputs/revision-{variant}.json")
        else:
            try:
                revision = load_json(revision_path)
                expected_revision_hash = stable_hash(
                    revision.get("combined_instructions", "")
                )
                if revision.get("combined_instructions_hash") != expected_revision_hash:
                    errors.append("revision instruction hash does not match")
                if (
                    revision.get("original_instructions_hash")
                    != spec.get("custom_instructions_hash")
                ):
                    errors.append("revision does not reference the original instructions")
                instructions_hash = revision.get("combined_instructions_hash")
            except ValueError as exc:
                errors.append(str(exc))
    expected = {
        "job_snapshot_hash": spec.get("job_snapshot", {}).get("snapshot_hash"),
        "profile_snapshot_hash": spec.get("profile_snapshot", {}).get("hash"),
        "evidence_hash": spec.get("evidence_hash"),
        "base_resume_hash": (spec.get("base_resumes") or [{}])[0].get("hash"),
        "custom_instructions_hash": instructions_hash,
        "template_hash": spec.get("template", {}).get("hash"),
        "skill_version": spec.get("skill_version"),
    }
    for key, value in expected.items():
        if not value or provenance.get(key) != value:
            errors.append(f"provenance mismatch: {key}")

    artifacts = result.get("artifacts", {})
    bindings = ats_report.get("bindings", {})
    try:
        pdf_path = confined(root, artifacts.get("pdf", ""), "artifact.pdf")
        source_path = confined(
            root, artifacts.get("editable_source", ""), "artifact.editable_source"
        )
        ats_path = confined(root, artifacts.get("ats_report", ""), "artifact.ats_report")
        extracted = "\n".join(
            page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages
        )
        actual_hashes = {
            "pdf_hash": hash_file(pdf_path),
            "editable_source_hash": hash_file(source_path),
            "extracted_text_hash": stable_hash(extracted),
            "ats_report_file_hash": hash_file(ats_path),
        }
        for key, value in actual_hashes.items():
            if provenance.get(key) != value:
                errors.append(f"artifact provenance mismatch: {key}")
        for key in ("pdf_hash", "editable_source_hash", "extracted_text_hash"):
            if bindings.get(key) != provenance.get(key):
                errors.append(f"ATS binding mismatch: {key}")
        canonical_ats = json.loads(json.dumps(ats_report))
        canonical_ats.get("bindings", {}).pop("analysis_hash", None)
        analysis_hash = stable_hash(canonical_ats)
        if (
            bindings.get("analysis_hash") != analysis_hash
            or provenance.get("ats_analysis_hash") != analysis_hash
        ):
            errors.append("ATS analysis hash does not match")
    except (OSError, TypeError, ValueError) as exc:
        errors.append(str(exc))

    status = result.get("status")
    approval = result.get("approval", {})
    if status not in {"needs_user_review", "ready_to_apply", "blocked", "failed"}:
        errors.append("invalid result status")
    if status == "ready_to_apply" and approval.get("user_approved") is not True:
        errors.append("ready_to_apply requires explicit user approval")
    if status == "needs_user_review" and approval.get("user_approved") is not False:
        errors.append("generated resume must await user approval")
    return errors


def stable_hash(*parts: Any) -> str:
    import hashlib

    digest = hashlib.sha256()
    for part in parts:
        digest.update(
            json.dumps(
                part,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\x00")
    return digest.hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    args = parser.parse_args()
    errors = validate(args.run_directory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Resume run contract: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
