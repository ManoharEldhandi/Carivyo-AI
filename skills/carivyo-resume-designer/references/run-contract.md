# Resume Run Contract

## Inputs

The orchestrator must provide an isolated immutable package:

```json
{
  "run_id": "uuid",
  "job_snapshot": {
    "job_id": "uuid",
    "company": "string",
    "title": "string",
    "description_path": "absolute-path",
    "source_url": "url",
    "snapshot_hash": "sha256"
  },
  "profile_version": "string",
  "profile_snapshot": {
    "version": "string",
    "profile": {},
    "capsule": "string",
    "hash": "sha256"
  },
  "context_policy": {
    "scope": "run_only",
    "ambient_context_allowed": false,
    "external_files_allowed": false
  },
  "evidence_claims": [
    {
      "id": "claim-id",
      "artifact_id": "source-artifact-id",
      "category": "experience|projects|skills|...",
      "text": "approved fact",
      "source": "artifact and location",
      "approval": "approved"
    }
  ],
  "base_resumes": [
    {
      "id": "resume-id",
      "artifact_id": "source-artifact-id",
      "track": "string",
      "source_path": "absolute-path",
      "text_path": "absolute-path",
      "hash": "sha256",
      "text_hash": "sha256"
    }
  ],
  "custom_instructions": "string",
  "output_directory": "absolute-path",
  "network_policy": "none|company_only|ats_allowed",
  "skill_version": "semver",
  "template": {
    "id": "string",
    "hash": "sha256"
  }
}
```

Reject the run when a required path escapes the workspace, evidence is not
approved, context scope is not `run_only`, ambient context is allowed, or a
required hash is missing.

## Required Artifacts

```text
resume-runs/{run_id}/
  inputs/
    job-description.txt
    run-spec.json
    revision-N.json        # current focused instruction or TeX revision only
    reference-base.*
  reviews/
    requirement-evidence-map.json
    change-plan.json
    hiring-review.json
  variants/
    resumeN.tex            # current successful variant
    resumeN.pdf
  renders/
  reports/
    validation.json
    ats-analysis.json
  result.json
```

Delete superseded generated variant files after the replacement passes every
gate. Preserve the immutable base resume, current revision provenance, exact
current TeX/PDF/render, and current reports.

## Result Schema

Write `result.json` with:

```json
{
  "status": "needs_user_review|ready_to_apply|blocked|failed",
  "selected_base_resume_id": "resume-id",
  "base_selection": {
    "score": 0,
    "rationale": ["string"]
  },
  "mode": "tailor|build|audit|revise",
  "custom_instruction_interpretation": [],
  "coverage": {
    "direct": [],
    "transferable": [],
    "unsupported": [],
    "unclear": []
  },
  "changes": [
    {
      "type": "move|shorten|replace|remove|add",
      "before": "string",
      "after": "string",
      "evidence_ids": ["claim-id"],
      "reason": "string"
    }
  ],
  "validation": {
    "export_ok": true,
    "page_count": 1,
    "text_extraction_ok": true,
    "links_ok": true,
    "section_order_ok": true,
    "section_completeness_ok": true,
    "section_inventory": [],
    "visual_ok": true,
    "visual_details": {
      "method": "deterministic_raster_v1",
      "human_inspected": false,
      "reason": "passed_machine_checks"
    },
    "evidence_ok": true,
    "change_percent": 12.5
  },
  "provenance": {
    "job_snapshot_hash": "sha256",
    "profile_snapshot_hash": "sha256",
    "evidence_hash": "sha256",
    "base_resume_hash": "sha256",
    "custom_instructions_hash": "sha256",
    "template_hash": "sha256",
    "skill_version": "semver",
    "pdf_hash": "sha256",
    "extracted_text_hash": "sha256",
    "ats_analysis_hash": "sha256"
  },
  "ats_analysis": {
    "analyzer_version": "semver",
    "assessment": {
      "status": "strong|review|needs_focus|blocked|insufficient_data",
      "compatibility": {},
      "evidence_alignment": {},
      "content_quality": {},
      "legacy_score_deprecated": true
    },
    "jd_quality": {"status": "complete", "confidence": "high|medium"},
    "structured_alignment": {"requirements": []},
    "parse_rate": 0,
    "checks": [],
    "critical_failures": [],
    "disclaimer": "string"
  },
  "hiring_evaluation": {
    "status": "complete|unavailable|failed|disabled",
    "provider": "ollama",
    "advisory": true,
    "score_basis": "independent dimension-specific evidence baselines plus local judgment",
    "authoritative": false,
    "dimensions": []
  },
  "approval": {
    "required": true,
    "user_approved": false
  },
  "remaining_gaps": [],
  "interview_probes": [],
  "artifacts": {
    "pdf": "absolute-path",
    "editable_source": "absolute-path",
    "render": "absolute-path",
    "render_pages": ["absolute-path-for-every-page"],
    "validation_report": "absolute-path",
    "ats_report": "absolute-path"
  }
}
```

Only an explicit product approval action may change `needs_user_review` to
`ready_to_apply`, and it must also set `approval.user_approved` to `true`.

## Contract Validation

Run `scripts/validate_run.py` against the run directory. A non-zero exit means
the artifact cannot be offered for approval.
