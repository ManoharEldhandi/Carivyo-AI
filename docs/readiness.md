# Carivyo Readiness Assessment

Assessment date: 2026-07-22

## Verdict

**Local single-user website: PASS WITH LIMITATIONS. Hosted or general
production deployment: NOT YET READY.**

The critical local journey is implemented and exercised through the real web
interface: import a resume, review the extracted profile, save strict
preferences, search verified official sources, inspect match evidence, request
a tailored resume, review the deterministic ATS report, approve and export the
PDF, and open the official application while retaining the selected resume in
the local application record.

## Verified capabilities

- Resume import with typed, mandatory review before any extracted claim becomes
  active evidence; replacement resumes produce a normalized version diff.
- Editable ordered roles, locations, Remote India scope, work modes, seniority,
  exclusions, freshness, and temporary typed search overrides that do not
  modify saved preferences.
- Greenhouse, Lever, Ashby, and SmartRecruiters connectors with pagination,
  explicit completeness metadata, official timestamp semantics, deduplication,
  allowlisted direct links, bounded retries, and source observations.
- Strict role, location, work-mode, seniority, exclusion, freshness, and source
  gates before ranking. Carivyo returns an honest zero-result state and never
  broadens a search without explicit user action.
- Persistent compact-memory chat with token estimates, provider-session reuse,
  task-scoped context, explicit runtime/model selection, and AI off until the
  user opts in.
- User-triggered resume design with custom instructions, frozen inputs,
  evidence constraints, immutable versions, current-preview binding, approval
  gates, completed-run restoration, an explicit new-version action, conditional
  in-browser TeX formatting edits, and run/variant/PDF-bound application
  association integrity.
- A deterministic, versioned 27-check ATS diagnostic with advisory AI review
  kept outside the deterministic score.
- Loopback binding, an ephemeral launch-token exchange, random local session token, origin validation, rate limits,
  outbound URL controls, isolated extraction, strict artifact permissions,
  redacted logs, backup, export, and deletion controls.
- Responsive React interface with concise product language, keyboard-contained
  dialogs, mobile navigation, visible loading/error/empty states, and a clear
  distinction between local storage, provider CLI processing, and fully local
  Ollama inference.

## Evidence summary

- Backend: 136 tests passed.
- Frontend: 35 tests passed across 9 files.
- Production build: 315.32 kB JavaScript (91.57 kB gzip) and 88.25 kB CSS
  (19.75 kB gzip).
- Browser journey: completed at desktop and 390 x 844 mobile widths through
  PDF export and application handoff; zero browser console errors.
- Browser axe pass on the completed Resume Studio state: zero WCAG A/AA,
  WCAG 2.1 AA, or WCAG 2.2 AA violations after the scroll/focus correction.
- Live read-only contract check: representative Greenhouse, Lever, Ashby, and
  SmartRecruiters sources all parsed valid official routes. SmartRecruiters
  correctly reported `complete=false` when its detail budget was exhausted.
- Dependency checks: `pip-audit` and production `npm audit` found no known
  vulnerabilities. Bandit found no high-severity issue; its remaining medium
  SQL findings use fixed identifiers or generated placeholder counts with
  parameterized values, and its low findings are expected allowlisted
  subprocess/public-board-token patterns.
- ATS anonymized PDF benchmark: 100 cases across ten role families,
  deterministic repeatability 1.0, issue precision 1.0, recall 0.9857, and
  published case-level analysis of the two false negatives,
  labeled issue precision 1.0, labeled issue recall 1.0. Vendor agreement is
  deliberately `null` because no authorized anonymized vendor corpus exists.

## Remaining limitations and production risks

- The catalog is curated (currently 20 configured company sources), not an
  exhaustive web search. Workday, iCIMS, and other tenant-specific systems need
  reviewed connector contracts before they can be enabled.
- SmartRecruiters requires per-job detail calls. The production detail budget
  is bounded, so large boards may be partial. Partial responses never close
  unseen jobs and never claim complete coverage.
- A direct URL is re-derived and allowlist-validated from the official source;
  Carivyo cannot guarantee that every employer page will accept an automated
  HTTP reachability probe because of bot controls. Final navigation remains
  user-controlled.
- The 98% ATS-agreement target is unproven. It is a benchmark objective, not a
  product claim, until an authorized diverse anonymized corpus supports
  category agreement, precision/recall, rank correlation, and score-deviation
  measurements.
- Every generated variant uses the generic ATS-safe A4 TeX template. Carivyo
  does not preserve or reconstruct arbitrary imported PDF/DOCX layouts.
- Exact in-browser TeX editing requires Tectonic. Without it, the website uses
  a labeled independent PDF fallback and disables source editing for that run.
- Exported fixture PDFs are visually and text-extraction tested, but the
  current generated PDF is not a tagged PDF and uses a conservative one-column
  template.
- Codex and Ollama are the controlled runtimes. Other installed provider CLIs
  are intentionally unavailable until argument-safe adapters are implemented.
- Codex token and context-savings values are estimates; provider cache-read
  billing telemetry is not available to the local website.
- Local files rely on loopback isolation, current-user permissions, and the
  host operating system's account/full-disk protection. App-managed field
  encryption and encrypted backup archives are not implemented.
- The session model and limiter are for a local single-user process, not a
  hosted multi-user threat model. No multi-device, long-duration, hostile-
  network, or full assistive-technology certification campaign has run.
- A 50-request synthetic concurrent burst measured about 3.0 seconds at p95;
  the single-user local path is fast, but hosted concurrency is not ready.
- Provider chat returns a completed response after the controlled CLI finishes;
  token-by-token streaming and cancellation of an in-flight CLI process remain
  future work.
- Enhancv is optional and external. Its UI and authentication can change, and
  CAPTCHA or account verification may require the user in the opened browser.
  The first-party local ATS remains available when the external report fails.

## Independent Reality Checker verdict

The final independent review on 2026-07-22 rated the trusted-machine,
single-user local website **PASS WITH LIMITATIONS** and hosted multi-user
production **NOT READY**. The passing local evidence is the 136-test backend
suite, 35-test frontend suite, production build, dependency audits, fresh
loopback launch, and verified core workflow. The limitations above remain
release boundaries; in particular, they do not support claims of exhaustive
live-job coverage, ATS-vendor parity, complete accessibility certification, or
hosted production readiness.
