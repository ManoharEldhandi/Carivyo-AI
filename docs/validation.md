# Carivyo Validation Evidence

Validation date: 2026-07-22

Scope: local-first single-user responsive website

## Automated regression and build

```bash
make check
```

Observed final results:

- Backend: 136 tests passed.
- Frontend: 35 tests passed across 9 files.
- Frontend production build: 315.32 kB JavaScript (91.57 kB gzip) and
  88.25 kB CSS (19.75 kB gzip).
- Python dependency consistency: no broken requirements.
- `pip-audit`: no known vulnerabilities in installed dependencies; the local
  editable `carivyo` package is not a PyPI package and is therefore skipped.
- Production `npm audit`: 0 known vulnerabilities.
- `git diff --check`: passed.
- General resume-skill contract validator: passed for both real-browser resume
  run workspaces, including artifact hashes, 27-check binding, evidence scope,
  and approval provenance.
- One-command launcher smoke: the bare `http://127.0.0.1:5173/` route exchanged
  the current ephemeral token, loaded the existing local profile and Jobs page,
  returned HTTP 200 from `/api/jobs`, emitted no browser errors, applied the
  legacy-plan compatibility normalization, and released both ports on shutdown.

The tests cover reviewed onboarding, profile rollover, typed preference
interpretation, temporary overrides, strict eligibility gates, contextual
exclusions, Remote India classification, UTC/freshness semantics,
deduplication, source completeness, SmartRecruiters pagination/detail fanout,
stale preview and semantic-review binding, deterministic ATS behavior,
filename-sensitive checks, resume revision/approval integrity, exact
run/variant/PDF application association, external ATS consent binding and
recursive secret redaction, revision rollback, truthful TeX fallback behavior,
popup failure handling, chat persistence, runtime/model
selection, privacy operations, modal focus, and accessibility smoke checks.

## Real-browser critical journey

An isolated backend (`127.0.0.1:8422`) and frontend (`127.0.0.1:5175`) used a
clean temporary data directory and realistic fixtures. The journey completed:

1. Imported `backend/tests/fixtures/resume.txt`.
2. Reviewed the extracted candidate profile before activation.
3. Answered five natural-language questions for Backend first, AI/LLM second;
   Bengaluru, Hyderabad, and Remote India only; remote/hybrid/onsite modes;
   fresher through two years; and explicit role exclusions.
4. Saved the profile and ran the strict 48-hour search.
5. Received only three eligible fixture roles: Backend Software Engineer in
   Bengaluru, Software Engineer I in Hyderabad, and AI/LLM Engineer in Remote
   India. An unrelated role and all out-of-scope locations were excluded.
6. Inspected direct/transferable/missing match evidence and source/freshness
   provenance.
7. Explicitly opened Resume Studio and supplied custom evidence-constrained
   instructions.
8. Generated the resume, reviewed separate submission compatibility, evidence
   alignment, and content-quality results, and saw all unsupported requirements.
9. Edited the generated TeX in Resume Studio, changed only the A4 page margin,
   recompiled it in Tectonic untrusted mode, and confirmed that draft 2 replaced
   all superseded generated variant files while retaining the immutable base.
10. Switched between Local and Enhancv ATS views. The Local report stayed the
    approval authority; the external action remained disabled until explicit
    consent. A separate authorized live adapter check completed successfully.
11. Closed, refreshed, and reopened Resume Studio; the approved draft 2 and its
    exact artifacts restored without regeneration. “New version” remained a
    separate explicit action.
12. Downloaded and visually inspected the one-page PDF and TeX. `pdfinfo` confirmed one
   page and no scripts; `pdftotext` extracted the complete resume in reading
   order; a Poppler render showed no clipping, overlap, broken glyphs, or
   unreadable content.
13. Approved the exact current variant and opened the official application in
    a reserved new tab. The fixture URL intentionally did not resolve, while
    SQLite still confirmed that the local application retained the approved
    resume-run association and recorded only `opened`, never `submitted`.
14. Downloaded and validated the full backup ZIP and profile JSON export;
    confirmed that delete is explicit and AI chat starts disabled.

Screenshots:

- `output/playwright/carivyo-tex-final.pdf`
- `output/playwright/carivyo-tex-final.tex`
- `output/playwright/resume-studio-desktop-tex.png`
- `output/playwright/resume-studio-mobile-tex.png`

