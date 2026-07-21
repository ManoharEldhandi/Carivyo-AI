# Resume Quality Gates

## Critical deterministic gates

Every gate below must pass before `needs_user_review`:

| Gate | Required evidence |
| --- | --- |
| Workspace isolation | Every declared input and output resolves inside the run directory |
| Provenance | JD, profile snapshot, evidence, base, instructions, template, and skill hashes are recorded |
| Export | Editable source and non-empty PDF exist |
| TeX safety | An editable source compiled the current PDF in untrusted mode and contains no blocked file/shell primitives; fallback runs are labeled non-editable |
| Page limit | Generated page count matches the interpreted length directive |
| Text extraction | PDF text is readable and ordered |
| Identity | Approved name and available contact fields are unchanged |
| Evidence | Every generated factual claim maps to approved evidence |
| Links | Visible approved links are valid and present in the PDF |
| Sections | Recognized headings appear in intended order |
| Visual | A deterministic raster gate confirms readable page geometry, visible content, safe edge clearance, and plausible density; the product still labels human inspection separately |
| Change budget | Tailor mode is at or below 25%; above 15% is visibly flagged |
| First-party ATS analysis | Exactly 27 versioned checks analyze the final extracted PDF against the frozen JD |
| Artifact binding | JD, PDF, extracted text, analyzer report, and ruleset hashes match |
| Approval | Generation ends at `needs_user_review` |

## Review gates

Review these after deterministic validation:

- The first 20-second scan communicates role direction and strongest proof.
- Direct requirements are supported by specific evidence.
- Transferable evidence is not presented as exact experience.
- Unsupported requirements remain visible as gaps.
- Seniority, ownership verbs, dates, and metrics are credible.
- Repetition is removed without erasing important scope.
- The document remains natural and readable rather than keyword-stuffed.
- Interview probes are answerable from the approved evidence.

## Failure behavior

- Block on evidence, identity, path, export, extraction, or approval failures.
- Block when the document cannot be rendered for visual verification.
- Block approval when artifact or analysis hashes no longer match.
- Ask for focused user direction on conflicting evidence or unsafe instructions.
- Start a new run when a revision would exceed the default variant or change budget.
- Never downgrade a failed gate to a warning merely to produce an artifact.
