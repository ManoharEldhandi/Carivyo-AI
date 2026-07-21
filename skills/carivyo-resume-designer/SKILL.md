---
name: carivyo-resume-designer
description: Create, tailor, audit, revise, and validate truthful job-specific resumes from an isolated run package containing a frozen job description, approved evidence, base resumes, and optional instructions. Use only after explicit resume-design intent. Never use ambient chat history, unrelated skills, hidden personal context, or the wider filesystem as candidate evidence.
---

# Carivyo Resume Designer

## Boundary

Create the strongest defensible resume for one selected job. Preserve the
candidate's evidence, voice, and strongest existing material.

- Run only after explicit resume-design intent.
- Treat the job description as employer evidence, never candidate evidence.
- Read candidate facts only from the run package.
- Never import facts from ambient conversation, another skill, a developer
  profile, home-directory files, previous users, or model memory.
- Never overwrite source resumes or silently approve a generated artifact.

## Read Before Acting

Read these files completely:

- `references/evidence-policy.md`
- `references/run-contract.md`
- `references/quality-gates.md`

Then read only the paths named by `inputs/run-spec.json`. Reject paths outside
the run workspace. Do not browse the candidate's broader artifact vault.

## Modes

- `tailor`: adapt the best editable base with a small change budget.
- `build`: create from approved evidence when no base can be safely edited.
- `audit`: report fit, truth, parsing, links, and layout without changing content.
- `revise`: patch one existing variant from focused user feedback.

## Workflow

### 1. Validate and freeze

Validate the run contract before generation. Record hashes for the JD,
evidence package, selected base, instructions, template, and skill version.
Keep source inputs immutable.

### 2. Map requirements to evidence

Classify each material requirement:

- `direct`: explicitly supported.
- `transferable`: defensibly related but not exact.
- `unsupported`: no approved evidence.
- `unclear`: conflicting or insufficient evidence.

Attach approved evidence IDs to `direct` and `transferable` items. Keep
unsupported and unclear requirements visible. Never transform a gap into a
candidate claim.

### 3. Select the Base

Score metadata and evidence coverage before opening sources. Prefer the base
with the strongest responsibility coverage, appropriate track/seniority,
sound parsing, and smallest safe change requirement. Record the selection
score and rationale.

If no base is safely editable, use `build` with an ATS-safe template and state
that the original layout was not preserved.

### 4. Interpret Custom Instructions

Compile natural language into structured directives: emphasis, exclusions,
project selection, section order, tone, length, or template.

Mark each directive `applied`, `blocked`, or `rejected` with a reason. Reject
fabrication, hidden keywords, inflated seniority, false metrics, misleading
dates, or inaccessible formatting.

### 5. Plan Minimal Changes

Plan `keep`, `move`, `shorten`, `replace`, `remove`, and `add` operations.
Every content change must cite evidence IDs and solve a named relevance,
truth, clarity, parsing, or layout issue.

Generate one main candidate. Allow focused instruction or TeX revisions within
the four-version safety budget. Keep only the current successful variant in the
working artifact set; never delete or overwrite the imported base resume.

### 6. Generate deterministically where possible

Use structured evidence selection, fixed templates, and deterministic
validators before involving a model. If a model improves wording, pass only
the bounded requirement-evidence map and approved claims; revalidate every
output claim.

Create an A4, single-column TeX design source. When Tectonic is available,
compile the exact source in untrusted mode and allow formatting-only editing.
If an independent PDF fallback is required, label its provenance and disable
TeX editing for that run. Reject file, shell, or dynamic input primitives.
Re-extract the final PDF and recompute
requirement coverage from content that is actually present; never credit a
claim merely because it existed in the broader run evidence package.

Render the final PDF and run deterministic raster checks for page geometry,
blank output, edge clipping signals, and implausible density. Label this as a
machine check; do not imply that a human reviewed overlap, typography, or visual
quality until the user actually inspects the preview.

Run Carivyo's first-party ATS analyzer against the exact extracted PDF and the
frozen JD. It applies 27 deterministic checks across seven categories and
returns transparent weights, evidence, and fixes. It requires no subscription
and must not claim to reproduce any third-party proprietary score. Treat the
score as diagnostic: there is no universal ATS score.

When the user explicitly selects Enhancv and confirms external processing, the
orchestrator may send only the exact current PDF and frozen JD through the
configured authorized adapter. Keep the local analysis authoritative for
Carivyo approval. Do not expose credentials, preserve third-party browser
artifacts, or claim parity between the two scores.

Then apply every gate in
`references/quality-gates.md`. Run:

```bash
python scripts/validate_run.py /absolute/path/to/resume-runs/<run-id>
```

Never trade truth, readability, or protected-trait safety for a score. Never
infer age or another protected characteristic; only report optional sensitive
data that is visibly present in the final resume.

### 7. Review and hand off

Review the 20-second scan, responsibility coverage, technical proof,
seniority fit, credibility risks, and likely interview probes. Patch only
material issues.

Return the selected base and rationale, fit/gap summary, interpreted
instructions, meaningful diff, validation results, remaining risks, and
artifact paths.

Set `needs_user_review` after successful generation. Only an explicit product
approval action may set `ready_to_apply`.

## Token Discipline

- Use requirement summaries, evidence IDs, and hashes instead of replaying raw
  documents.
- Load all selected-base claims only when needed for change comparison; load
  other evidence by job relevance.
- Cache base analysis and requirement maps by content hash.
- Send patches for revision, not the entire workspace.
- Never call a model for export, hashing, path checks, page counts, links,
  diffing, or evidence validation.

## Stop Gates

Stop with a specific reason when:

- A mandatory claim needs unsupported evidence.
- Sources conflict on a material fact.
- An instruction would make the resume misleading.
- The selected template cannot produce a readable result.
- Tailoring would materially replace the candidate's career story.
- Validation cannot confirm a usable document.
- The final PDF, extracted text, JD, or ATS report hash differs from the
  artifact that was analyzed.

Use no network by default. The sole ATS exception is an explicit, consented
Enhancv adapter invocation controlled by the application. Follow the run's
network policy exactly. Never
store credentials, unrelated personal context, or raw model prompts in the run
artifacts.
