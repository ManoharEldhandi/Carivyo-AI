# Carivyo

Carivyo is a local-first career intelligence workspace. Upload a resume once,
answer a short adaptive interview, and receive fresh jobs ranked against
approved evidence. When a role is worth pursuing, Carivyo can create a
job-specific resume—but only after the user explicitly starts and approves the
workflow.

The product is a React/TypeScript SPA backed by a FastAPI modular monolith and
SQLite. It runs on loopback, keeps personal artifacts on the local machine, and
can use an existing Codex CLI session or an on-device Ollama model. Codex is
the default assisted runtime; Ollama is an explicit on-device alternative for
chat and Carivyo's advisory hiring-manager review. Ollama cloud pointers are excluded
from every path labelled local. With Codex, compact task context is processed by the selected provider through
the installed CLI while Carivyo's records stay local. With Ollama, both stored
records and model inference remain on the device. The explicit Fully local
switch blocks provider-backed execution and refuses to fall back when Ollama
is unavailable. Turning AI off keeps the
deterministic extraction, filtering, matching, and ATS paths available.

## Verified project scope

- **2 model runtimes**: an authenticated Codex CLI session (the default) or an
  on-device Ollama model, with explicit provider selection and no silent
  fallback in fully local mode.
- **27 deterministic ATS checks** bound to the exact resume and job-description
  artifacts, with approval invalidated when the analyzed evidence changes.
- **4 official hiring-system connectors** for Greenhouse, Lever, Ashby, and
  SmartRecruiters, backed by **120 audited company boards** and direct-source
  provenance.
- Evidence-gated structured outputs, deterministic eligibility filters,
  redacted logs, bounded verification, and layered prompt-injection defenses;
  application handoff always remains user controlled.

## What works

- Near-zero-configuration onboarding from PDF, DOCX, TeX, Markdown, or text.
- Adaptive questions that resolve only high-impact uncertainty.
- Greenhouse, Lever, Ashby, and SmartRecruiters connectors with pagination,
  bounded detail verification, 120 audited official company boards, custom
  company application-domain validation, and direct-application provenance.
- Tri-state job eligibility: explicit exclusions, clearly incompatible
  geography, senior scope, and missing official links remain hard gates;
  missing salary/work-mode/employment metadata stays eligible with visible
  uncertainty. A saved freshness limit is always strict: choosing 24, 48, or
  72 hours excludes older and date-unverified listings. Locations retain their
  deliberate priority order, including an explicit India-wide option for the
  supported official-source cities.
- A focused desktop queue that puts current, strong/good priority matches first;
  older or lower-confidence official listings are available through an explicit
  broader-results control instead of competing with the next decision.
- Opt-in daily or weekly searches while the local service is open, with a
  visible next run and optional browser notification. A missed search runs once
  on the next local start; Carivyo does not install a hidden background agent.
- Feedback-aware ranking learns a small, explainable preference signal from
  Keep, Hide, and Apply actions. Every role also has a "Why this job?" view
  that separates proven evidence, priority alignment, unknowns, and real gaps.
- A local “Start fresh” control clears search, application, generated-resume,
  ATS, schedule, chat, profile, and backup data while retaining imported resume
  masters for a fresh evidence review. Full deletion remains available through
  the local API for users who do not want to retain a master.
- Resume-supported role expansion covers software/backend, AI/LLM, applied ML,
  and company-specific early-career titles such as AMTS, engineering analyst,
  programmer analyst, graduate engineer trainee, and applications developer.
- Editable profile priorities, natural-language preference routing, explicit
  resume replacement, and one-time search overrides that never mutate saved
  priorities.
- Persistent compact-memory chat with provider-session reuse and visible token
  estimates, explicit Codex/Ollama model selection, and AI chat disabled until
  the user opts in.
- A general, isolated resume-design skill with frozen inputs, evidence mapping,
  unsupported-gap reporting, artifact checks, and an approval gate. The exact
  final PDF is evaluated by ATS v2 as three independent outputs—submission
  compatibility, evidence-backed job alignment, and content quality. A full
  official JD is required before job-specific alignment is shown;
  approval is blocked if the analyzed artifacts change. Resume Studio restores
  the latest saved job-specific run after closing or refreshing, while “New
  version” starts a separate immutable run.
