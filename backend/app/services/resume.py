from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from PIL import Image, ImageChops, ImageStat, UnidentifiedImageError

from app.artifacts import ArtifactVault
from app.db import Database
from app.services.ats import ATSAnalyzer, CRITICAL_CHECK_IDS
from app.services.extraction import build_evidence, extract_in_subprocess
from app.services.hiring_agent import LocalHiringAgent
from app.services.pdf_validation import validate_pdf_parsers
from app.services.requirements import (
    analyze_job_description,
    extract_requirements,
    match_requirements,
)
from app.services.profile import ProfileService
from app.services.search import SearchService
from app.utils import (
    json_dumps,
    json_loads,
    new_id,
    stable_hash,
    tokenize,
)


class ResumeRunBlocked(ValueError):
    pass


class ResumeService:
    SKILL_VERSION = "5.0.0"
    SUPPORTED_SKILL_VERSIONS = {"3.1.0", "4.0.0", "5.0.0"}
    TEMPLATE_ID = "carivyo-ats-a4-tex-v2"
    TEMPLATE_HASH = stable_hash(
        TEMPLATE_ID,
        "Helvetica",
        "single-column",
        "a4",
        "1F3864",
        "2F5496",
        "1A5DAD",
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
    RESUME_CATEGORIES = {
        "summary",
        "experience",
        "projects",
        "skills",
        "achievements",
        "education",
        "certifications",
        "volunteer",
        "leadership",
        "publications",
        "languages",
    }
    DEFAULT_SECTION_ORDER = [
        "summary",
        "experience",
        "projects",
        "skills",
        "achievements",
        "education",
        "certifications",
        "volunteer",
        "leadership",
        "publications",
        "languages",
    ]
    SECTION_LABELS = {
        "summary": "Summary",
        "experience": "Experience",
        "projects": "Projects",
        "skills": "Skills",
        "achievements": "Achievements",
        "education": "Education",
        "certifications": "Certifications",
        "volunteer": "Volunteer Experience",
        "leadership": "Leadership",
        "publications": "Publications",
        "languages": "Languages",
    }

    def __init__(
        self,
        database: Database,
        vault: ArtifactVault,
        profiles: ProfileService,
        search: SearchService,
        hiring_agent: Optional[LocalHiringAgent] = None,
    ):
        self.database = database
        self.vault = vault
        self.profiles = profiles
        self.search = search
        self.ats = ATSAnalyzer()
        self.hiring_agent = hiring_agent

    async def create(self, job_id: str, instructions: str) -> Dict[str, Any]:
        job = await self.search.revalidate(job_id)
        if job["live_state"] != "live":
            raise ResumeRunBlocked(
                "Resume design is blocked because the official job route is not currently live"
            )
        jd_quality = analyze_job_description(job["description"], job["title"])
        if jd_quality["status"] != "complete":
            raise ResumeRunBlocked(
                "The official source has not supplied complete responsibilities and qualifications. "
                "Carivyo will not claim job-specific ATS alignment from partial discovery metadata."
            )
        profile = self.profiles.active_profile()
        if not profile:
            raise ResumeRunBlocked("Complete onboarding before designing a resume")
        evidence = self.profiles.approved_evidence(profile=profile)
        if not evidence:
            raise ResumeRunBlocked("No approved candidate evidence is available")
        bases = self.profiles.active_resume_bases(profile=profile)
        if not bases:
            raise ResumeRunBlocked("No imported base resume is available")
        base, base_selection = self._select_base(job, bases, evidence)
        mode = self._mode_for_base(base, evidence)
        normalized_text, normalized_evidence = self._normalized_base_evidence(
            base,
            evidence,
        )
        scoped_evidence = self._job_scoped_evidence(
            job,
            normalized_evidence,
            base,
            mode,
        )

        run_id = new_id()
        workspace = self.vault.directory("resume-runs", run_id)
        for directory in ("inputs", "reviews", "variants", "renders", "reports"):
            self.vault.directory("resume-runs", run_id, directory)
        jd_path = self.vault.write_text(
            f"resume-runs/{run_id}/inputs/job-description.txt",
            job["description"],
        )
        base_suffix = Path(base["source_path"]).suffix or ".txt"
        reference_path = self.vault.write_bytes(
            f"resume-runs/{run_id}/inputs/reference-base{base_suffix}",
            Path(base["source_path"]).read_bytes(),
        )
        reference_text_path = self.vault.write_text(
            f"resume-runs/{run_id}/inputs/reference-base-extracted.txt",
            normalized_text,
        )
        interpretation = self.interpret_instructions(instructions, base, mode)
        evidence_snapshot = [
            {
                "id": claim["id"],
                "artifact_id": claim["artifact_id"],
                "category": claim["category"],
                "text": claim["text"],
                "source_location": claim["source_location"],
                "source": f"{claim['artifact_id']}:{claim['source_location']}",
                "approval": "approved",
                "confidence": claim["confidence"],
            }
            for claim in scoped_evidence
        ]
        profile_snapshot = {
            "version": profile["version"],
            "profile": profile["profile"],
            "capsule": profile["capsule"],
        }
        profile_snapshot["hash"] = stable_hash(
            profile_snapshot["version"],
            profile_snapshot["profile"],
            profile_snapshot["capsule"],
        )
        template = {"id": self.TEMPLATE_ID, "hash": self.TEMPLATE_HASH}
        run_spec = {
            "run_id": run_id,
            "job_snapshot": {
                "job_id": job_id,
                "company": job["company"],
                "title": job["title"],
                "description_path": str(jd_path),
                "source_url": job["source_url"],
                "snapshot_hash": stable_hash(job["description"]),
                "quality": jd_quality,
            },
            "profile_version": profile["version"],
            "profile_snapshot": profile_snapshot,
            "context_policy": {
                "scope": "run_only",
                "ambient_context_allowed": False,
                "external_files_allowed": False,
            },
            "evidence_claims": evidence_snapshot,
            "evidence_hash": stable_hash(evidence_snapshot),
            "base_resumes": [
                {
                    "id": base["id"],
                    "artifact_id": base["artifact_id"],
                    "track": base["track"],
                    "source_path": str(reference_path),
                    "text_path": str(reference_text_path),
                    "original_name": base["original_name"],
                    "original_kind": base["original_kind"],
                    "original_size_bytes": base["original_size_bytes"],
                    "hash": base["content_hash"],
                    "text_hash": self.vault.hash_file(reference_text_path),
                    "editable_kind": base["editable_kind"],
                    "usable_for_tailoring": bool(base["usable_for_tailoring"]),
                }
            ],
            "custom_instructions": instructions,
            "custom_instructions_hash": stable_hash(instructions),
            "output_directory": str(workspace),
            "network_policy": "none",
            "skill_version": self.SKILL_VERSION,
            "extraction_version": "poppler-layout-logical-claims-v2",
            "mode": mode,
            "base_selection": base_selection,
            "template": template,
        }
        self.vault.write_text(
            f"resume-runs/{run_id}/inputs/run-spec.json",
            json.dumps(run_spec, ensure_ascii=False, indent=2),
        )
        self.database.execute(
            """
            INSERT INTO resume_runs(
                id, job_id, status, stage, mode, base_resume_id,
                custom_instructions, interpretation_json, workspace_path,
                jd_hash, profile_version
            ) VALUES (?, ?, 'running', 'mapping', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                job_id,
                mode,
                base["id"],
                instructions,
                json_dumps(interpretation),
                str(workspace),
                stable_hash(job["description"]),
                profile["version"],
            ),
        )
        try:
            result = await asyncio.to_thread(
                self._generate,
                run_id=run_id,
                job=job,
                profile=profile,
                evidence=scoped_evidence,
                base=base,
                interpretation=interpretation,
                variant_number=1,
                mode=mode,
                base_selection=base_selection,
            )
        except Exception as exc:
            self.database.execute(
                """
                UPDATE resume_runs
                SET status = 'failed', stage = 'failed', error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(exc), run_id),
            )
            raise
        return result

    def get(self, run_id: str) -> Dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM resume_runs WHERE id = ?",
            (run_id,),
        )
        if not row:
            raise KeyError("Resume run not found")
        result = {}
        if row["result_path"] and Path(row["result_path"]).exists():
            result = json.loads(Path(row["result_path"]).read_text(encoding="utf-8"))
        return {
            **row,
            "interpretation": json_loads(row["interpretation_json"], []),
            "result": result,
        }

    def latest_for_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        row = self.database.fetch_one(
            """
            SELECT id FROM resume_runs
            WHERE job_id = ? AND result_path IS NOT NULL
              AND status IN ('needs_user_review', 'ready_to_apply')
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (job_id,),
        )
        return self.get(row["id"]) if row else None

    def revise(self, run_id: str, message: str) -> Dict[str, Any]:
        run = self.get(run_id)
        if run["status"] not in {"needs_user_review", "ready_to_apply"}:
            raise ResumeRunBlocked("Only a completed resume can receive a focused revision")
        self._ensure_run_mutable(run_id)
        existing_result = run["result"]
        current_variant = int(existing_result.get("variant") or 1)
        next_variant = current_variant + 1
        if next_variant > 4:
            raise ResumeRunBlocked(
                "This run reached the four-version safety budget; start a new run for broader changes"
            )
        run_spec, job, profile, evidence, base = self._load_frozen_inputs(run)
        if run_spec.get("template", {}).get("id") != self.TEMPLATE_ID:
            raise ResumeRunBlocked("Start a new run to use the editable TeX workflow")
        combined = (
            run_spec.get("custom_instructions", "")
            + "\nFocused revision: "
            + message
        ).strip()
        base_mode = (
            existing_result.get("base_mode")
            or run_spec.get("mode")
            or "build"
        )
        if base_mode not in {"tailor", "build"}:
            base_mode = "build"
        interpretation = self.interpret_instructions(combined, base, base_mode)
        revision_spec = {
            "variant": next_variant,
            "kind": "instruction",
            "message": message,
            "combined_instructions": combined,
            "combined_instructions_hash": stable_hash(combined),
            "original_instructions_hash": run_spec["custom_instructions_hash"],
            "previous_result_hash": stable_hash(existing_result),
        }
        workspace = Path(run["workspace_path"]).resolve()
        self._write_json(
            workspace / "inputs" / f"revision-{next_variant}.json", revision_spec
        )
        self.database.execute(
            """
            UPDATE resume_runs
            SET status = 'running', stage = 'revision',
                custom_instructions = ?, interpretation_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (combined, json_dumps(interpretation), run_id),
        )
        try:
            return self._generate(
                run_id,
                job,
                profile,
                evidence,
                base,
                interpretation,
                variant_number=next_variant,
                previous_result=existing_result,
                mode=base_mode,
                base_selection=existing_result.get("base_selection"),
                instructions_hash=revision_spec["combined_instructions_hash"],
            )
        except Exception as exc:
            self._discard_variant(workspace, next_variant)
            (workspace / "inputs" / f"revision-{next_variant}.json").unlink(
                missing_ok=True
            )
            self.database.execute(
                """
                UPDATE resume_runs
                SET status = ?, stage = ?, custom_instructions = ?,
                    interpretation_json = ?, error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    run["status"],
                    run["stage"],
                    run["custom_instructions"],
                    run["interpretation_json"],
                    run_id,
                ),
            )
            raise

    def source(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        result = run.get("result", {})
        artifacts = result.get("artifacts", {})
        source_value = artifacts.get("editable_source")
        if not source_value:
            raise KeyError("Editable resume source not found")
        workspace = Path(run["workspace_path"]).resolve()
        source_path = self._confined_run_path(
            workspace, Path(source_value), "editable resume source"
        )
        source_text = source_path.read_text(encoding="utf-8")
        return {
            "run_id": run_id,
            "variant": result.get("variant"),
            "language": "latex" if source_path.suffix == ".tex" else "markdown",
            "editable": (
                source_path.suffix == ".tex"
                and result.get("editable_source_exact") is True
                and shutil.which("tectonic") is not None
                and run["status"] in {"needs_user_review", "ready_to_apply"}
            ),
            "source": source_text,
            "source_hash": self.vault.hash_file(source_path),
            "filename": source_path.name,
        }

    def update_source(self, run_id: str, source: str, instruction: str) -> Dict[str, Any]:
        run = self.get(run_id)
        if run["status"] not in {"needs_user_review", "ready_to_apply"}:
            raise ResumeRunBlocked("Only a completed resume can be edited")
        self._ensure_run_mutable(run_id)
        current_result = run.get("result", {})
        self._validate_tex_source(source)
        workspace = Path(run["workspace_path"]).resolve()
        current_source_value = current_result.get("artifacts", {}).get(
            "editable_source"
        )
        if not current_source_value:
            raise ResumeRunBlocked("The current TeX source is unavailable")
        current_source_path = self._confined_run_path(
            workspace,
            Path(current_source_value),
            "current editable resume source",
        )
        current_source = current_source_path.read_text(encoding="utf-8")
        self._validate_tex_revision(current_source, source)
        if current_result.get("editable_source_exact") is not True:
            raise ResumeRunBlocked(
                "Install Tectonic and start a new resume before editing TeX"
            )
        current_variant = int(current_result.get("variant") or 1)
        next_variant = current_variant + 1
        if next_variant > 4:
            raise ResumeRunBlocked(
                "This run reached the four-version safety budget; start a new run for broader changes"
            )
        run_spec, job, profile, evidence, base = self._load_frozen_inputs(run)
        if run_spec.get("template", {}).get("id") != self.TEMPLATE_ID:
            raise ResumeRunBlocked("Start a new run to use the editable TeX workflow")
        combined = (
            str(run.get("custom_instructions") or "")
            + "\nManual TeX edit: "
            + instruction.strip()
        ).strip()
        interpretation = self.interpret_instructions(
            combined,
            base,
            current_result.get("base_mode") or run_spec.get("mode") or "build",
        )
        revision_spec = {
            "variant": next_variant,
            "kind": "tex_edit",
            "message": instruction.strip() or "Manual TeX edit",
            "combined_instructions": combined,
            "combined_instructions_hash": stable_hash(combined),
            "original_instructions_hash": run_spec["custom_instructions_hash"],
            "previous_result_hash": stable_hash(current_result),
            "source_hash": stable_hash(source),
        }
        self._write_json(
            workspace / "inputs" / f"revision-{next_variant}.json",
            revision_spec,
        )
        self.database.execute(
            """
            UPDATE resume_runs
            SET status = 'running', stage = 'tex_edit', custom_instructions = ?,
                interpretation_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (combined, json_dumps(interpretation), run_id),
        )
        try:
            return self._generate(
                run_id,
                job,
                profile,
                evidence,
                base,
                interpretation,
                variant_number=next_variant,
                previous_result=current_result,
                mode=current_result.get("base_mode") or "build",
                base_selection=current_result.get("base_selection"),
                instructions_hash=revision_spec["combined_instructions_hash"],
                source_override=source,
            )
        except Exception as exc:
            self._discard_variant(workspace, next_variant)
            (workspace / "inputs" / f"revision-{next_variant}.json").unlink(
                missing_ok=True
            )
            self.database.execute(
                """
                UPDATE resume_runs
                SET status = ?, stage = ?, custom_instructions = ?,
                    interpretation_json = ?, error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    run["status"],
                    run["stage"],
                    run["custom_instructions"],
                    run["interpretation_json"],
                    run_id,
                ),
            )
            raise

    @staticmethod
    def _validate_tex_source(source: str) -> None:
        if "\\documentclass" not in source or "\\begin{document}" not in source:
            raise ResumeRunBlocked("Keep the complete Carivyo TeX document")
        forbidden = re.compile(
            r"\\(?:input|include|includeonly|write18|openin|openout|read|catcode|"
            r"immediate|loop|csname|newread|newwrite|usepackage\s*\{(?:shellesc|"
            r"minted|pythontex))\b",
            flags=re.IGNORECASE,
        )
        if forbidden.search(source):
            raise ResumeRunBlocked("The TeX source contains a blocked file or command primitive")
        if source.count("\\begin{document}") != 1 or source.count("\\end{document}") != 1:
            raise ResumeRunBlocked("The TeX document boundary is invalid")

    @classmethod
    def _validate_tex_revision(cls, current: str, proposed: str) -> None:
        link_pattern = r"\\href\s*\{([^{}]*)\}\s*\{"
        if re.findall(link_pattern, proposed) != re.findall(link_pattern, current):
            raise ResumeRunBlocked("TeX link validation failed")
        if cls._normalize_claim(cls._tex_visible_text(proposed)) != cls._normalize_claim(
            cls._tex_visible_text(current)
        ):
            raise ResumeRunBlocked(
                "Manual TeX edits may change formatting only; use Request changes for evidence-backed wording"
            )

    def _load_frozen_inputs(
        self,
        run: Dict[str, Any],
    ) -> Tuple[
        Dict[str, Any],
        Dict[str, Any],
        Dict[str, Any],
        List[Dict[str, Any]],
        Dict[str, Any],
    ]:
        workspace = Path(run["workspace_path"]).resolve()
        run_spec_path = self._confined_run_path(
            workspace,
            workspace / "inputs" / "run-spec.json",
            "run specification",
        )
        try:
            run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ResumeRunBlocked("The frozen resume run specification is invalid") from exc
        if run_spec.get("run_id") != run["id"]:
            raise ResumeRunBlocked("The frozen resume run identifier does not match")
        output_directory = run_spec.get("output_directory")
        if (
            not isinstance(output_directory, str)
            or Path(output_directory).expanduser().resolve() != workspace
        ):
            raise ResumeRunBlocked("The frozen output directory does not match the run workspace")
        if run_spec.get("network_policy") != "none":
            raise ResumeRunBlocked("The frozen resume run network policy is invalid")
        context_policy = run_spec.get("context_policy", {})
        if (
            context_policy.get("scope") != "run_only"
            or context_policy.get("ambient_context_allowed") is not False
            or context_policy.get("external_files_allowed") is not False
        ):
            raise ResumeRunBlocked("The resume run does not enforce isolated context")

        custom_instructions = run_spec.get("custom_instructions")
        if (
            not isinstance(custom_instructions, str)
            or stable_hash(custom_instructions)
            != run_spec.get("custom_instructions_hash")
        ):
            raise ResumeRunBlocked("The frozen custom-instructions hash does not match")
        template = run_spec.get("template", {})
        legacy_template_hash = stable_hash(
            "carivyo-ats-single-column-v1",
            "Helvetica",
            "single-column",
            "letter",
        )
        supported_templates = {
            "carivyo-ats-single-column-v1": legacy_template_hash,
            self.TEMPLATE_ID: self.TEMPLATE_HASH,
        }
        if supported_templates.get(template.get("id")) != template.get("hash"):
            raise ResumeRunBlocked("The frozen template hash does not match")
        if run_spec.get("skill_version") not in self.SUPPORTED_SKILL_VERSIONS:
            raise ResumeRunBlocked("The frozen resume skill version does not match")

        job_spec = run_spec.get("job_snapshot", {})
        description_path = self._confined_run_path(
            workspace,
            Path(job_spec.get("description_path", "")),
            "job description",
        )
        description = description_path.read_text(encoding="utf-8")
        if (
            job_spec.get("job_id") != run.get("job_id")
            or stable_hash(description) != job_spec.get("snapshot_hash")
            or job_spec.get("snapshot_hash") != run.get("jd_hash")
        ):
            raise ResumeRunBlocked("The frozen job description hash does not match")
        job = {
            "id": job_spec.get("job_id"),
            "company": job_spec.get("company", ""),
            "title": job_spec.get("title", ""),
            "description": description,
            "source_url": job_spec.get("source_url", ""),
        }

        profile_spec = run_spec.get("profile_snapshot", {})
        expected_profile_hash = stable_hash(
            profile_spec.get("version"),
            profile_spec.get("profile"),
            profile_spec.get("capsule"),
        )
        if (
            not profile_spec.get("profile")
            or profile_spec.get("version") != run_spec.get("profile_version")
            or profile_spec.get("version") != run.get("profile_version")
            or profile_spec.get("hash") != expected_profile_hash
        ):
            raise ResumeRunBlocked("The frozen profile snapshot is invalid")
        profile = {
            "version": profile_spec["version"],
            "profile": profile_spec["profile"],
            "capsule": profile_spec.get("capsule", ""),
        }

        evidence = run_spec.get("evidence_claims", [])
        evidence_ids = [
            claim.get("id") for claim in evidence if isinstance(claim, dict)
        ]
        if (
            not evidence
            or len(evidence_ids) != len(evidence)
            or any(not claim_id for claim_id in evidence_ids)
            or len(set(evidence_ids)) != len(evidence_ids)
            or stable_hash(evidence) != run_spec.get("evidence_hash")
            or any(claim.get("approval") != "approved" for claim in evidence)
        ):
            raise ResumeRunBlocked("The frozen evidence package is invalid")

        base_specs = run_spec.get("base_resumes", [])
        if len(base_specs) != 1:
            raise ResumeRunBlocked("The frozen run must contain exactly one selected base")
        base = dict(base_specs[0])
        if base.get("id") != run.get("base_resume_id"):
            raise ResumeRunBlocked("The frozen base-resume identifier does not match")
        source_path = self._confined_run_path(
            workspace,
            Path(base.get("source_path", "")),
            "base source",
        )
        text_path = self._confined_run_path(
            workspace,
            Path(base.get("text_path", "")),
            "base extracted text",
        )
        if (
            self.vault.hash_file(source_path) != base.get("hash")
            or self.vault.hash_file(text_path) != base.get("text_hash")
        ):
            raise ResumeRunBlocked("The frozen base-resume hash does not match")
        base.update(
            {
                "source_path": str(source_path),
                "text_path": str(text_path),
                "content_hash": base["hash"],
            }
        )
        return run_spec, job, profile, list(evidence), base

    @staticmethod
    def _confined_run_path(workspace: Path, path: Path, label: str) -> Path:
        resolved = path.expanduser().resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError as exc:
            raise ResumeRunBlocked(f"The frozen {label} escapes the run workspace") from exc
        if not resolved.is_file():
            raise ResumeRunBlocked(f"The frozen {label} is missing")
        ArtifactVault.assert_not_symlink(path)
        return resolved

    def approve(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        if run["status"] != "needs_user_review":
            raise ResumeRunBlocked("Only a validated resume awaiting review can be approved")
        result = run["result"]
        if (
            result.get("status") != "needs_user_review"
            or result.get("approval")
            != {"required": True, "user_approved": False}
        ):
            raise ResumeRunBlocked("The persisted resume approval state is invalid")
        self._verify_run_integrity(run, result)
        result["status"] = "ready_to_apply"
        result["approval"] = {
            "required": True,
            "user_approved": True,
        }
        result_path = Path(run["result_path"])
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result_path.chmod(0o600)
        self.database.execute(
            """
            UPDATE resume_runs
            SET status = 'ready_to_apply', stage = 'approved',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (run_id,),
        )
        return self.get(run_id)

    def verify_ready_for_handoff(self, run_id: str) -> Dict[str, Any]:
        """Return a run only after revalidating every approval integrity gate."""

        run = self.get(run_id)
        result = run.get("result", {})
        if (
            run.get("status") != "ready_to_apply"
            or run.get("stage") != "approved"
            or result.get("status") != "ready_to_apply"
            or result.get("approval")
            != {"required": True, "user_approved": True}
        ):
            raise ResumeRunBlocked("The resume is not approved and ready for handoff")
        self._verify_run_integrity(run, result)
        return run

    def _ensure_run_mutable(self, run_id: str) -> None:
        locked = self.database.fetch_one(
            """
            SELECT id, status FROM applications
            WHERE resume_run_id = ?
              AND status NOT IN ('draft', 'opened')
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (run_id,),
        )
        if locked:
            raise ResumeRunBlocked(
                "This resume is bound to a submitted application and cannot be changed"
            )

    @staticmethod
    def interpret_instructions(
        instructions: str,
        base: Optional[Dict[str, Any]],
        mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        lowered = instructions.casefold()
        result: List[Dict[str, Any]] = []
        if not instructions.strip():
            result.append(
                {
                    "type": "length",
                    "value": "one_page",
                    "status": "applied",
                    "source": "default",
                }
            )
        if "one page" in lowered or "1 page" in lowered:
            result.append({"type": "length", "value": "one_page", "status": "applied"})
        if "two page" in lowered or "2 page" in lowered:
            result.append({"type": "length", "value": "two_pages", "status": "applied"})
        emphasize = re.findall(
            r"(?:emphasize|focus on|highlight)\s+([^.;\n]+)",
            instructions,
            flags=re.IGNORECASE,
        )
        for value in emphasize[:4]:
            result.append(
                {"type": "emphasis", "value": value.strip(), "status": "applied"}
            )
        exclusions = re.findall(
            r"(?:exclude|remove|do not include)\s+([^.;\n]+)",
            instructions,
            flags=re.IGNORECASE,
        )
        for value in exclusions[:4]:
            result.append(
                {"type": "exclude", "value": value.strip(), "status": "applied"}
            )
        if "keep" in lowered and "layout" in lowered:
            if mode == "tailor":
                result.append(
                    {
                        "type": "layout",
                        "value": "preserve_semantic_structure",
                        "status": "applied",
                        "reason": (
                            "The editable base section order and approved claims are "
                            "preserved; the PDF uses Carivyo's standard ATS-safe rendering."
                        ),
                    }
                )
            else:
                result.append(
                    {
                        "type": "layout",
                        "value": "preserve_base",
                        "status": "blocked",
                        "reason": (
                            "Verified in-place layout editing is unavailable for this "
                            "base format, so an ATS-safe Build-mode template is used."
                        ),
                    }
                )
        if any(term in lowered for term in ("invent", "fake", "hidden keyword", "white text")):
            result.append(
                {
                    "type": "unsafe_instruction",
                    "value": instructions,
                    "status": "rejected",
                    "reason": "Truthfulness and accessible-document rules cannot be overridden.",
                }
            )
        return result

    def _generate(
        self,
        run_id: str,
        job: Dict[str, Any],
        profile: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
        base: Dict[str, Any],
        interpretation: Sequence[Dict[str, Any]],
        variant_number: int,
        previous_result: Optional[Dict[str, Any]] = None,
        mode: str = "build",
        base_selection: Optional[Dict[str, Any]] = None,
        instructions_hash: Optional[str] = None,
        source_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        workspace = Path(
            self.database.fetch_one(
                "SELECT workspace_path FROM resume_runs WHERE id = ?",
                (run_id,),
            )["workspace_path"]
        )
        base_claims = self._base_claims(base, evidence)
        section_order = (
            self._section_order(base_claims)
            if mode == "tailor"
            else list(self.DEFAULT_SECTION_ORDER)
        )
        selected = (
            self._select_tailor_evidence(
                job,
                base_claims,
                interpretation,
                section_order,
            )
            if mode == "tailor"
            else self._select_evidence(job, evidence, interpretation)
        )
        if not selected:
            raise ResumeRunBlocked(
                "No approved evidence is relevant enough to produce a truthful resume"
            )
        source_path = workspace / "variants" / f"resume{variant_number}.tex"
        pdf_path = workspace / "variants" / f"resume{variant_number}.pdf"
        requested_max_pages = 2 if any(
            item.get("value") == "two_pages" and item.get("status") == "applied"
            for item in interpretation
        ) else 1
        max_pages = requested_max_pages
        page_limit_relaxed = False
        required_sections = [
            category
            for category in section_order
            if any(claim["category"] == category for claim in base_claims)
        ]
        selected_for_pdf = list(selected)
        compiled_with_tectonic = False
        while True:
            source_text = source_override or self._build_tex(
                profile["profile"], selected_for_pdf, section_order
            )
            source_path.write_text(source_text, encoding="utf-8")
            source_path.chmod(0o600)
            compiled_with_tectonic = self._compile_tex(source_path, pdf_path)
            if not compiled_with_tectonic:
                if source_override is not None:
                    raise ResumeRunBlocked(
                        "Tectonic is required to compile manual TeX edits"
                    )
                self._build_pdf(
                    profile["profile"],
                    selected_for_pdf,
                    pdf_path,
                    section_order,
                )
            page_count = len(PdfReader(str(pdf_path)).pages)
            if page_count <= max_pages:
                break
            if source_override is not None:
                raise ResumeRunBlocked(
                    f"The edited TeX exceeds the {max_pages}-page limit"
                )
            trimmed = self._trim_lowest_priority_claim(
                selected_for_pdf,
                required_sections,
                job,
                interpretation,
            )
            if len(trimmed) < len(selected_for_pdf):
                selected_for_pdf = trimmed
                continue
            if max_pages == 1:
                max_pages = 2
                page_limit_relaxed = True
                continue
            break

        reader = PdfReader(str(pdf_path))
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        if source_override is not None and previous_result:
            previous_pdf = self._confined_run_path(
                workspace,
                Path(previous_result.get("artifacts", {}).get("pdf", "")),
                "previous generated PDF",
            )
            previous_reader = PdfReader(str(previous_pdf))
            previous_extracted = "\n".join(
                page.extract_text() or "" for page in previous_reader.pages
            )
            if self._normalize_claim(extracted) != self._normalize_claim(
                previous_extracted
            ):
                raise ResumeRunBlocked(
                    "Manual TeX edits may change formatting only; use Request changes for evidence-backed wording"
                )
        requirement_map = self._requirement_evidence_map(
            job["description"],
            selected_for_pdf,
        )
        render_paths = self._render_pdf_pages(
            pdf_path,
            workspace / "renders",
            variant_number,
            len(reader.pages),
        )
        render_path = render_paths[0] if render_paths else None
        evidence_ok = all(
            self._normalize_claim(claim["text"]) in self._normalize_claim(extracted)
            for claim in selected_for_pdf
        )
        change_plan = self._change_plan(
            mode,
            base_claims,
            selected_for_pdf,
            section_order,
        )
        change_percent = (
            self._change_percent(base_claims, selected_for_pdf, section_order)
            if mode == "tailor"
            else None
        )
        change_budget_status = "not_applicable"
        if change_percent is not None:
            if change_percent <= 15:
                change_budget_status = "within_target"
            elif change_percent <= 25:
                change_budget_status = "within_review_budget"
            else:
                change_budget_status = "explicit_review_required"
        links_ok = self._validate_pdf_links(reader, profile["profile"])
        identity_ok = self._validate_identity(extracted, profile["profile"])
        section_order_ok = self._validate_section_order(
            extracted,
            selected_for_pdf,
            section_order,
        )
        present_sections = {
            claim["category"] for claim in selected_for_pdf
        }
        section_inventory = [
            {
                "id": category,
                "label": self.SECTION_LABELS[category],
                "expected": category in required_sections,
                "present": category in present_sections,
                "claim_count": sum(
                    claim["category"] == category for claim in selected_for_pdf
                ),
            }
            for category in section_order
            if category in required_sections or category in present_sections
        ]
        section_completeness_ok = all(
            item["present"] for item in section_inventory if item["expected"]
        )
        parser_validation = validate_pdf_parsers(
            pdf_path,
            pypdf_text=extracted,
            expected_sections=[
                self.SECTION_LABELS[item].casefold()
                for item in present_sections
                if item in self.SECTION_LABELS
            ],
        )
        parser_consensus_ok = parser_validation["status"] != "blocked"
        page_visual_results = [self._validate_render(path) for path in render_paths]
        visual_ok = bool(page_visual_results) and all(
            result[0] for result in page_visual_results
        ) and len(page_visual_results) == len(reader.pages)
        visual_details = {
            "method": "deterministic_raster_all_pages_v2",
            "human_inspected": False,
            "page_count": len(reader.pages),
            "validated_page_count": len(page_visual_results),
            "pages": [result[1] for result in page_visual_results],
            "reason": "passed_all_page_machine_checks" if visual_ok else "page_visual_check_failed",
        }
        validation = {
            "export_ok": pdf_path.exists() and pdf_path.stat().st_size > 500,
            "page_count": len(reader.pages),
            "page_count_ok": len(reader.pages) <= max_pages,
            "requested_page_limit": requested_max_pages,
            "effective_page_limit": max_pages,
            "section_preserving_page_limit_relaxed": page_limit_relaxed,
            "text_extraction_ok": len(extracted.strip()) > 80,
            "parser_consensus_ok": parser_consensus_ok,
            "parser_validation": parser_validation,
            "links_ok": links_ok,
            "identity_ok": identity_ok,
            "section_order_ok": section_order_ok,
            "section_completeness_ok": section_completeness_ok,
            "section_inventory": section_inventory,
            "visual_ok": visual_ok,
            "visual_details": visual_details,
            "evidence_ok": evidence_ok,
            "change_percent": change_percent,
            "change_budget_applicable": mode == "tailor",
            "change_budget_status": change_budget_status,
        }
        if not all(
            validation[key]
            for key in (
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
        ):
            raise ResumeRunBlocked("Deterministic document validation failed")

        pdf_hash = self.vault.hash_file(pdf_path)
        editable_source_hash = self.vault.hash_file(source_path)
        extracted_text_hash = stable_hash(extracted)
        export_filename = self._professional_export_filename(profile, job)
        ats_analysis = self.ats.analyze(
            extracted,
            self._ats_metadata(
                pdf_path,
                reader,
                extracted,
                source_text,
                job,
                profile,
                export_filename,
                parser_validation,
            ),
            job["description"],
        )
        frozen_baseline_path = workspace / "inputs" / "reference-base-extracted.txt"
        baseline_text = frozen_baseline_path.read_text(
            encoding="utf-8", errors="replace"
        )
        baseline_analysis = self.ats.analyze(
            baseline_text,
            {
                "filename": base["original_name"],
                "file_format": base["original_kind"],
                "size_bytes": base["original_size_bytes"],
                "image_only": not bool(baseline_text.strip()),
                "job_title": job["title"],
                "extracted_char_count": len(baseline_text),
                "source_char_count": len(baseline_text),
            },
            job["description"],
        )
        baseline_categories = {
            item["id"]: item for item in baseline_analysis["category_summaries"]
        }
        ats_comparison = {
            "baseline_scope": (
                "Imported resume text evaluated against the same frozen JD. "
                "Layout-only fields are included only when the imported format exposes them."
            ),
            "baseline_score": baseline_analysis["overall_score"],
            "current_score": ats_analysis["overall_score"],
            "score_delta": round(
                ats_analysis["overall_score"] - baseline_analysis["overall_score"], 1
            ),
            "analyzer_version": ats_analysis["analyzer_version"],
            "categories": [
                {
                    "id": current["id"],
                    "label": current["label"],
                    "baseline": baseline_categories.get(current["id"], {}).get(
                        "percentage"
                    ),
                    "current": current["percentage"],
                    "delta": (
                        round(
                            current["percentage"]
                            - baseline_categories[current["id"]]["percentage"],
                            1,
                        )
                        if current["percentage"] is not None
                        and baseline_categories.get(current["id"], {}).get("percentage")
                        is not None
                        else None
                    ),
                }
                for current in ats_analysis["category_summaries"]
            ],
        }

        coverage = {
            key: [item for item in requirement_map if item["classification"] == key]
            for key in ("direct", "transferable", "unsupported", "unclear")
        }
        hiring_review = {
            "scan": "ATS-safe single-column document with explicit evidence selection.",
            "strongest_evidence": [claim["text"] for claim in selected_for_pdf[:3]],
            "remaining_gaps": [
                item["requirement"] for item in coverage["unsupported"][:5]
            ],
            "interview_probes": [
                f"Be ready to explain: {claim['text']}"
                for claim in selected_for_pdf[:3]
            ],
        }
        decision_support = (
            self.hiring_agent.evaluate(
                run_id=run_id,
                claims=selected_for_pdf,
                requirements=requirement_map,
                section_inventory=section_inventory,
                deterministic_assessment=ats_analysis.get("assessment"),
            )
            if self.hiring_agent
            else {
                "status": "disabled",
                "advisory": True,
                "authoritative": False,
                "dimensions": [],
                "strengths": [],
                "concerns": [],
                "recommended_changes": [],
                "interview_probes": [],
                "missing_sections": [],
            }
        )
        hiring_review["decision_support"] = decision_support
        self._write_json(workspace / "reviews" / "requirement-evidence-map.json", requirement_map)
        self._write_json(workspace / "reviews" / "change-plan.json", change_plan)
        self._write_json(workspace / "reviews" / "hiring-review.json", hiring_review)
        validation_path = workspace / "reports" / "validation.json"
        self._write_json(validation_path, validation)
        run_spec_path = workspace / "inputs" / "run-spec.json"
        run_spec = json.loads(run_spec_path.read_text(encoding="utf-8"))
        base_spec = (run_spec.get("base_resumes") or [{}])[0]
        run_spec_hash = self.vault.hash_file(run_spec_path)
        validation_hash = stable_hash(validation)
        validation_report_file_hash = self.vault.hash_file(validation_path)
        render_hash = self.vault.hash_file(render_path) if render_path else ""
        revision_spec_hash = ""
        if variant_number > 1:
            revision_spec_hash = self.vault.hash_file(
                workspace / "inputs" / f"revision-{variant_number}.json"
            )
        effective_instructions_hash = (
            instructions_hash or run_spec["custom_instructions_hash"]
        )
        ats_analysis["bindings"] = {
            "run_spec_hash": run_spec_hash,
            "jd_hash": run_spec["job_snapshot"]["snapshot_hash"],
            "profile_snapshot_hash": run_spec["profile_snapshot"]["hash"],
            "evidence_hash": run_spec["evidence_hash"],
            "base_resume_hash": base_spec["hash"],
            "base_resume_text_hash": base_spec["text_hash"],
            "custom_instructions_hash": effective_instructions_hash,
            "original_custom_instructions_hash": run_spec[
                "custom_instructions_hash"
            ],
            "revision_spec_hash": revision_spec_hash,
            "template_hash": run_spec["template"]["hash"],
            "skill_version": run_spec["skill_version"],
            "pdf_hash": pdf_hash,
            "editable_source_hash": editable_source_hash,
            "extracted_text_hash": extracted_text_hash,
            "render_hash": render_hash,
            "validation_hash": validation_hash,
            "validation_report_file_hash": validation_report_file_hash,
            "variant": variant_number,
        }
        ats_analysis_hash = stable_hash(ats_analysis)
        ats_analysis["bindings"]["analysis_hash"] = ats_analysis_hash
        ats_report_path = workspace / "reports" / "ats-analysis.json"
        self._write_json(ats_report_path, ats_analysis)
        ats_report_file_hash = self.vault.hash_file(ats_report_path)
        self.database.execute(
            """
            INSERT INTO ats_analyses(
                id, run_id, analyzer_version, score, analysis_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                run_id,
                ats_analysis["analyzer_version"],
                ats_analysis["overall_score"],
                json_dumps(ats_analysis),
            ),
        )

        result = {
            "status": "needs_user_review",
            "source_compiler": (
                "tectonic" if compiled_with_tectonic else "reportlab_fallback"
            ),
            "editable_source_exact": compiled_with_tectonic,
            "export_filename": export_filename,
            "selected_base_resume_id": base["id"],
            "base_selection": base_selection
            or run_spec.get("base_selection")
            or {"score": 0, "rationale": ["Only available base resume."]},
            "mode": "revise" if variant_number > 1 else mode,
            "base_mode": mode,
            "custom_instruction_interpretation": list(interpretation),
            "coverage": coverage,
            "jd_quality": ats_analysis.get("jd_quality", {}),
            "changes": change_plan,
            "validation": validation,
            "ats_analysis": ats_analysis,
            "ats_comparison": ats_comparison,
            "hiring_evaluation": decision_support,
            "section_inventory": section_inventory,
            "provenance": {
                "run_spec_hash": run_spec_hash,
                "job_snapshot_hash": run_spec["job_snapshot"]["snapshot_hash"],
                "profile_snapshot_hash": run_spec["profile_snapshot"]["hash"],
                "evidence_hash": run_spec["evidence_hash"],
                "base_resume_hash": base_spec["hash"],
                "base_resume_text_hash": base_spec["text_hash"],
                "custom_instructions_hash": effective_instructions_hash,
                "original_custom_instructions_hash": run_spec[
                    "custom_instructions_hash"
                ],
                "revision_spec_hash": revision_spec_hash,
                "template_hash": run_spec["template"]["hash"],
                "skill_version": run_spec["skill_version"],
                "pdf_hash": pdf_hash,
                "editable_source_hash": editable_source_hash,
                "extracted_text_hash": extracted_text_hash,
                "render_hash": render_hash,
                "validation_hash": validation_hash,
                "validation_report_file_hash": validation_report_file_hash,
                "ats_analysis_hash": ats_analysis_hash,
                "ats_report_file_hash": ats_report_file_hash,
            },
            "approval": {
                "required": True,
                "user_approved": False,
            },
            "remaining_gaps": hiring_review["remaining_gaps"]
            + (
                [
                    "The imported layout was not modified; this base format uses an ATS-safe Build-mode template."
                ]
                if mode == "build"
                else []
            ),
            "interview_probes": (
                decision_support.get("interview_probes")
                or hiring_review["interview_probes"]
            ),
            "artifacts": {
                "pdf": str(pdf_path.resolve()),
                "editable_source": str(source_path.resolve()),
                "render": str(render_path.resolve()) if render_path else "",
                "render_pages": [str(path.resolve()) for path in render_paths],
                "validation_report": str(
                    (workspace / "reports" / "validation.json").resolve()
                ),
                "ats_report": str(ats_report_path.resolve()),
                "hiring_review": str(
                    (workspace / "reviews" / "hiring-review.json").resolve()
                ),
            },
            "variant": variant_number,
        }
        result_path = workspace / "result.json"
        self._write_json(result_path, result)
        self.database.execute(
            """
            UPDATE resume_runs
            SET status = 'needs_user_review', stage = 'review',
                result_path = ?, error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(result_path), run_id),
        )
        self._cleanup_superseded_variants(workspace, variant_number)
        return self.get(run_id)

    def ats_analysis(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        result = run.get("result", {})
        analysis = result.get("ats_analysis")
        if not analysis:
            raise KeyError("ATS analysis not found")
        return analysis

    @classmethod
    def _ats_metadata(
        cls,
        pdf_path: Path,
        reader: PdfReader,
        extracted: str,
        source_text: str,
        job: Dict[str, Any],
        profile: Dict[str, Any],
        export_filename: str,
        parser_validation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        profile_links = profile["profile"].get("identity", {}).get("links", [])
        linkedin_url = next(
            (link for link in profile_links if "linkedin.com/" in link.casefold()),
            "",
        )
        source_is_tex = source_text.lstrip().startswith("\\documentclass")
        source_char_count = (
            len(cls._tex_visible_text(source_text))
            if source_is_tex
            else len(source_text)
        )
        return {
            "filename": export_filename,
            "file_format": "pdf",
            "size_bytes": pdf_path.stat().st_size,
            "page_count": len(reader.pages),
            "column_count": 1,
            "has_tables": False,
            "has_text_boxes": False,
            "image_only": not bool(extracted.strip()),
            "job_title": job["title"],
            "linkedin_url": linkedin_url,
            "extracted_char_count": len(extracted),
            "source_char_count": source_char_count,
            "parse_rate": (
                parser_validation.get("consensus_score")
                if isinstance(parser_validation, dict)
                else None
            ),
            "parser_validation": parser_validation or {},
        }

    @staticmethod
    def _tex_visible_text(source: str) -> str:
        """Approximate visible TeX text without using the produced PDF as its own baseline."""

        body = source.partition("\\begin{document}")[2]
        body = body.partition("\\end{document}")[0]
        body = re.sub(r"%[^\n]*", " ", body)
        body = re.sub(
            r"\\href\s*\{[^{}]*\}\s*\{([^{}]*)\}", r" \1 ", body
        )
        body = re.sub(r"\\(?:resumesection|textbf|textit|emph)\s*\{([^{}]*)\}", r" \1 ", body)
        body = re.sub(r"\\(?:begin|end)\s*\{[^{}]*\}", " ", body)
        body = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", " ", body)
        body = body.replace("{", " ").replace("}", " ").replace("~", " ")
        body = re.sub(r"\\[%&#_$]", " ", body)
        return " ".join(body.split())

    @staticmethod
    def _professional_export_filename(
        profile: Dict[str, Any], job: Dict[str, Any]
    ) -> str:
        identity = profile.get("profile", {}).get("identity", {})
        candidate = str(identity.get("name") or "Candidate")
        role = str(job.get("title") or "Role")

        def safe_words(value: str, limit: int) -> List[str]:
            return re.findall(r"[A-Za-z0-9]+", value)[:limit]

        parts = safe_words(candidate, 4) + safe_words(role, 5) + ["Resume"]
        return "_".join(parts)[:112].rstrip("_") + ".pdf"

    def _verify_run_integrity(
        self,
        run: Dict[str, Any],
        result: Dict[str, Any],
    ) -> None:
        run_spec, job, profile, _evidence, base = self._load_frozen_inputs(run)
        workspace = Path(run["workspace_path"]).resolve()
        result_path = self._confined_run_path(
            workspace,
            Path(run.get("result_path", "")),
            "resume result",
        )
        if result_path != (workspace / "result.json").resolve():
            raise ResumeRunBlocked("The persisted resume result path is invalid")
        if result.get("selected_base_resume_id") != base.get("id"):
            raise ResumeRunBlocked("The generated resume is bound to the wrong base")

        variant = result.get("variant")
        template_id = run_spec.get("template", {}).get("id")
        allowed_variants = {1, 2} if template_id == "carivyo-ats-single-column-v1" else {1, 2, 3, 4}
        if (
            isinstance(variant, bool)
            or not isinstance(variant, int)
            or variant not in allowed_variants
        ):
            raise ResumeRunBlocked("The generated resume variant is invalid")
        instructions_hash, revision_spec_hash = self._instruction_bindings(
            workspace,
            run,
            run_spec,
            variant,
        )

        run_spec_path = workspace / "inputs" / "run-spec.json"
        base_spec = run_spec["base_resumes"][0]
        provenance = result.get("provenance", {})
        if not isinstance(provenance, dict):
            raise ResumeRunBlocked("The generated resume provenance is invalid")
        frozen_provenance = {
            "run_spec_hash": self.vault.hash_file(run_spec_path),
            "job_snapshot_hash": run_spec["job_snapshot"]["snapshot_hash"],
            "profile_snapshot_hash": run_spec["profile_snapshot"]["hash"],
            "evidence_hash": run_spec["evidence_hash"],
            "base_resume_hash": base_spec["hash"],
            "base_resume_text_hash": base_spec["text_hash"],
            "custom_instructions_hash": instructions_hash,
            "original_custom_instructions_hash": run_spec[
                "custom_instructions_hash"
            ],
            "revision_spec_hash": revision_spec_hash,
            "template_hash": run_spec["template"]["hash"],
            "skill_version": run_spec["skill_version"],
        }
        for key, expected in frozen_provenance.items():
            if provenance.get(key) != expected:
                raise ResumeRunBlocked(f"The frozen resume provenance is invalid: {key}")

        artifacts = result.get("artifacts", {})
        if not isinstance(artifacts, dict):
            raise ResumeRunBlocked("The generated resume artifact manifest is invalid")
        source_suffix = ".md" if template_id == "carivyo-ats-single-column-v1" else ".tex"
        expected_artifacts = {
            "pdf": workspace / "variants" / f"resume{variant}.pdf",
            "editable_source": workspace / "variants" / f"resume{variant}{source_suffix}",
            "render": workspace / "renders" / f"resume{variant}.png",
            "validation_report": workspace / "reports" / "validation.json",
            "ats_report": workspace / "reports" / "ats-analysis.json",
        }
        artifact_labels = {
            "pdf": "generated PDF",
            "editable_source": "editable source",
            "render": "generated render",
            "validation_report": "validation report",
            "ats_report": "ATS analysis report",
        }
        artifact_paths: Dict[str, Path] = {}
        for key, expected_path in expected_artifacts.items():
            path = self._confined_run_path(
                workspace,
                Path(artifacts.get(key, "")),
                artifact_labels[key],
            )
            if path != expected_path.resolve():
                raise ResumeRunBlocked(f"The {artifact_labels[key]} path is invalid")
            artifact_paths[key] = path

        try:
            source_text = artifact_paths["editable_source"].read_text(encoding="utf-8")
            reader = PdfReader(str(artifact_paths["pdf"]))
            extracted = "\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise ResumeRunBlocked("The generated resume artifacts are unreadable") from exc

        artifact_hashes = {
            "pdf_hash": self.vault.hash_file(artifact_paths["pdf"]),
            "editable_source_hash": self.vault.hash_file(
                artifact_paths["editable_source"]
            ),
            "extracted_text_hash": stable_hash(extracted),
            "render_hash": self.vault.hash_file(artifact_paths["render"]),
            "validation_report_file_hash": self.vault.hash_file(
                artifact_paths["validation_report"]
            ),
            "ats_report_file_hash": self.vault.hash_file(
                artifact_paths["ats_report"]
            ),
        }
        artifact_errors = {
            "pdf_hash": "The generated PDF changed after ATS analysis",
            "editable_source_hash": "The editable resume changed after ATS analysis",
            "extracted_text_hash": "The analyzed PDF text no longer matches",
            "render_hash": "The generated resume render changed after validation",
            "validation_report_file_hash": "The validation report changed after validation",
            "ats_report_file_hash": "The ATS report changed after analysis",
        }
        for key, actual in artifact_hashes.items():
            if provenance.get(key) != actual:
                raise ResumeRunBlocked(artifact_errors[key])

        validation = self._read_json_artifact(
            artifact_paths["validation_report"],
            "validation report",
        )
        if validation != result.get("validation"):
            raise ResumeRunBlocked("The persisted validation results do not match")
        validation_hash = stable_hash(validation)
        if provenance.get("validation_hash") != validation_hash:
            raise ResumeRunBlocked("The persisted validation binding is invalid")
        failed_validation = sorted(
            {
                *(
                    key
                    for key in self.CRITICAL_VALIDATION_FLAGS
                    if (
                        key != "section_completeness_ok"
                        or run_spec.get("skill_version") == "5.0.0"
                    )
                    if validation.get(key) is not True
                ),
                *(
                    key
                    for key, value in validation.items()
                    if key.endswith("_ok") and value is not True
                ),
            }
        )
        if failed_validation:
            raise ResumeRunBlocked(
                "Persisted validation failed: " + ", ".join(failed_validation)
            )
        page_count = validation.get("page_count")
        if (
            isinstance(page_count, bool)
            or not isinstance(page_count, int)
            or page_count != len(reader.pages)
            or page_count < 1
        ):
            raise ResumeRunBlocked("The persisted page-count validation failed")
        self._verify_change_budget(validation)

        report = self._read_json_artifact(
            artifact_paths["ats_report"],
            "ATS analysis report",
        )
        if report != result.get("ats_analysis"):
            raise ResumeRunBlocked("The resume result and ATS report disagree")
        report_summary = report.get("report_summary")
        readiness = (
            report_summary.get("readiness")
            if isinstance(report_summary, dict)
            else None
        )
        critical_failures = report.get("critical_failures")
        checks = report.get("checks")
        if not isinstance(checks, list):
            raise ResumeRunBlocked("The persisted ATS checks are invalid")
        derived_critical_failures = [
            check.get("id")
            for check in checks
            if isinstance(check, dict)
            and check.get("id") in CRITICAL_CHECK_IDS
            and check.get("status") == "fail"
        ]
        if (
            readiness == "blocked"
            or not isinstance(critical_failures, list)
            or critical_failures
            or derived_critical_failures
        ):
            raise ResumeRunBlocked("ATS readiness is blocked by critical failures")
        if readiness not in {"strong", "review", "needs_focus"}:
            raise ResumeRunBlocked("The persisted ATS readiness is invalid")
        if (
            len(checks) != 27
            or any(not isinstance(check, dict) for check in checks)
            or len({check.get("id") for check in checks}) != 27
        ):
            raise ResumeRunBlocked("The persisted ATS check contract is invalid")

        bindings = report.get("bindings")
        if not isinstance(bindings, dict):
            raise ResumeRunBlocked("The ATS analysis binding is invalid")
        expected_bindings = {
            "run_spec_hash": frozen_provenance["run_spec_hash"],
            "jd_hash": frozen_provenance["job_snapshot_hash"],
            "profile_snapshot_hash": frozen_provenance["profile_snapshot_hash"],
            "evidence_hash": frozen_provenance["evidence_hash"],
            "base_resume_hash": frozen_provenance["base_resume_hash"],
            "base_resume_text_hash": frozen_provenance["base_resume_text_hash"],
            "custom_instructions_hash": frozen_provenance[
                "custom_instructions_hash"
            ],
            "original_custom_instructions_hash": frozen_provenance[
                "original_custom_instructions_hash"
            ],
            "revision_spec_hash": revision_spec_hash,
            "template_hash": frozen_provenance["template_hash"],
            "skill_version": frozen_provenance["skill_version"],
            "pdf_hash": artifact_hashes["pdf_hash"],
            "editable_source_hash": artifact_hashes["editable_source_hash"],
            "extracted_text_hash": artifact_hashes["extracted_text_hash"],
            "render_hash": artifact_hashes["render_hash"],
            "validation_hash": validation_hash,
            "validation_report_file_hash": artifact_hashes[
                "validation_report_file_hash"
            ],
            "variant": variant,
        }
        if set(bindings) != {*expected_bindings, "analysis_hash"} or any(
            bindings.get(key) != expected
            for key, expected in expected_bindings.items()
        ):
            raise ResumeRunBlocked("The ATS analysis input bindings are invalid")
        bound_hash = bindings.get("analysis_hash")
        canonical = json.loads(json.dumps(report))
        canonical["bindings"].pop("analysis_hash", None)
        if (
            stable_hash(canonical) != bound_hash
            or bound_hash != provenance.get("ats_analysis_hash")
        ):
            raise ResumeRunBlocked("The ATS analysis binding is invalid")

        reproduced = self.ats.analyze(
            extracted,
            self._ats_metadata(
                artifact_paths["pdf"],
                reader,
                extracted,
                source_text,
                job,
                profile,
                result.get("export_filename")
                or self._professional_export_filename(profile, job),
                validation.get("parser_validation")
                if isinstance(validation.get("parser_validation"), dict)
                else None,
            ),
            job["description"],
        )
        report_without_bindings = json.loads(json.dumps(report))
        report_without_bindings.pop("bindings", None)
        if report_without_bindings != reproduced:
            raise ResumeRunBlocked("The persisted ATS analysis cannot be reproduced")

        database_rows = self.database.fetch_all(
            """
            SELECT analyzer_version, score, analysis_json
            FROM ats_analyses WHERE run_id = ?
            """,
            (run["id"],),
        )
        matching_rows = [
            row
            for row in database_rows
            if json_loads(row.get("analysis_json"), None) == report
        ]
        if len(matching_rows) != 1:
            raise ResumeRunBlocked("The persisted ATS analysis does not match")
        database_row = matching_rows[0]
        if (
            database_row.get("analyzer_version") != report.get("analyzer_version")
            or database_row.get("score") != report.get("overall_score")
        ):
            raise ResumeRunBlocked("The persisted ATS analysis metadata does not match")

    def _instruction_bindings(
        self,
        workspace: Path,
        run: Dict[str, Any],
        run_spec: Dict[str, Any],
        variant: int,
    ) -> Tuple[str, str]:
        original_hash = run_spec["custom_instructions_hash"]
        if variant == 1:
            instructions_hash = original_hash
            revision_spec_hash = ""
        else:
            revision_path = self._confined_run_path(
                workspace,
                workspace / "inputs" / f"revision-{variant}.json",
                "revision specification",
            )
            revision = self._read_json_artifact(
                revision_path,
                "revision specification",
            )
            combined = revision.get("combined_instructions")
            instructions_hash = (
                stable_hash(combined) if isinstance(combined, str) else ""
            )
            if (
                revision.get("variant") != variant
                or revision.get("combined_instructions_hash") != instructions_hash
                or revision.get("original_instructions_hash") != original_hash
                or not isinstance(revision.get("previous_result_hash"), str)
                or len(revision["previous_result_hash"]) != 64
            ):
                raise ResumeRunBlocked("The frozen revision specification is invalid")
            revision_spec_hash = self.vault.hash_file(revision_path)
        if stable_hash(run.get("custom_instructions")) != instructions_hash:
            raise ResumeRunBlocked("The persisted custom instructions do not match")
        return instructions_hash, revision_spec_hash

    @staticmethod
    def _verify_change_budget(validation: Dict[str, Any]) -> None:
        applicable = validation.get("change_budget_applicable")
        percent = validation.get("change_percent")
        status = validation.get("change_budget_status")
        if applicable is True:
            if (
                isinstance(percent, bool)
                or not isinstance(percent, (int, float))
                or not 0 <= percent <= 25
                or status not in {"within_target", "within_review_budget"}
            ):
                raise ResumeRunBlocked("The persisted change-budget validation failed")
        elif applicable is False:
            if percent is not None or status != "not_applicable":
                raise ResumeRunBlocked("The persisted change-budget validation failed")
        else:
            raise ResumeRunBlocked("The persisted change-budget validation failed")

    @staticmethod
    def _read_json_artifact(path: Path, label: str) -> Dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ResumeRunBlocked(f"The persisted {label} is invalid") from exc
        if not isinstance(value, dict):
            raise ResumeRunBlocked(f"The persisted {label} is invalid")
        return value

    @classmethod
    def _select_base(
        cls,
        job: Dict[str, Any],
        bases: Sequence[Dict[str, Any]],
        evidence: Sequence[Dict[str, Any]],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        job_tokens = set(tokenize(f"{job['title']} {job['description']}"))
        title_tokens = set(tokenize(job["title"]))
        scored: List[Tuple[float, int, Dict[str, Any], Dict[str, Any]]] = []
        for index, base in enumerate(bases):
            claims = cls._base_claims(base, evidence)
            track_overlap = len(title_tokens & set(tokenize(base.get("track") or "")))
            claim_overlaps = [
                len(job_tokens & set(tokenize(claim["text"])))
                for claim in claims
            ]
            relevant_claims = sum(overlap > 0 for overlap in claim_overlaps)
            strongest_overlap = sum(sorted(claim_overlaps, reverse=True)[:5])
            editable = cls._mode_for_base(base, evidence) == "tailor"
            score = (
                track_overlap * 8
                + relevant_claims * 1.5
                + strongest_overlap
                + (6 if editable else 0)
            )
            rationale = [
                f"{relevant_claims} approved claims overlap the selected job.",
                (
                    "Supports low-change Tailor mode."
                    if editable
                    else "Requires the ATS-safe Build fallback."
                ),
            ]
            if track_overlap:
                rationale.insert(0, "Resume track aligns with the job title.")
            scored.append(
                (
                    score,
                    -index,
                    base,
                    {
                        "score": round(score, 1),
                        "rationale": rationale,
                        "evaluated_base_count": len(bases),
                    },
                )
            )
        _, _, selected, selection = max(
            scored,
            key=lambda item: (item[0], item[1], item[2]["id"]),
        )
        return selected, selection

    @classmethod
    def _normalized_base_evidence(
        cls,
        base: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Re-extract one approved base without mutating the active profile.

        This upgrades legacy PDF whitespace and wrapped-line extraction inside
        the frozen run. Every derived claim still comes from the exact approved
        source artifact and carries deterministic source-location provenance.
        """

        fallback_text = Path(base["text_path"]).read_text(
            encoding="utf-8",
            errors="replace",
        )
        try:
            text = extract_in_subprocess(
                Path(base["source_path"]).resolve(),
                str(base["original_kind"]),
            )
            extracted, _summary = build_evidence(text)
            approved_source_claims = [
                claim
                for claim in evidence
                if claim.get("artifact_id") == base.get("artifact_id")
            ]
            used_ids: set[str] = set()
            claims = []
            for claim in extracted:
                if claim.get("category") not in cls.RESUME_CATEGORIES:
                    continue
                fresh_start, fresh_end = cls._source_line_range(
                    claim["source_location"]
                )
                source_claims = [
                    source_claim
                    for source_claim in approved_source_claims
                    if cls._source_ranges_overlap(
                        (fresh_start, fresh_end),
                        cls._source_line_range(source_claim["source_location"]),
                    )
                ]
                source_claim = next(
                    (
                        item
                        for item in source_claims
                        if str(item["id"]) not in used_ids
                    ),
                    None,
                )
                if source_claim is None:
                    raise ValueError(
                        "Normalized evidence could not be bound to an approved claim"
                    )
                claim_id = str(source_claim["id"])
                used_ids.add(claim_id)
                claims.append(
                    {
                        **claim,
                        "id": claim_id,
                        "artifact_id": base["artifact_id"],
                        "confidence": 1.0,
                        "derived_from_approved_artifact": True,
                        "source_claim_ids": [
                            str(item["id"]) for item in source_claims
                        ],
                    }
                )
            if claims:
                return text, claims
        except (OSError, ValueError):
            pass
        return fallback_text, cls._base_claims(base, evidence)

    @staticmethod
    def _source_line_range(source_location: str) -> Tuple[int, int]:
        values = [int(value) for value in re.findall(r"\d+", source_location)]
        if not values:
            return (10_000, 10_000)
        return (values[0], values[-1])

    @staticmethod
    def _source_ranges_overlap(
        left: Tuple[int, int],
        right: Tuple[int, int],
    ) -> bool:
        return left[0] <= right[1] and right[0] <= left[1]

    @classmethod
    def _job_scoped_evidence(
        cls,
        job: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
        base: Dict[str, Any],
        mode: str,
    ) -> List[Dict[str, Any]]:
        eligible = [
            claim
            for claim in evidence
            if claim.get("artifact_id") == base.get("artifact_id")
            and claim.get("category") in cls.RESUME_CATEGORIES
        ]
        base_claims = cls._base_claims(base, eligible)
        if mode == "tailor":
            selected = list(base_claims)
            limit = 12
        else:
            selected = []
            limit = 36

        job_tokens = set(tokenize(f"{job['title']} {job['description']}"))
        scored: List[Tuple[int, float, str, Dict[str, Any]]] = []
        selected_ids = {claim["id"] for claim in selected}
        for claim in eligible:
            if claim["id"] in selected_ids:
                continue
            overlap = len(job_tokens & set(tokenize(claim["text"])))
            continuity_bonus = 1 if claim["category"] in {"education", "summary"} else 0
            scored.append(
                (
                    overlap + continuity_bonus,
                    float(claim.get("confidence") or 0),
                    claim["id"],
                    claim,
                )
            )
        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        for score, _, _, claim in scored:
            if mode == "tailor" and score <= 0:
                continue
            selected.append(claim)
            if len(selected) >= len(base_claims) + limit:
                break
        return selected

    @classmethod
    def _mode_for_base(
        cls,
        base: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
    ) -> str:
        if not base.get("usable_for_tailoring"):
            return "build"
        if base.get("editable_kind") not in {"text", "markdown"}:
            return "build"
        if not any(
            claim.get("artifact_id") == base.get("artifact_id")
            and claim.get("category") in cls.RESUME_CATEGORIES
            for claim in evidence
        ):
            return "build"
        return "tailor"

    @classmethod
    def _base_claims(
        cls,
        base: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        return [
            claim
            for claim in evidence
            if claim.get("artifact_id") == base.get("artifact_id")
            and claim.get("category") in cls.RESUME_CATEGORIES
        ]

    @classmethod
    def _section_order(
        cls,
        claims: Sequence[Dict[str, Any]],
    ) -> List[str]:
        first_lines: Dict[str, int] = {}
        for claim in claims:
            match = re.search(r"(\d+)", claim.get("source_location", ""))
            line = int(match.group(1)) if match else 10_000
            category = claim["category"]
            first_lines[category] = min(first_lines.get(category, line), line)
        ordered = [
            category
            for category, _ in sorted(first_lines.items(), key=lambda item: item[1])
        ]
        return ordered + [
            category
            for category in cls.DEFAULT_SECTION_ORDER
            if category not in ordered
        ]

    @classmethod
    def _select_tailor_evidence(
        cls,
        job: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
        interpretation: Sequence[Dict[str, Any]],
        section_order: Sequence[str],
    ) -> List[Dict[str, Any]]:
        exclusions = [
            item.get("value", "").casefold()
            for item in interpretation
            if item.get("type") == "exclude" and item.get("status") == "applied"
        ]
        selected: List[Dict[str, Any]] = []
        for category in section_order:
            category_claims = [
                claim
                for claim in evidence
                if claim["category"] == category
                and not any(
                    value and value in claim["text"].casefold()
                    for value in exclusions
                )
            ]
            selected.extend(sorted(category_claims, key=cls._source_line))
        return selected

    @classmethod
    def _ordered_claims(
        cls,
        claims: Sequence[Dict[str, Any]],
        section_order: Sequence[str],
    ) -> List[Dict[str, Any]]:
        return [
            claim
            for category in section_order
            for claim in claims
            if claim["category"] == category
        ]

    @classmethod
    def _change_plan(
        cls,
        mode: str,
        base_claims: Sequence[Dict[str, Any]],
        generated_claims: Sequence[Dict[str, Any]],
        section_order: Sequence[str],
    ) -> List[Dict[str, Any]]:
        if mode == "build":
            return [
                {
                    "type": "add",
                    "before": "",
                    "after": claim["text"],
                    "evidence_ids": [claim["id"]],
                    "reason": "Selected approved evidence for a named job requirement.",
                }
                for claim in generated_claims
            ]
        original = cls._ordered_claims(base_claims, section_order)
        generated = cls._ordered_claims(generated_claims, section_order)
        original_index = {claim["id"]: index for index, claim in enumerate(original)}
        generated_index = {claim["id"]: index for index, claim in enumerate(generated)}
        changes: List[Dict[str, Any]] = []
        for claim in original:
            if claim["id"] not in generated_index:
                changes.append(
                    {
                        "type": "remove",
                        "before": claim["text"],
                        "after": "",
                        "evidence_ids": [claim["id"]],
                        "reason": "Removed by explicit instruction or page-fit selection.",
                    }
                )
        for claim in generated:
            if claim["id"] not in original_index:
                changes.append(
                    {
                        "type": "add",
                        "before": "",
                        "after": claim["text"],
                        "evidence_ids": [claim["id"]],
                        "reason": "Added from approved evidence for a named requirement.",
                    }
                )
            elif original_index[claim["id"]] != generated_index[claim["id"]]:
                changes.append(
                    {
                        "type": "move",
                        "before": claim["text"],
                        "after": claim["text"],
                        "evidence_ids": [claim["id"]],
                        "reason": "Moved stronger job-relevant evidence earlier without rewriting it.",
                    }
                )
        return changes

    @classmethod
    def _change_percent(
        cls,
        base_claims: Sequence[Dict[str, Any]],
        generated_claims: Sequence[Dict[str, Any]],
        section_order: Sequence[str],
    ) -> float:
        original = [
            cls._normalize_claim(claim["text"])
            for claim in cls._ordered_claims(base_claims, section_order)
        ]
        generated = [
            cls._normalize_claim(claim["text"])
            for claim in cls._ordered_claims(generated_claims, section_order)
        ]
        if not original:
            return 100.0
        return round((1 - SequenceMatcher(None, original, generated).ratio()) * 100, 1)

    @staticmethod
    def _validate_pdf_links(reader: PdfReader, profile: Dict[str, Any]) -> bool:
        identity = profile.get("identity", {})
        expected: List[str] = []
        if identity.get("email"):
            expected.append(f"mailto:{identity['email']}")
        for link in (identity.get("links") or [])[:2]:
            parsed = urlparse(link)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return False
            expected.append(link)
        observed: set[str] = set()
        for page in reader.pages:
            for reference in page.get("/Annots", []) or []:
                annotation = reference.get_object()
                action = annotation.get("/A")
                if action and action.get("/URI"):
                    observed.add(str(action.get("/URI")))
        return observed == set(expected)

    @classmethod
    def _validate_identity(cls, extracted: str, profile: Dict[str, Any]) -> bool:
        identity = profile.get("identity", {})
        normalized = cls._normalize_claim(extracted)
        for value in (
            identity.get("name"),
            identity.get("email"),
            identity.get("phone"),
        ):
            if value and cls._normalize_claim(value) not in normalized:
                return False
        return True

    @classmethod
    def _validate_section_order(
        cls,
        extracted: str,
        claims: Sequence[Dict[str, Any]],
        section_order: Sequence[str],
    ) -> bool:
        normalized = extracted.casefold()
        headings = [
            cls.SECTION_LABELS[category].casefold()
            for category in section_order
            if any(claim["category"] == category for claim in claims)
        ]
        positions = [normalized.find(heading) for heading in headings]
        return all(position >= 0 for position in positions) and positions == sorted(positions)

    @staticmethod
    def _requirement_evidence_map(
        description: str, evidence: Sequence[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        requirements = extract_requirements(description)
        sections: Dict[str, List[str]] = {}
        for claim in evidence:
            sections.setdefault(str(claim.get("category") or "experience"), []).append(
                str(claim.get("text") or "")
            )
        structured = match_requirements(requirements, sections)
        result: List[Dict[str, Any]] = []
        for requirement in structured["requirements"]:
            requirement_text = str(requirement["text"])
            requirement_tokens = set(tokenize(requirement_text))
            matched_entities = set(requirement.get("matched_entities") or [])
            matches = []
            for claim in evidence:
                claim_text = str(claim.get("text") or "")
                overlap = requirement_tokens & set(tokenize(claim_text))
                entity_overlap = {
                    entity
                    for entity in matched_entities
                    if entity.casefold() in claim_text.casefold()
                }
                if overlap or entity_overlap:
                    matches.append((len(overlap) + 2 * len(entity_overlap), claim, overlap))
            matches.sort(key=lambda item: item[0], reverse=True)
            years_required = bool(
                re.search(
                    r"\b(?:\d+\s*[-–]\s*\d+|\d+\+?)\s+years?\b|years?\s+of\s+experience",
                    requirement_text,
                    flags=re.IGNORECASE,
                )
            )
            years_proven = any(
                re.search(
                    r"\b(?:\d+\s*[-–]\s*\d+|\d+\+?)\s+years?\b|years?\s+of\s+experience",
                    str(item[1].get("text") or ""),
                    flags=re.IGNORECASE,
                )
                for item in matches
            )
            if years_required and not years_proven:
                classification = "unsupported"
                matches = []
            else:
                classification = {
                    "direct": "direct",
                    "listed_only": "transferable",
                    "transferable": "transferable",
                    "unsupported": "unsupported",
                }[str(requirement["match_status"])]
            result.append(
                {
                    "requirement_id": requirement["id"],
                    "requirement": requirement_text,
                    "priority": requirement["priority"],
                    "category": requirement["category"],
                    "classification": classification,
                    "evidence_ids": [item[1]["id"] for item in matches[:4]],
                    "overlap_terms": sorted(matches[0][2]) if matches else [],
                    "best_field": requirement.get("best_field"),
                    "matched_entities": requirement.get("matched_entities") or [],
                    "demonstrated_entities": requirement.get("demonstrated_entities") or [],
                    "entity_coverage": requirement.get("entity_coverage"),
                    "lexical_coverage": requirement.get("lexical_coverage"),
                }
            )
        return result

    @staticmethod
    def _atomic_requirements(description: str) -> List[str]:
        normalized = re.sub(r"\s+", " ", description).strip()
        sentences = [
            sentence.strip(" -•\t")
            for sentence in re.split(r"(?<=[.!?;])\s+", normalized)
            if sentence.strip()
        ]
        markers = (
            "experience",
            "knowledge",
            "proficient",
            "ability",
            "responsible",
            "skill",
            "build",
            "design",
            "develop",
            "required",
            "preferred",
            "work with",
            "should have",
        )
        requirement_sentences = [
            sentence
            for sentence in sentences
            if any(marker in sentence.casefold() for marker in markers)
        ] or sentences[:10]

        prefix_pattern = re.compile(
            r"^(?P<prefix>"
            r"candidates?\s+should\s+have|"
            r"experience\s+(?:with|in)|"
            r"knowledge\s+of|proficient\s+in|ability\s+to|"
            r"responsible\s+for|work\s+with|"
            r"build|design|develop|create|maintain|use"
            r")\s+",
            flags=re.IGNORECASE,
        )
        atomic: List[str] = []
        for sentence in requirement_sentences:
            carry_prefix = ""
            for raw_segment in sentence.rstrip(".!?;").split(","):
                segment = raw_segment.strip()
                segment = re.sub(r"^and\s+", "", segment, flags=re.IGNORECASE)
                if not segment:
                    continue
                prefix_match = prefix_pattern.match(segment)
                if prefix_match:
                    carry_prefix = prefix_match.group("prefix")
                elif carry_prefix and len(tokenize(segment)) <= 4:
                    segment = f"{carry_prefix} {segment}"

                strong_split = re.match(
                    r"^(?P<first>.+?)\s+and\s+(?P<second>strong\s+.+)$",
                    segment,
                    flags=re.IGNORECASE,
                )
                if strong_split:
                    first = strong_split.group("first")
                    second = strong_split.group("second")
                    second_prefix = (
                        prefix_match.group("prefix")
                        if prefix_match
                        else carry_prefix
                    )
                    atomic.append(first)
                    atomic.append(f"{second_prefix} {second}".strip())
                else:
                    atomic.append(segment)

        unique_requirements: List[str] = []
        seen: set[str] = set()
        for requirement in atomic:
            cleaned = re.sub(r"\s+", " ", requirement).strip()
            key = cleaned.casefold()
            requirement_tokens = tokenize(cleaned)
            single_technology_requirement = (
                len(requirement_tokens) == 1
                and len(requirement_tokens[0]) >= 3
                and bool(
                    re.match(
                        r"^(?:work\s+with|proficient\s+in|knowledge\s+of|use)\s+",
                        cleaned,
                        flags=re.IGNORECASE,
                    )
                )
            )
            if (
                (len(requirement_tokens) < 2 and not single_technology_requirement)
                or key in seen
            ):
                continue
            seen.add(key)
            unique_requirements.append(cleaned)
        return unique_requirements[:18]

    @classmethod
    def _select_evidence(
        cls,
        job: Dict[str, Any],
        evidence: Sequence[Dict[str, Any]],
        interpretation: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        job_tokens = set(tokenize(job["title"] + " " + job["description"]))
        emphasis = " ".join(
            item.get("value", "")
            for item in interpretation
            if item.get("type") == "emphasis" and item.get("status") == "applied"
        )
        emphasis_tokens = set(tokenize(emphasis))
        exclusions = [
            item.get("value", "").casefold()
            for item in interpretation
            if item.get("type") == "exclude" and item.get("status") == "applied"
        ]
        eligible = [
            claim
            for claim in evidence
            if claim.get("category") in cls.RESUME_CATEGORIES
            and not any(
                value and value in str(claim.get("text") or "").casefold()
                for value in exclusions
            )
        ]
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for claim in eligible:
            grouped.setdefault(claim["category"], []).append(claim)
        for claims in grouped.values():
            claims.sort(key=cls._source_line)

        def relevance(claim: Dict[str, Any]) -> float:
            claim_tokens = set(tokenize(claim["text"]))
            score = len(job_tokens & claim_tokens) + 2 * len(
                emphasis_tokens & claim_tokens
            )
            if claim["category"] in {"experience", "projects"}:
                score += 1.5
            return score

        caps = {
            "summary": 1,
            "experience": 5,
            "projects": 8,
            "skills": 3,
            "achievements": 3,
            "education": 2,
            "certifications": 2,
            "volunteer": 3,
            "leadership": 3,
            "publications": 2,
            "languages": 2,
        }
        selected: List[Dict[str, Any]] = []
        for category in cls.DEFAULT_SECTION_ORDER:
            category_claims = grouped.get(category, [])
            if not category_claims:
                continue
            cap = caps[category]
            if category == "projects":
                chosen = cls._select_project_blocks(category_claims, relevance, cap)
            elif category == "experience":
                context = category_claims[:2]
                remaining = sorted(
                    category_claims[2:],
                    key=lambda claim: (-relevance(claim), cls._source_line(claim)),
                )
                chosen = (context + remaining[: max(0, cap - len(context))])[:cap]
            else:
                chosen = sorted(
                    category_claims,
                    key=lambda claim: (-relevance(claim), cls._source_line(claim)),
                )[:cap]
            if not chosen:
                chosen = [category_claims[0]]
            selected.extend(sorted(chosen, key=cls._source_line))
        return selected

    @classmethod
    def _select_project_blocks(
        cls,
        claims: Sequence[Dict[str, Any]],
        relevance: Any,
        cap: int,
    ) -> List[Dict[str, Any]]:
        anchor_indices = [
            index
            for index, claim in enumerate(claims)
            if cls._is_entry_heading("projects", claim["text"])
        ]
        if not anchor_indices:
            return sorted(
                claims,
                key=lambda claim: (-relevance(claim), cls._source_line(claim)),
            )[:cap]
        blocks: List[List[Dict[str, Any]]] = []
        for position, start in enumerate(anchor_indices):
            end = (
                anchor_indices[position + 1]
                if position + 1 < len(anchor_indices)
                else len(claims)
            )
            blocks.append(list(claims[start:end]))
        ranked = sorted(
            blocks,
            key=lambda block: (
                -sum(relevance(claim) for claim in block),
                cls._source_line(block[0]),
            ),
        )[:2]
        chosen: List[Dict[str, Any]] = []
        for block in ranked:
            anchor = block[0]
            rest = sorted(
                block[1:],
                key=lambda claim: (-relevance(claim), cls._source_line(claim)),
            )
            chosen.extend([anchor, *rest[:3]])
        return sorted(chosen[:cap], key=cls._source_line)

    @staticmethod
    def _source_line(claim: Dict[str, Any]) -> int:
        match = re.search(r"(\d+)", str(claim.get("source_location") or ""))
        return int(match.group(1)) if match else 10_000

    @staticmethod
    def _is_entry_heading(category: str, text: str) -> bool:
        lowered = text.casefold()
        if category == "projects":
            return bool(
                re.search(r"(?:github\.com/|gitlab\.com/|https?://)", lowered)
                or re.search(r"\s[—–-]\s", text)
            )
        if category == "experience":
            return bool(
                re.search(r"\b(?:19|20)\d{2}\b.*(?:present|current|\b(?:19|20)\d{2}\b)", lowered)
                or "|" in text
            )
        return False

    @classmethod
    def _trim_lowest_priority_claim(
        cls,
        claims: Sequence[Dict[str, Any]],
        required_sections: Sequence[str],
        job: Dict[str, Any],
        interpretation: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove one low-value detail without deleting a source section."""

        counts = {
            category: sum(claim["category"] == category for claim in claims)
            for category in cls.RESUME_CATEGORIES
        }
        job_tokens = set(tokenize(job["title"] + " " + job["description"]))
        emphasis_tokens = set(
            tokenize(
                " ".join(
                    str(item.get("value") or "")
                    for item in interpretation
                    if item.get("type") == "emphasis"
                    and item.get("status") == "applied"
                )
            )
        )
        candidates: List[Tuple[float, int]] = []
        for index, claim in enumerate(claims):
            category = claim["category"]
            minimum = 1 if category in required_sections else 0
            if counts.get(category, 0) <= minimum:
                continue
            heading = cls._is_entry_heading(category, claim["text"])
            if heading and any(
                other["category"] == category
                and not cls._is_entry_heading(category, other["text"])
                for other in claims
            ):
                continue
            tokens = set(tokenize(claim["text"]))
            relevance = len(tokens & job_tokens) + 2 * len(tokens & emphasis_tokens)
            continuity = 2 if category in {"summary", "education"} else 0
            candidates.append((relevance + continuity, index))
        if not candidates:
            return list(claims)
        _, remove_index = min(candidates, key=lambda item: (item[0], -item[1]))
        return [claim for index, claim in enumerate(claims) if index != remove_index]

    @classmethod
    def _build_markdown(
        cls,
        profile: Dict[str, Any],
        claims: Sequence[Dict[str, Any]],
        section_order: Optional[Sequence[str]] = None,
    ) -> str:
        identity = profile.get("identity", {})
        contact = " · ".join(
            value
            for value in (
                identity.get("email"),
                identity.get("phone"),
                *(identity.get("links") or [])[:2],
            )
            if value
        )
        sections: Dict[str, List[str]] = {}
        for claim in claims:
            sections.setdefault(claim["category"], []).append(claim["text"])
        lines = [f"# {identity.get('name') or 'Candidate'}", contact, ""]
        for key in section_order or cls.DEFAULT_SECTION_ORDER:
            if not sections.get(key):
                continue
            heading = cls.SECTION_LABELS[key]
            lines.extend([f"## {heading}"])
            if key == "summary":
                lines.extend(sections[key])
            else:
                lines.extend(f"- {value}" for value in sections[key])
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    @classmethod
    def _build_tex(
        cls,
        profile: Dict[str, Any],
        claims: Sequence[Dict[str, Any]],
        section_order: Optional[Sequence[str]] = None,
    ) -> str:
        identity = profile.get("identity", {})
        contact_parts: List[str] = []
        if identity.get("email"):
            email = cls._tex_escape(str(identity["email"]))
            contact_parts.append(f"\\href{{mailto:{email}}}{{{email}}}")
        if identity.get("phone"):
            contact_parts.append(cls._tex_escape(str(identity["phone"])))
        for link in (identity.get("links") or [])[:2]:
            safe_link = cls._tex_escape(str(link))
            contact_parts.append(f"\\href{{{safe_link}}}{{{safe_link}}}")

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for claim in claims:
            grouped.setdefault(claim["category"], []).append(claim)

        body: List[str] = [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[margin=0.58in]{geometry}",
            r"\usepackage{enumitem}",
            r"\usepackage{xcolor}",
            r"\usepackage{hyperref}",
            r"\usepackage{helvet}",
            r"\renewcommand{\familydefault}{\sfdefault}",
            r"\pagestyle{empty}",
            r"\setlength{\parindent}{0pt}",
            r"\setlength{\parskip}{0pt}",
            r"\definecolor{ResumeNavy}{HTML}{1F3864}",
            r"\definecolor{ResumeBlue}{HTML}{2F5496}",
            r"\definecolor{ResumeLink}{HTML}{1A5DAD}",
            r"\hypersetup{colorlinks=true,urlcolor=ResumeLink,linkcolor=ResumeBlue}",
            r"\newcommand{\resumesection}[1]{\vspace{4pt}{\color{ResumeBlue}\bfseries\uppercase{#1}}\par\vspace{1pt}{\color{ResumeBlue}\hrule}\vspace{2pt}}",
            r"\begin{document}",
            r"\begin{center}",
            "{\\color{ResumeNavy}\\fontsize{18}{20}\\selectfont\\bfseries "
            + cls._tex_escape(str(identity.get("name") or "Candidate"))
            + r"}\par",
            r"\vspace{2pt}",
            r"{\small " + r" \textbullet{} ".join(contact_parts) + r"}\par",
            r"\end{center}",
            r"\vspace{-3pt}",
        ]
        for category in section_order or cls.DEFAULT_SECTION_ORDER:
            items = grouped.get(category)
            if not items:
                continue
            body.append(
                f"\\resumesection{{{cls._tex_escape(cls.SECTION_LABELS[category])}}}"
            )
            if category == "summary":
                for item in items:
                    body.append(cls._tex_escape(str(item["text"])) + r"\par")
                continue
            if category in {"skills", "languages"}:
                for item in items:
                    label, separator, value = str(item["text"]).partition(":")
                    if separator and len(label) <= 40:
                        body.append(
                            r"{\small\textbf{"
                            + cls._tex_escape(label + ":")
                            + "} "
                            + cls._tex_escape(value.strip())
                            + r"}\par"
                        )
                    else:
                        body.append(
                            r"{\small "
                            + cls._tex_escape(str(item["text"]))
                            + r"}\par"
                        )
                continue
            if category in {"education", "certifications", "publications"}:
                for index, item in enumerate(items):
                    command = r"\textbf" if index == 0 else r"\textit"
                    body.append(
                        command
                        + "{"
                        + cls._tex_escape(str(item["text"]))
                        + r"}\par"
                    )
                continue

            list_open = False
            for item in items:
                text = str(item["text"])
                is_heading = cls._is_entry_heading(category, text)
                if is_heading or cls._looks_like_technology_line(text):
                    if list_open:
                        body.append(r"\end{itemize}")
                        list_open = False
                    command = r"\textbf" if is_heading else r"\textit"
                    rendered = command + "{" + cls._tex_escape(text) + "}"
                    if is_heading and len(text) > 95:
                        rendered = r"{\small " + rendered + "}"
                    body.append(rendered + r"\par")
                    continue
                if not list_open:
                    body.append(
                        r"\begin{itemize}[leftmargin=13pt,itemsep=1pt,topsep=1pt,parsep=0pt]"
                    )
                    list_open = True
                body.append("\\item " + cls._tex_escape(text))
            if list_open:
                body.append(r"\end{itemize}")
        body.extend([r"\end{document}", ""])
        return "\n".join(body)

    @staticmethod
    def _tex_escape(value: str) -> str:
        replacements = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        return "".join(replacements.get(character, character) for character in value)

    @staticmethod
    def _looks_like_technology_line(text: str) -> bool:
        return (
            text.count("·") >= 1
            and len(text) <= 220
            and not re.search(r"[.!?]$", text)
        )

    @staticmethod
    def _compile_tex(source_path: Path, output_path: Path) -> bool:
        executable = shutil.which("tectonic")
        if not executable:
            return False
        with tempfile.TemporaryDirectory(
            prefix=".carivyo-tex-", dir=source_path.parent
        ) as temporary:
            temporary_path = Path(temporary)
            result = subprocess.run(
                [
                    executable,
                    "--untrusted",
                    "--outdir",
                    str(temporary_path),
                    str(source_path),
                ],
                cwd=str(source_path.parent),
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            compiled = temporary_path / f"{source_path.stem}.pdf"
            if result.returncode != 0 or not compiled.is_file():
                detail = " ".join((result.stderr or result.stdout).split())[-800:]
                raise ResumeRunBlocked(
                    "TeX compilation failed" + (f": {detail}" if detail else "")
                )
            shutil.copyfile(compiled, output_path)
        output_path.chmod(0o600)
        return True

    @staticmethod
    def _cleanup_superseded_variants(workspace: Path, current_variant: int) -> None:
        keep_stem = f"resume{current_variant}"
        for directory in (workspace / "variants", workspace / "renders"):
            if not directory.is_dir():
                continue
            for path in directory.glob("resume*.*"):
                if path.stem != keep_stem and path.is_file() and not path.is_symlink():
                    path.unlink(missing_ok=True)

    @staticmethod
    def _discard_variant(workspace: Path, variant: int) -> None:
        stem = f"resume{variant}"
        for directory in (workspace / "variants", workspace / "renders"):
            if not directory.is_dir():
                continue
            for path in directory.glob(f"{stem}.*"):
                if path.is_file() and not path.is_symlink():
                    path.unlink(missing_ok=True)

    @classmethod
    def _build_pdf(
        cls,
        profile: Dict[str, Any],
        claims: Sequence[Dict[str, Any]],
        output_path: Path,
        section_order: Optional[Sequence[str]] = None,
    ) -> None:
        styles = getSampleStyleSheet()
        name_style = ParagraphStyle(
            "Name",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=21,
            textColor=colors.HexColor("#172033"),
            alignment=TA_LEFT,
            spaceAfter=3,
        )
        contact_style = ParagraphStyle(
            "Contact",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.7,
            leading=11,
            textColor=colors.HexColor("#475467"),
            spaceAfter=7,
        )
        heading_style = ParagraphStyle(
            "Heading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#3547B8"),
            borderColor=colors.HexColor("#CDD5EA"),
            borderWidth=0,
            borderPadding=0,
            spaceBefore=5,
            spaceAfter=2,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.7,
            leading=11.2,
            textColor=colors.HexColor("#172033"),
            spaceAfter=1.5,
        )
        entry_style = ParagraphStyle(
            "Entry",
            parent=body_style,
            fontName="Helvetica-Bold",
            spaceBefore=1.5,
            spaceAfter=0.5,
        )
        meta_style = ParagraphStyle(
            "Meta",
            parent=body_style,
            fontName="Helvetica-Oblique",
            textColor=colors.HexColor("#475467"),
            spaceAfter=0.8,
        )
        document = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=0.48 * inch,
            leftMargin=0.48 * inch,
            topMargin=0.42 * inch,
            bottomMargin=0.42 * inch,
            title=f"{profile.get('identity', {}).get('name', 'Candidate')} Resume",
            author=profile.get("identity", {}).get("name", "Candidate"),
        )
        identity = profile.get("identity", {})
        story: List[Any] = [
            Paragraph(html.escape(identity.get("name") or "Candidate"), name_style)
        ]
        contact_parts = []
        if identity.get("email"):
            email = html.escape(identity["email"])
            contact_parts.append(f'<a href="mailto:{email}">{email}</a>')
        if identity.get("phone"):
            contact_parts.append(html.escape(identity["phone"]))
        for link in (identity.get("links") or [])[:2]:
            safe_link = html.escape(link, quote=True)
            contact_parts.append(f'<a href="{safe_link}">{html.escape(link)}</a>')
        story.append(Paragraph(" &nbsp;·&nbsp; ".join(contact_parts), contact_style))

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for claim in claims:
            grouped.setdefault(claim["category"], []).append(claim)
        for category in section_order or cls.DEFAULT_SECTION_ORDER:
            items = grouped.get(category)
            if not items:
                continue
            heading = cls.SECTION_LABELS[category].upper()
            story.append(Paragraph(heading, heading_style))
            if category == "summary":
                for item in items:
                    story.append(Paragraph(html.escape(item["text"]), body_style))
                continue
            if category in {"skills", "languages"}:
                for item in items:
                    label, separator, value = str(item["text"]).partition(":")
                    markup = (
                        f"<b>{html.escape(label + ':')}</b> {html.escape(value.strip())}"
                        if separator and len(label) <= 40
                        else html.escape(str(item["text"]))
                    )
                    story.append(Paragraph(markup, body_style))
                continue
            if category in {"education", "certifications", "publications"}:
                for index, item in enumerate(items):
                    story.append(
                        Paragraph(
                            html.escape(str(item["text"])),
                            entry_style if index == 0 else meta_style,
                        )
                    )
                continue
            for item in items:
                text = str(item["text"])
                if cls._is_entry_heading(category, text):
                    story.append(Paragraph(html.escape(text), entry_style))
                elif cls._looks_like_technology_line(text):
                    story.append(Paragraph(html.escape(text), meta_style))
                else:
                    story.append(
                        ListFlowable(
                            [
                                ListItem(
                                    Paragraph(html.escape(text), body_style),
                                    leftIndent=9,
                                )
                            ],
                            bulletType="bullet",
                            start="circle",
                            leftIndent=13,
                            bulletFontSize=5,
                            spaceAfter=0.5,
                        )
                    )
        document.build(story)
        output_path.chmod(0o600)

    @staticmethod
    def _render_pdf(
        pdf_path: Path, render_directory: Path, variant_number: int
    ) -> Optional[Path]:
        pages = ResumeService._render_pdf_pages(
            pdf_path,
            render_directory,
            variant_number,
            len(PdfReader(str(pdf_path)).pages),
        )
        return pages[0] if pages else None

    @staticmethod
    def _render_pdf_pages(
        pdf_path: Path,
        render_directory: Path,
        variant_number: int,
        page_count: int,
    ) -> List[Path]:
        executable = shutil.which("pdftoppm")
        if not executable:
            return []
        outputs: List[Path] = []
        for page_number in range(1, max(1, page_count) + 1):
            stem = (
                f"resume{variant_number}"
                if page_number == 1
                else f"resume{variant_number}-page{page_number}"
            )
            prefix = render_directory / stem
            result = subprocess.run(
                [
                    executable,
                    "-png",
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-singlefile",
                    "-r",
                    "144",
                    str(pdf_path),
                    str(prefix),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            output = prefix.with_suffix(".png")
            if result.returncode != 0 or not output.exists():
                return []
            output.chmod(0o600)
            outputs.append(output)
        return outputs

    @staticmethod
    def _validate_render(render_path: Optional[Path]) -> Tuple[bool, Dict[str, Any]]:
        """Run deterministic raster checks before exposing a generated resume.

        This is deliberately a conservative machine gate, not a claim that a human
        inspected the page. It detects missing/corrupt renders, blank pages, content
        touching the raster edge (a clipping signal), and implausibly dense output.
        """

        details: Dict[str, Any] = {
            "method": "deterministic_raster_v1",
            "human_inspected": False,
        }
        if not render_path or not render_path.is_file():
            return False, {**details, "reason": "render_missing"}
        try:
            with Image.open(render_path) as source:
                image = source.convert("L")
        except (OSError, UnidentifiedImageError):
            return False, {**details, "reason": "render_unreadable"}

        width, height = image.size
        details.update({"width": width, "height": height})
        if width < 600 or height < 800 or height <= width:
            return False, {**details, "reason": "unexpected_page_geometry"}

        background = Image.new("L", image.size, 255)
        ink = ImageChops.difference(background, image)
        # Ignore anti-aliasing noise that is visually indistinguishable from white.
        ink = ink.point(lambda value: 255 if value >= 12 else 0)
        bbox = ink.getbbox()
        if bbox is None:
            return False, {**details, "reason": "blank_page"}

        nonwhite_ratio = round(ImageStat.Stat(ink).mean[0] / 255, 4)
        left, top, right, bottom = bbox
        edge_clearance = min(left, top, width - right, height - bottom)
        details.update(
            {
                "content_bbox": [left, top, right, bottom],
                "nonwhite_ratio": nonwhite_ratio,
                "edge_clearance_px": edge_clearance,
            }
        )
        if edge_clearance < 2:
            return False, {**details, "reason": "possible_edge_clipping"}
        if nonwhite_ratio < 0.002:
            return False, {**details, "reason": "insufficient_visible_content"}
        if nonwhite_ratio > 0.42:
            return False, {**details, "reason": "implausible_page_density"}
        return True, {**details, "reason": "passed_machine_checks"}

    @staticmethod
    def _normalize_claim(value: str) -> str:
        return re.sub(r"\W+", "", value.casefold())

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        path.chmod(0o600)
