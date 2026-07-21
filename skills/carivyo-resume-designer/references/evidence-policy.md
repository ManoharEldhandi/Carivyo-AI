# Evidence and Resume Policy

## Context Isolation

The run package is the complete candidate truth boundary. Accept candidate
facts only when they appear as approved evidence in `run-spec.json`.

Never use:

- Ambient chat history unless copied into approved run evidence.
- A different user's files, profile, resume skill, or generated variant.
- Home-directory searches or files not named by the run specification.
- Job descriptions, company pages, or recruiter language as candidate proof.
- Model memory or plausible inference.

## Evidence Priority

Resolve conflicts narrowly:

1. Current explicit user correction or approval.
2. Approved evidence claims in the current run.
3. Exact claims in the selected approved base.
4. Other approved current-run source artifacts.
5. General writing or ATS advice.

If the correction is not yet represented as approved evidence, stop and ask
the product to update the evidence ledger before generation.

## Allowed Transformations

- Exact reuse.
- Reordering.
- Shortening that preserves agency, scope, causality, tense, and metrics.
- Combining statements only when they share the same source and do not strengthen the claim.
- Adding exact JD terminology when approved evidence proves the same concept.
- Removing irrelevant or duplicate content.

## Prohibited Transformations

- Inventing or increasing metrics, users, scale, revenue, accuracy, latency, ownership, leadership, years, dates, education, or certifications.
- Turning exposure, coursework, prototypes, or internal demos into production experience.
- Changing `assisted`, `supported`, or `contributed` into `led`, `owned`, or `architected`.
- Moving a project result into employment experience.
- Adding keywords that the user cannot defend.
- Hiding keywords in metadata, white text, headers, or inaccessible content.
- Concealing mandatory gaps.
- Merging claims from different candidates, users, profiles, or run workspaces.
- Using an unapproved source because it appears more recent or complete.

When evidence conflicts, use the narrower claim and surface the conflict.

## Default Document Policy

- Preserve the selected base resume's design unless the user requests a new template or a verified defect requires change.
- Prefer a single-column ATS-safe structure with ordinary headings and visible links.
- Default to one page for students and early-career candidates; allow two pages when experience and evidence justify it.
- Avoid tables, sidebars, text boxes, photos, charts, unusual bullets, and header/footer-only contact information.
- Keep reverse chronology, consistent dates, readable type, and visible whitespace.
- Preserve extracted-text reading order.

## Change Budget

For tailoring an existing base:

- Aim for 15% or less extracted-text change.
- Require a new run or explicit exception above 25%.
- Prefer reordering and selection before rewriting.
- Allow one main generation and up to three focused instruction or TeX
  revisions. Start a new run after the fourth current variant.

For first-time resume creation, the change budget does not apply, but every statement still requires evidence.

## Validation

A ready artifact must have:

- Successful export and readable page count.
- Correct text extraction and section order.
- Working visible links.
- Consistent identity, dates, and contact details.
- No unsupported or misleading claims.
- No clipping, overlap, broken glyphs, or excessive empty space.
- A recorded relationship between the exact JD, source evidence, editable source, and exported PDF.
- Requirement and ATS coverage calculated from the exact final extracted PDF,
  not unused profile evidence or claims removed during page fitting.
- Matching hashes for the frozen JD, PDF bytes, extracted text, analyzer
  version, and machine-readable ATS report.
- An isolated workspace and matching provenance hashes.
- A machine-readable validation report with no failed critical gate.

## Custom Instructions

Accept natural-language requests about emphasis, tone, ordering, project
selection, template, length, or content exclusions. Convert them into
structured directives and show the interpretation.

Custom instructions cannot override evidence, privacy, safety, or deterministic
validation.

Manual TeX edits may change presentation, spacing, and other safe document
source. Factual wording changes must still pass the approved-evidence gate;
unsafe TeX file/shell primitives are always rejected.