- Three frozen, evidence-safe one-page resume templates—Balanced, AI
  engineering, and Software engineering—can be selected before tailoring.
  The chosen template is recorded inside the immutable resume run and checked
  before export or approval.
- Resume Studio offers the reviewed Codex model catalog and only the reasoning
  efforts supported by the selected model. Its per-run default is GPT-5.6 Terra
  at Extra high reasoning; this does not change the app-wide runtime setting.
  Codex creates a visible JD-and-evidence advisory plan, while deterministic
  evidence selection writes the actual resume.
- Optional GitHub verification requires a second explicit consent and examines
  only direct public repository URLs already present in approved evidence. It
  can prioritize an existing claim, but never adds a repository-derived skill,
  metric, responsibility, or new bullet automatically.
- Independent `pypdf` and Poppler extraction must agree, and every rendered PDF
  page passes machine visual validation before approval.
  Every recognized source section is retained as a blocking generation gate;
  page fitting can remove redundant details but cannot erase an entire section.
  A job-specific, explainable hiring-manager simulation adapted from the
  MIT-licensed `interviewstreet/hiring-agent` runs through on-device Ollama when
  available and remains advisory. Each hiring dimension uses its own evidence
  baseline before the local model contributes advisory judgment.
- User-controlled application handoff and pipeline tracking. Carivyo does not
  submit applications automatically.
- Downloadable local backup/JSON export and deletion controls, strict artifact
  permissions, rate limits, origin checks, and redacted structured logs.

## Quick start

Requirements:

- Python 3.11+ (3.13 recommended)
- Node.js 20+
- Poppler (`pdftoppm` and `pdftotext`) for render and parser-consensus validation
- Optional: authenticated Codex CLI or a running Ollama model
- Optional: Tectonic for in-browser TeX compilation (`brew install tectonic`)

On macOS, Poppler can be installed with `brew install poppler`. Then:

```bash
git clone https://github.com/ManoharEldhandi/Carivyo-AI.git
cd Carivyo-AI
make install
make dev
```

`make dev` starts both services and opens `http://127.0.0.1:5173/`
automatically. The frontend receives an ephemeral launch token from the local
process, so reopening that address while `make dev` is running also works. The
API runs at `http://127.0.0.1:8420`. Personal data is written to `.carivyo/` by
default and is excluded from Git. Set `CARIVYO_NO_OPEN=1` when browser launch is
not wanted. Shutdown terminates the complete frontend/backend process trees;
startup refuses occupied ports instead of silently serving an older bundle.

### Codex Terra demo

For the interview/demo configuration, run:

```bash
./run-demo.sh
```

The launcher keeps all Carivyo data local, installs the official Codex CLI into the ignored
`.carivyo/tools/` directory when it is not already available, and asks for a one-time Codex sign-in
only when required. It starts the backend and frontend, prints all local URLs, and explicitly
selects **Codex CLI + GPT-5.6 Terra** for AI work. It does not remove or disable Ollama: choose the
Fully local option in **Profile > AI runtime** to use an installed on-device Ollama model instead.

The Codex provider receives compact task context through its local CLI session; Carivyo's profile,
jobs, resumes, artifacts, and SQLite database remain on this machine. The app keeps deterministic
search, matching, and ATS analysis available even when AI is disabled or unavailable.

For the complete product walkthrough, architecture, technology map, and interview demo script, see
[docs/DEMO_GUIDE.md](docs/DEMO_GUIDE.md). Generate its shareable PDF with:

```bash
.venv/bin/python scripts/generate_demo_guide_pdf.py
```

To return to the resume-submission first screen before a demo, stop Carivyo and run:

```bash
./reset-demo-data.sh
```

To build and run the laptop release (the production frontend assets served by
one loopback-only local process), use:

```bash
make local-release
```

The launcher prints a private `http://127.0.0.1:8420/#bootstrap=…` URL and
opens it unless `--no-browser` is passed to `carivyo start`. This is a local
laptop release, not a hosted deployment or a signed native installer; Carivyo
rejects non-loopback hosts and clients. A hosted service requires the separate
multi-user controls listed in `docs/readiness.md`.

