# Carivyo Implementation Decisions

These decisions close build-critical gaps found during the architecture audit.
They are intentionally narrower than the complete product vision.

## ADR-001 — Local Modular Monolith

**Status:** Accepted

Carivyo ships as a React SPA, FastAPI application, SQLite database, and local
artifact vault. Product agents are application modules behind typed use cases,
not processes or network services.

This keeps transactions, local installation, debugging, and privacy manageable.
Module ports preserve an extraction path if a future workload needs isolation.

## ADR-002 — Deterministic Core, Optional AI Depth

**Status:** Accepted

Resume extraction, URL checks, source parsing, freshness classification,
deduplication, hard gates, baseline scoring, token estimation, and document
validation are deterministic. AI is optional for conversational synthesis and
bounded reranking.

If no runtime is available, the core journey degrades visibly instead of
blocking or fabricating an AI result.

## ADR-003 — Official ATS MVP Boundary

**Status:** Accepted

The first release implements Greenhouse, Lever, Ashby, and SmartRecruiters
against their public job-board interfaces. A source catalog supplies board
identifiers. Discovery and verification remain separate: only a connector-
specific official response can label a job live. SmartRecruiters list
pagination and detail verification expose explicit completeness metadata; a
bounded partial response can add verified jobs but cannot close unseen jobs or
claim exhaustive coverage.

Generic crawling, browser-session sources, Workday, iCIMS, and similar
tenant-specific adapters are deferred until canonicalization, retry behavior,
timestamp semantics, and dead-link rates are measured on the enabled families.

## ADR-004 — Freshness Is Evidence, Not Inference

**Status:** Accepted

`first_published`, Lever `createdAt`, and Ashby `publishedAt` are accepted only
for their documented posting semantics. Greenhouse `updated_at` is not treated
as a posting date. Future, malformed, or missing timestamps cannot receive a
verified freshness badge.

Search completion does not imply a supply of jobs under 24 hours. The feed
always reports the observed mix.

## ADR-005 — Immutable Evidence and Resume Runs

**Status:** Accepted

Imported claims are not approved until onboarding confirmation. Resume runs
consume only a frozen job snapshot, approved evidence, a selected base record,
and current instructions. Every artifact is written under a run-scoped
directory and the original resume is never overwritten.

The imported base remains immutable. Every generated variant uses the generic
A4, single-column TeX template while preserving approved claims and measuring
relevance-based changes against the imported base. Resume Studio exposes that
generated TeX for formatting-only edits when Tectonic compiled the visible
PDF. If Tectonic is unavailable, it labels the independent ReportLab fallback
and disables source editing for that run. It rejects file/shell primitives and
any edit whose compiled visible text differs from the prior evidence-reviewed
variant; factual wording changes must pass through the normal revision path.
Carivyo does not claim to reconstruct or preserve arbitrary PDF or DOCX source
layouts.

## ADR-006 — Explicit Mutation and Application Gates

**Status:** Accepted

Chat emits typed intents. Preference mutations, resume approval, application
preparation, and external URL opening are validated by server-side state
transitions. Opening an application never records a submission; only the user
can mark it applied.

## ADR-007 — Recovery Through Idempotent Checkpoints

**Status:** Accepted

Imports key by content hash, search plans key by profile and preference
versions, connector records key by source and external ID, verifications record
verifier version, and resume artifacts key by run ID. Long workflows persist
stages and retry bounded transient failures without duplicating records.

## ADR-008 — Truthful Runtime Capability Reporting

**Status:** Accepted

The controlled MVP adapters are Codex and Ollama. Codex conversations persist
their provider session identifier and resume that session when possible;
Carivyo still stores the durable compact context and can reconstruct it after a
provider-session failure. Ollama uses explicit compact prompts and measured
usage when the local endpoint reports it.

Claude Code, Gemini CLI, and OpenCode may be detected for diagnostics, but they
are reported as unavailable until argument-safe, bounded adapters are
implemented and tested.

## ADR-009 — Local Security Boundary

