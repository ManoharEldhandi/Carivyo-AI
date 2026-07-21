# Carivyo — Product Problem Definition

## Product Thesis

Carivyo is a local-first AI career agent that understands a user from their resume, asks only the few questions it cannot safely infer, continuously finds fresh and verified jobs across many sources, and lets the user create a truthful job-specific resume only for opportunities they choose.

The product should feel like opening a personal job-search workspace, not configuring a job board.

## Core Problem

Job seekers currently have to:

- Re-enter the same profile and preferences across multiple sites.
- Search many portals and repeatedly filter stale, duplicate, closed, or irrelevant jobs.
- Guess whether a role truly fits their experience.
- Rewrite a resume for every promising JD.
- Send sensitive career data to several cloud tools.
- Repeat their history whenever they start a new AI conversation.

Most products expose more filters, forms, scores, and automation. They do not reliably maintain an evidence-backed understanding of the person, prove that each job is fresh and live, or connect job discovery to controlled resume tailoring.

## Product Goal

After a user launches Carivyo and uploads one or more resumes, the system should:

1. Build a structured understanding of the user's career history, skills, evidence, seniority, likely role families, and resume tracks.
2. Ask a short adaptive interview—normally three to seven conversational questions—to resolve only high-impact uncertainty.
3. Compile the results into a reusable local profile, evidence ledger, preference model, and job-search plan.
4. Start searching automatically and present only live official jobs with accepted posting evidence from the last 48 hours, with the under-24-hour tier first.
5. Let the user open the official application directly or explicitly start a resume-design workflow with optional natural-language instructions.
6. Learn from meaningful behavior and feedback without rebuilding the profile or invoking AI after every click.

The first useful job feed should require minutes of setup, not a long form.

## Two Primary Product Jobs

### 1. Find the Right Fresh Jobs

Search many official ATS platforms, company career pages, job boards, directories, and user-authorized browser sources. Normalize, deduplicate, validate, and rank jobs using the user's evidence, preferences, location order, and activity.

Every recommendation must show:

- Official apply URL and live-status check.
- Freshness evidence and verification time.
- Fit, location, experience, and risk explanation.
- Evidence from the user's profile that supports the match.
- The recommended base-resume track.

### 2. Design a Resume for a Chosen Job

Resume tailoring is user-triggered, never automatic for every job. When the user chooses **Design resume**, Carivyo should run a separate general resume-design skill using:

- The frozen JD and company context.
- Approved candidate evidence.
- Existing base resumes and templates.
- The user's natural-language custom instructions.
- Deterministic document and truthfulness checks.

The system must preserve the original resume, show meaningful changes, expose unsupported gaps, and require approval before use.

## Supporting Experience

### AI Chat

A persistent chat should let the user say:

- “Find more backend roles in Hyderabad.”
- “Why was this role ranked above that one?”
- “Stop showing frontend-heavy jobs.”
- “Use this project and keep my current resume design.”
- “What does Carivyo know about me?”

The chat is a control and explanation layer over the same profile, preferences, jobs, and resume runs. It must not operate as an isolated fresh chatbot on every request.

### Adaptive Personalization

Carivyo maintains:

- Hard constraints explicitly confirmed by the user.
- Soft preferences inferred from conversations and behavior.
- Negative preferences learned from hidden or rejected jobs.
- Confidence and provenance for every learned preference.

It updates these only after explicit statements, meaningful activity patterns, imported evidence changes, or scheduled consolidation.

## Core Components

| Component | Responsibility |
|---|---|
| Automatic Onboarding Agent | Parses uploaded resumes, detects career tracks, identifies uncertainty, and conducts the minimal adaptive interview. |
| Context and Evidence Vault | Stores source documents, approved facts, profile summaries, resume tracks, conflicts, and provenance locally. |
| Preference Learner | Maintains hard constraints and confidence-weighted soft preferences from user statements and activity. |
| Search Planner | Converts the profile and preferences into role families, query packs, company/source targets, location order, and search budgets. |
| Job Discovery Fabric | Searches a scalable connector ecosystem instead of depending on a fixed portal list. |
| Validation and Freshness Engine | Verifies live official applications, posting evidence, eligibility, and source confidence. |
| Matching and Ranking Engine | Uses deterministic rules, local semantic retrieval, and bounded AI reranking to produce explainable recommendations. |
| Fresh Job Inbox | Shows clean job cards, location-aware ordering, freshness groups, risks, and direct actions. |
| Carivyo Resume Designer | Separate general skill for evidence-backed, user-triggered resume creation and tailoring. |
| Persistent AI Chat | Provides contextual conversation, commands, explanations, and updates using compact memory. |
| Application Tracker | Tracks interest, resume preparation, applications, interviews, rejections, and offers. |
| Local Runtime Gateway | Uses an authenticated local CLI or on-device model through controlled adapters. |
| Token and Cost Controller | Compacts context, reuses cached analysis, enforces budgets, and reports measured or estimated usage. |

## Product Principles

- One upload and a short conversation should be enough to begin.
- Ask only questions whose answers materially change the result.
- Search broadly with code; use AI deeply only on shortlisted information.
- Official sources and deterministic validation outrank AI inference.
- Every candidate claim and match reason must have provenance.
- Unknown information remains unknown.
- Profile and preference memory belongs to the application, not to a single model session.
- Resume design starts only when the user requests it.
- Final application submission remains user-controlled.
- The interface should expose outcomes first and advanced controls only when needed.

## Experience and Visual Direction

Carivyo should use a modern, calm product system: crisp high-contrast surfaces, restrained depth, an indigo intelligence accent, generous spacing, and a compact information hierarchy. Subtle neomorphic cues may add tactility, but never at the expense of contrast, focus visibility, density, or accessibility.

The primary navigation should remain small:

- Jobs
- Applications
- Chat
- Profile

Most settings should be editable through natural language or progressive disclosure rather than a large settings form.

## Non-Goals

- Fully autonomous high-volume auto-application.
- Claiming to search literally every site on the internet.
- Bypassing authentication, CAPTCHA, robots rules, or portal restrictions.
- Sending all resume and history data to every AI request.
- Rebuilding the user's profile or search plan after every interaction.
- Treating a model session as the only durable memory.
- Guaranteeing interviews or optimizing blindly for ATS scores.

## Differentiation

The category already includes broad cloud products and local job-search tools. Carivyo's position should be:

> A zero-configuration, local career agent that combines high-coverage verified job search, adaptive personal memory, token-efficient persistent chat, and provenance-backed resume design.

Its defensible advantage is not “AI for jobs.” It is the quality and efficiency of the complete loop:

**understand once → search continuously → verify evidence → rank personally → tailor only on demand → learn carefully**

## Success Measures

- Median onboarding time below five minutes.
- No more than seven onboarding questions for a typical resume.
- 100% of the primary feed supported by accepted posting evidence within 48 hours; report the under-24-hour share separately.
- Less than 2% dead links among jobs labeled verified.
- At least 70% of the top ten jobs marked Keep, Save, Apply, or More like this.
- Zero unsupported claims introduced into approved resumes.
- Typical chat requests use compact context rather than replaying full history.
- Search-plan regeneration occurs only after material profile or preference changes.
- All core data can be exported, backed up, and deleted locally.
