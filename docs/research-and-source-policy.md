# Carivyo Research and Source Policy

Updated: 2026-07-18

This document records the primary-source decisions used by the implementation.
It is not a promise that every named source family is currently enabled. The
runtime source catalog and connector coverage shown in the UI are authoritative.

## Job-source hierarchy

Carivyo ranks source trust in this order:

1. An official employer career page or public employer ATS endpoint.
2. A public ATS-hosted job detail and apply route.
3. A structured `JobPosting` record on the employer's single-job page.
4. A discovery portal used only to locate an official route; the portal record
   is never treated as freshness or liveness proof.

Greenhouse's Job Board API exposes published jobs and official absolute URLs.
Its documented `updated_at` value is an update time, so Carivyo does not relabel
it as the employer's original posting time. A connector may use a separately
documented `first_published` field when present.

- https://developers.greenhouse.io/job-board.html

Lever's public Postings API exposes published postings, hosted detail/apply
URLs, country, `allLocations`, and an explicit `workplaceType`. Carivyo uses
these structured fields and does not infer onsite work merely because a city is
present. Lever's public documentation does not make a universal freshness
guarantee, so a missing/undocumented timestamp cannot receive a fresh badge.

- https://github.com/lever/postings-api

Ashby's public Job Postings API is limited to currently published postings.
Only listed postings and their official routes are eligible.

- https://developers.ashbyhq.com/docs/public-job-posting-api

SmartRecruiters documents a public Posting API for listing active company
postings. List responses expose `offset`, `limit`, and `totalFound`; the limit
is capped at 100. Carivyo follows those fields until all summaries are fetched,
then requests each selected posting's official detail record. Because detail
fanout is bounded, any unverified remainder is reported as partial and is not
treated as a complete source response.

- https://developers.smartrecruiters.com/reference/v1listpostings
- https://developers.smartrecruiters.com/docs/endpoints
- https://developers.smartrecruiters.com/docs/customer-overview

Workday exposes customer platform APIs, but there is no single anonymous,
cross-tenant public job-board contract equivalent to the three enabled ATS
families. A future Workday adapter must be tenant-specific, fixture-tested, and
must prove its official route/timestamp semantics before being enabled.

- https://community-content.workday.com/en-us/public/products/platform-and-product-extensions/soap-api-reference.html

## Location, remote work, and liveness

Google's current `JobPosting` guidance distinguishes a physical `jobLocation`
from `jobLocationType: TELECOMMUTE` and requires
`applicantLocationRequirements` for geographically restricted remote work.
Carivyo follows the same separation: “remote” alone is not “Remote India”; the
listing must also contain India eligibility evidence. Country matching uses
normalized boundaries, so “Indiana” cannot satisfy “India.”

`datePosted` means the original employer posting date. `validThrough`, a 404 or
410 response, removal from a complete official board response, or removal of
job structured data can establish expiry. Discovery time is stored separately
and never substituted for employer-posted time.

- https://developers.google.com/search/docs/appearance/structured-data/job-posting
- https://schema.org/JobPosting

## ATS and resume evaluation

There is no universal ATS score. Public ATS guidance consistently supports
machine-readable text, conventional sections, complete titles/dates, simple
layouts, structured extraction, and comparison of skills, titles, experience,
dates, and company information. These inputs inform Carivyo's deterministic
checks; they do not justify predicting a hiring outcome.

- https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse
- https://www.workday.com/en-us/topics/hr/applicant-tracking-system.html
- https://support.greenhouse.io/hc/en-us/articles/41131616864283-Talent-Matching-Data-Processing-FAQ
- https://arxiv.org/abs/2401.16349
- https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf

Enhancv's official checker page documents its public 27-check surface and
two-tier interpretation model. Carivyo uses that surface only as a coverage
reference. The optional adapter invokes the user's authorized account, labels
the result external, requires explicit document-sharing consent, and never
presents its score as Carivyo's score.

- https://enhancv.com/resources/resume-checker/
- https://enhancv.com/features/tailor-resume-to-job-description/

## AI model routing

OpenAI's current model guidance identifies GPT-5.6 Sol as the quality-first
frontier model, Terra as the balance of intelligence and cost, and Luna as the
cost-sensitive/high-volume option. Carivyo keeps this as a versioned model
catalog instead of scattering model slugs through the codebase:

- Terra/low is the reviewed default for interactive career chat and ordinary
  semantic review.
- Luna is offered for extraction, routing, classification, and concise chat.
- Sol is opt-in for difficult evidence or resume reasoning.

The runtime validates provider authentication, executable compatibility,
catalog membership, and reasoning support before selection. Model usage remains
provider-processed unless an Ollama model is explicitly selected.

- https://developers.openai.com/api/docs/models
- https://developers.openai.com/api/docs/models/gpt-5.6-sol

The OpenAI Docs MCP was installed during this audit, but the current Codex task
must be restarted before newly installed MCP tools become callable. The exact
GPT-5.6 migration/prompt pages did not render through fallback browsing, so the
implementation used the official model pages plus the bundled OpenAI Docs skill
guidance for tier-aware routing. Pricing is deliberately not hardcoded.