**Status:** Accepted

The MVP binds only to loopback, uses a random session token, validates origins,
rate-limits local requests, restricts artifact and runtime directories to the
current user, guards outbound URLs against SSRF, sanitizes untrusted source
content, and never accepts provider credentials.

Application-managed field encryption and encrypted backups are distribution
hardening work, not completed MVP features. Until then, users should run
Carivyo on a device protected by operating-system account security and
full-disk encryption.

## Deferred Release Capabilities

- Browser autofill or automatic submission.
- Signed-in browser connectors.
- In-place backup restore while the application is running.
- AI processing after individual save/hide events.
- Claims of exhaustive portal coverage.
- Application-managed field encryption and encrypted backup archives.
- Controlled Claude Code, Gemini CLI, and OpenCode adapters.

## ADR-010 — Hard Search Contract Before Ranking

**Status:** Accepted

Target roles, ordered locations, Remote India scope, work modes, seniority,
explicit exclusions, official-direct source policy, and the 48-hour cutoff are
eligibility gates. A fit score can never compensate for a failed gate. Unknown
or missing posting dates do not enter the default feed. Zero correct jobs is a
valid successful result and is preferable to one irrelevant recommendation.

Freshness is recomputed when the feed is read. Each successful complete board
response also closes previously observed listings that disappeared from that
official source.

## ADR-011 — Transparent First-Party Resume Analysis

**Status:** Accepted

Carivyo runs a deterministic, versioned 27-check analyzer against the exact
final PDF text and frozen job description. Its score is a diagnostic summary,
not a universal ATS score or a reproduction of a third party's proprietary
formula. Every check exposes its weight, evidence, status, and suggested fix.

The seven public categories are ATS essentials, resume sections, content, job
tailoring, recruiter red flags, bias/date safety, and seniority/impact. Missing
inputs become `not_applicable`; protected traits are never inferred. Resume
approval is bound to the analyzed JD and artifact hashes.

## ADR-012 — Explicit Runtime and Model Selection

**Status:** Accepted

The UI separates local data storage from AI processing location. It shows the
resolved provider, exact model, reasoning profile, session reuse, and measured
or estimated usage. Codex defaults to GPT-5.6 Terra at low reasoning for the
balanced chat path; Luna and Sol remain explicit efficient and quality-first
choices. Installed Ollama models are enumerated and validated server-side.

Changing provider or model invalidates provider-session reuse. If a selected
model disappears, Carivyo reports the failure rather than silently choosing a
different model.

## ADR-013 — Typed Temporary Search Overrides

**Status:** Accepted

A one-time natural-language search instruction is parsed into the same typed
preference schema used by onboarding. It is applied to one search plan only,
records its source text and interpreted fields, and never writes to the saved
profile. Ambiguous or unsupported text fails visibly instead of falling into a
generic keyword bucket or silently broadening the search.

## ADR-014 — Variant-Bound Resume Review State

**Status:** Accepted

Preview images, deterministic ATS reports, semantic reviews, approval, export,
and application association are bound to the exact resume run ID, variant, and
PDF hash. Submitted application bindings make that resume run immutable.
A revision clears stale derived state immediately. Late asynchronous responses
are ignored unless their run/variant key still matches the visible version.
Application handoff preserves the approved run association and cannot silently
substitute a newer resume.

## ADR-015 — Explicit External ATS Boundary and Resume Recovery

**Status:** Accepted

The first-party deterministic ATS is always available and remains the default.
Enhancv is an optional external comparison selected inside Resume Studio. It
requires explicit per-variant document-sharing consent bound to the PDF and
frozen-JD hashes, invokes only a configured
allowlisted Python adapter, reads credentials from local environment settings
or the operating-system Keychain, and keeps one compact final report after
temporary browser outputs are removed. Its result never replaces the local
approval gate or implies vendor parity.

Closing or refreshing Resume Studio restores the latest completed run for that
job. Starting “New version” is explicit and creates a separate immutable run;
it does not overwrite the restored run.
