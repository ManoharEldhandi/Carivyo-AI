# Carivyo Readiness Assessment

Assessment date: 2026-09-09

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
- Strict role, source, seniority, exclusion, and clearly incompatible geography
  gates before ranking. The default desktop queue leads with current,
  strong/good priority-safe roles; broader verified listings remain available
  only through an explicit control, with their tradeoffs visible.
- Ordered job and location priorities, bounded Keep/Hide/Apply feedback
  learning, a requirement-level "Why this job?" decision view, and opt-in
  daily/weekly local searches with visible next-run state. Scheduling runs only
  while Carivyo is open and catches up once on the next start.
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
- Three frozen one-page resume templates (Balanced, AI engineering, Software
  engineering), each bound to the exact resume run. The template choice cannot
  bypass evidence, artifact, ATS, or approval gates.
- Loopback binding, an ephemeral launch-token exchange, random local session token, origin validation, rate limits,
  outbound URL controls, isolated extraction, strict artifact permissions,
  redacted logs, backup, export, and deletion controls.
- Compact dark desktop interface with keyboard-contained dialogs, visible
  loading/error/empty states, and a clear distinction between local storage,
  provider CLI processing, and fully local Ollama inference. The supported
  product target is a laptop; mobile is deliberately out of scope.

## Evidence summary

- Backend: 163 tests passed.
- Frontend: 36 tests passed across 9 files.
- Production build: 327.33 kB JavaScript (94.96 kB gzip) and 133.44 kB CSS
  (29.22 kB gzip).
- Browser journey: the current local desktop build was inspected through Jobs,
  Profile, the "Why this job?" drawer, and the three-template Resume Studio
  entry state. The queue showed current priority roles first and kept broader
  verified results behind an explicit control.
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
- Every generated variant uses one of three frozen ATS-safe A4 TeX templates.
  Carivyo does not preserve or reconstruct arbitrary imported PDF/DOCX layouts.
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
  network, or full assistive-technology certification campaign has run. Mobile
  layout is intentionally not a release target.
- A 50-request synthetic concurrent burst measured about 3.0 seconds at p95;
  the single-user local path is fast, but hosted concurrency is not ready.
- Provider chat returns a completed response after the controlled CLI finishes;
  token-by-token streaming and cancellation of an in-flight CLI process remain
  future work.
- Enhancv is optional and external. Its UI and authentication can change, and
  CAPTCHA or account verification may require the user in the opened browser.
  The first-party local ATS remains available when the external report fails.

## Independent Reality Checker verdict

The final independent review on 2026-09-09 rates the trusted-machine,
single-user laptop workspace **PASS WITH LIMITATIONS** and hosted multi-user
production **NOT READY**. The passing local evidence is the 163-test backend
suite, 36-test frontend suite, production build, loopback launcher smoke, and
verified desktop core workflow. The limitations above remain release
boundaries; in particular, they do not support claims of exhaustive live-job
coverage, ATS-vendor parity, complete accessibility certification, or hosted
production readiness.