`make install` chooses Python 3.13, 3.12, or 3.11 when available and uses the
public npm registry and PyPI. Override the interpreter or Python index when
needed:

```bash
make install PYTHON=/path/to/python PYPI_INDEX=https://your-reviewed-mirror/simple
```

Copy `.env.example` to `.env` only when changing defaults. Carivyo works without
an environment file.

### Optional Enhancv report

The local 27-check ATS is always available and remains the default. To add an
Enhancv report option, install its browser once and configure an authorized
checker script in the ignored `.env`:

```bash
make setup-enhancv
cp .env.example .env
```

Set `CARIVYO_ENHANCV_EMAIL`, `CARIVYO_ENHANCV_PASSWORD`, and
`CARIVYO_ENHANCV_SCRIPT_PATH` locally. On macOS, an existing `enhancv.com`
Keychain item can be used instead with `CARIVYO_ENHANCV_USE_KEYCHAIN=true`.
The UI asks for explicit consent before
sending the exact PDF and JD. Browser HTML, screenshots, logs, and generic
intermediate reports are deleted after the run; immutable, versioned compact
reports and the reusable local browser login profile are retained. Each report
is bound to the actual PDF/JD bytes and kept in history. Credentials are
never committed or returned through the API.

## Validation

Run the same local checks used by CI:

```bash
make check
```

The resume skill also has an executable run-contract validator:

```bash
.venv/bin/python skills/carivyo-resume-designer/scripts/validate_run.py \
  /absolute/path/to/a/resume-run
```

Current evidence, browser coverage, performance observations, and limitations
are recorded in [docs/validation.md](docs/validation.md) and
[docs/readiness.md](docs/readiness.md). The independent ATS calculation,
calibration boundary, and safety rules are documented in
[docs/ats-methodology.md](docs/ats-methodology.md).

## Architecture and trust boundary

Carivyo treats every job description and remote response as untrusted data.
Freshness comes from connector-specific official timestamps—not model
inference. Candidate claims must come from the approved evidence ledger. Raw
shell commands are never accepted from the UI, imported content cannot become
instructions, and external application URLs must pass connector-specific
allowlists.

Each new resume run produces an A4, single-column TeX design source. When
Tectonic is installed, the displayed PDF is compiled from that exact source and
formatting-only edits are enabled in Resume Studio. Without Tectonic, Carivyo
uses an independent ReportLab PDF fallback and clearly disables TeX editing;
it never presents that source as the exact origin of the fallback PDF. Unsafe
file/shell primitives and unsupported content are rejected. Imported PDFs and
DOCX files use the explicit ATS-safe Build path because arbitrary source-layout
reconstruction is not claimed.

Generated TeX uses the same Carlito-first, Helvetica-fallback sans-serif
strategy as the retained master resumes. The master resume's direct source
language is retained: an optional model can identify priorities and gaps, but
cannot rewrite evidence or make a factual assertion eligible for export.

Read the [problem definition](problem.md), [system architecture](system.md),
and [architecture decisions](docs/architecture-decisions.md) for the complete
design. Security reports should follow [SECURITY.md](SECURITY.md).
Third-party attributions are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Project status

Carivyo is Git-ready for a private, laptop-first release from this repository:
`make local-release` builds the frontend and starts one authenticated loopback
service. It is not a hosted multi-user product or a signed native installer.
Official source coverage currently includes 120 curated company boards across
Greenhouse, Lever, Ashby, SmartRecruiters, Salesforce Careers, and Goldman
Sachs Higher. The catalog is broad rather than exhaustive, and a
SmartRecruiters board is explicitly reported as partial whenever its bounded
detail-verification budget cannot cover every listing. Broader connectors,
application-managed encryption, encrypted backups, signed distribution, and
controlled adapters for additional CLIs remain future work.

## Ownership and license

Carivyo is private proprietary software owned by Manohar Eldhandi. It is not
open source and external use, copying, modification, redistribution, hosting,
or derivative work is not permitted without written authorization. See the
[proprietary license](LICENSE). External contributions are not accepted.
