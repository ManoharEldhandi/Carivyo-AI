# Product implementation checklist

This release keeps Carivyo a private, laptop-first application. Codex is the
default assisted runtime; Ollama remains an optional on-device alternative.

## Search quality

- [x] Keep official-source, eligibility, and evidence boundaries in the search path.
- [x] Give ordered user priorities material weight in ranking.
- [x] Learn bounded ranking preferences from Keep, Hide, and Apply feedback.
- [x] Expose a job explanation that separates proven evidence, user-priority
  alignment, unknown metadata, and genuine gaps.
- [x] Persist daily or weekly local search schedules with visible next-run state
  and opt-in browser notification support.
- [x] Enforce the selected 24/48/72-hour freshness window as a hard inclusion
  boundary, and make India-wide official-city coverage an explicit priority.

## Product workflow and UI

- [x] Make the desktop Jobs page outcome-first: compact search scope, one clear
  refresh action, and results above the fold.
- [x] Make the detailed job view an explicit “Why this job?” decision surface.
- [x] Keep advanced search controls and technical evidence behind disclosure.
- [x] Reduce the visual density of Profile and Resume Studio without removing
  review or approval gates.
- [x] Centre the job decision view around a readable full job description and
  use compact rectangular metadata labels across the desktop product.

## Truthful resumes and ATS

- [x] Provide three evidence-safe template choices: AI, Software, and Balanced.
- [x] Freeze the selected template inside every resume run and validate it before
  export or approval.
- [x] Make ATS output show separate compatibility, evidence alignment, and
  content-quality judgments instead of implying a vendor score.
- [x] Add requirement-to-evidence explanations that make unknowns and gaps
  reviewable before tailoring.

## Release hygiene

- [x] Make Codex the default runtime selection while retaining explicit Ollama
  and fully-local choices.
- [x] Update the vulnerable PDF dependency range.
- [x] Add focused API and UI coverage for the new contracts.
- [x] Run backend tests, frontend tests, production build, and Git diff review.
- [x] Offer a user-facing local reset that clears activity and preferences while
  retaining resume masters for a fresh, evidence-gated onboarding review.

## Deliberate laptop-first boundary

The scheduler runs while Carivyo’s local service is running. If the laptop or
service is off at the due time, the next start runs the missed search; this
avoids silently installing an operating-system background agent. Browser
notifications are optional and only occur while the local workspace is open.
