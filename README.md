# Carivyo

Carivyo is a local-first career intelligence workspace. Upload a resume once,
answer a short adaptive interview, and receive fresh jobs ranked against
approved evidence. When a role is worth pursuing, Carivyo can create a
job-specific resume—but only after the user explicitly starts and approves the
workflow.

The product is a React/TypeScript SPA backed by a FastAPI modular monolith and
SQLite. It runs on loopback, keeps personal artifacts on the local machine, and
can use an existing Codex CLI session or an on-device Ollama model. When a
local Ollama model is installed, new profiles default to it for chat and
Carivyo's advisory hiring-manager review. Ollama cloud pointers are excluded
from every path labelled local. With Codex, compact task context is processed by the selected provider through
the installed CLI while Carivyo's records stay local. With Ollama, both stored
records and model inference remain on the device. Turning AI off keeps the
deterministic extraction, filtering, matching, and ATS paths available.

## What works

- Near-zero-configuration onboarding from PDF, DOCX, TeX, Markdown, or text.
- Adaptive questions that resolve only high-impact uncertainty.
- Greenhouse, Lever, Ashby, and SmartRecruiters connectors with pagination,
  bounded detail verification, 120 audited official company boards, custom
  company application-domain validation, and direct-application provenance.
- Tri-state job eligibility: explicit exclusions, clearly incompatible
  geography, senior scope, and missing official links remain hard gates;
  missing salary/date/work-mode/employment metadata stays eligible with visible
  uncertainty. Locations and freshness are ranked preferences by default, while
  one-time instructions can still enforce strict scope.
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
  final PDF is evaluated by a transparent first-party 27-check ATS diagnostic;
  approval is blocked if the analyzed artifacts change. Resume Studio restores
  the latest saved job-specific run after closing or refreshing, while “New
  version” starts a separate immutable run.
- Poppler-based PDF extraction preserves whitespace and merges wrapped bullets.
  Every recognized source section is retained as a blocking generation gate;
  page fitting can remove redundant details but cannot erase an entire section.
  A job-specific, explainable hiring-manager simulation adapted from the
  MIT-licensed `interviewstreet/hiring-agent` runs through on-device Ollama when
  available and remains advisory. Its displayed composite is anchored 75% to
  deterministic evidence coverage and 25% to the local-model judgment.
- User-controlled application handoff and pipeline tracking. Carivyo does not
  submit applications automatically.
- Downloadable local backup/JSON export and deletion controls, strict artifact
  permissions, rate limits, origin checks, and redacted structured logs.

## Quick start

Requirements:

- Python 3.11+ (3.13 recommended)
- Node.js 20+
- Poppler (`pdftoppm`) for PDF render validation
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

To exercise the production frontend bundle locally, use two terminals after
`make install`:

```bash
# terminal 1
export CARIVYO_BOOTSTRAP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "Private launch token: $CARIVYO_BOOTSTRAP_TOKEN"
.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8420

# terminal 2
cd frontend
npm run build
npm run preview -- --host 127.0.0.1 --port 4173
```

Open `http://127.0.0.1:4173/#bootstrap=<the token from terminal 1>`. This is a
local website deployment; Carivyo rejects non-loopback hosts and clients. A
hosted service requires the separate multi-user security controls listed in
`docs/readiness.md`.

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
intermediate reports are deleted after the run; only one compact final report
and the reusable local browser login profile are retained. Credentials are
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

Read the [problem definition](problem.md), [system architecture](system.md),
and [architecture decisions](docs/architecture-decisions.md) for the complete
design. Security reports should follow [SECURITY.md](SECURITY.md).
Third-party attributions are recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Project status

Carivyo is a tested local single-user website, not a hosted multi-user service
and not yet a production-readiness claim. Official source coverage currently
includes 120 curated company boards across Greenhouse, Lever, Ashby,
SmartRecruiters, Salesforce Careers, and Goldman Sachs Higher. The catalog is
broad rather than exhaustive, and a SmartRecruiters board is explicitly
reported as partial whenever its bounded detail-verification budget cannot
cover every listing. Broader connectors, application-managed encryption,
encrypted backups, distribution hardening, and controlled adapters for
additional CLIs remain future work.

## Ownership and license

Carivyo is private proprietary software owned by Manohar Eldhandi. It is not
open source and external use, copying, modification, redistribution, hosting,
or derivative work is not permitted without written authorization. See the
[proprietary license](LICENSE). External contributions are not accepted.