## Accessibility and browser behavior

- Desktop and 390 x 844 mobile layouts were visually inspected.
- Resume Studio initially exposed one serious axe finding: its scrollable
  preview lacked keyboard access. The preview is now a named focusable region.
- Tailoring initially removed the focused action and left focus on the body.
  The completed state now moves focus to the dialog close control.
- The final axe run on the populated mobile Resume Studio state reported zero
  WCAG A/AA, WCAG 2.1 AA, or WCAG 2.2 AA violations.
- Modal Escape, focus trap, and focus return have automated tests.
- The browser reported zero console errors. The only warning was produced by
  a deliberately blocked inline axe injection during a CSP diagnostic; a fresh
  browser session reported zero product errors and zero warnings.

This is not a full assistive-technology or WCAG certification. A screen-reader
matrix, browser zoom/reflow campaign, and manual color measurements across all
states remain release work.

## Performance observations

On the populated local development page:

- DOMContentLoaded: 440 ms.
- Load completion: 457 ms.
- Resource requests: 57.
- Transferred resource bytes: approximately 908 kB, including development
  assets and fonts.
- Browser-reported long tasks: 0 (the entry API itself emitted a deprecation
  warning, so this value is supporting evidence only).

The populated 80-job endpoint probe ran 30 sequential reads at 73.75 ms p50,
113.17 ms p95, and 130.98 ms maximum with a 168,797-byte response. Backend
performance tests are included in the passing 136-test suite. These
measurements are local-machine observations, not low-end-device, endurance, or
internet-deployment benchmarks.

## Live official-source contract check

Run the bounded read-only diagnostic with:

```bash
.venv/bin/python scripts/verify_live_sources.py
```

The 2026-07-21 UTC run passed all four representative source families with no
invalid accepted candidate:

| Source | Accepted | Posting evidence | Complete |
| --- | ---: | ---: | --- |
| Greenhouse / PhonePe | 53 | 53 | yes |
| Lever / Binance | 273 | 273 | yes |
| Ashby / OpenAI | 723 | 723 | yes |
| SmartRecruiters / Bosch | 5 detail-verified | 5 | no - detail limit reached |

SmartRecruiters fetched all 113 summaries across two pages, then deliberately
verified only five details for this bounded live diagnostic. It returned
`complete=false` with `detail_limit_reached`; this is the intended truthful
behavior, not a pass for exhaustive board coverage. Live counts will change and
are not product guarantees.

## ATS benchmark

```bash
.venv/bin/python scripts/benchmark_ats.py
```

Anonymized PDF benchmark v2 contains 100 reproducible resume/JD pairs. Results:

- Analyzer: `carivyo-ats-2.0.0`.
- Repeatability: 1.0.
- Labeled issue precision: 1.0.
- Labeled issue recall: 0.9857.
- Actual PDF artifacts: 100 across 10 role families.
- False positives: 0; false negatives: 2, both published in
  `docs/ats-benchmark-v2.md`.
- Vendor agreement: `null`.

The corpus covers 800 labeled check outcomes and does not establish applicant-
population accuracy. No premium-provider score or private report is
committed, and no 98% parity claim is made. The required authorized anonymized
corpus and agreement metric are defined in `docs/ats-methodology.md`.

## Security evidence

- Loopback API, ephemeral launch-token exchange, random session token, origin checks, per-route rate limits,
  strict file validation, subprocess isolation, URL allowlists, DNS/IP checks,
  redirect/size/time bounds, prompt/content separation, and redacted logs are
  covered by code and focused tests.
- `pip-audit` and production `npm audit` found no known vulnerabilities.
- Bandit found no high-severity issue. Five medium SQL warnings were reviewed:
  one interpolates only a fixed internal table allowlist, and four construct
  only placeholder counts while binding every value. Low warnings describe
  intentional `shell=False` allowlisted subprocesses and public Greenhouse
  board identifiers named `board_token`; they are not credentials.
- Response headers include a restrictive content-security policy,
  `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a restrictive
  `Permissions-Policy`, and `Cache-Control: no-store`.

The remaining local encryption, multi-user isolation, and deployment risks are
listed in `docs/readiness.md`.
