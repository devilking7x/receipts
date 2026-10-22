# Receipts — AI Procurement Due-Diligence Investigator

**Team:** Raza7x (solo) · **Track:** Track 2 — "The Agent That Can Explain Why"
**Event:** Open Agent Hackathon 2026 (GenAI.Works)

Receipts investigates a B2B supplier before you sign with them. Give it a
vendor name and a procurement context, and it builds an evidence backed
risk report: financial health (via Zetaris), legal exposure, and
reputation — every claim cited, every score computed with transparent
math, and a "Path to Greenlight" table that says exactly what would
have to change for the vendor to become acceptable.

## Architecture

```
Planner -> 3 parallel Executors -> Adversarial Evaluator -> Writer
              (asyncio.gather)         (Markovian critique loop)
```

- **PlannerAgent** splits the investigation into FINANCIAL_TASK,
  LEGAL_TASK and REPUTATION_TASK.
- **FinancialExecutor** queries Zetaris (load-bearing: it fails closed
  without Zetaris in live mode).
- **LegalExecutor** collects legal filings and news records, then the
  Evaluator retries severe secondary claims against primary records.
- **ReputationExecutor** collects PR statements and customer reviews,
  and the Evaluator catches PR claims that contradict Zetaris data.
- **EvaluatorAgent** runs Rule A (citation audit), Rule B (source
  authority with smart retry) and Rule C (cross-domain contradiction).
- **WriterAgent** computes the deterministic risk score and writes
  `report.md` + `report.json` plus a Mermaid evidence graph.

Two custom Meterless engines power the cognition layer (no LangGraph,
no CrewAI, no external agent framework):

- **World Model** (`cognition/world_model.py`): an evidence graph of
  Entity, Claim and Evidence nodes with SUPPORTS, CONTRADICTS and
  DERIVED_FROM edges.
- **Markovian** (`cognition/markov_state.py`): the claim lifecycle
  PROPOSED → CHALLENGED → RETRY_IN_PROGRESS → VERIFIED / DISCARDED,
  with every transition written to `logs/traces.jsonl`.

## Scoring Formula

Scores are computed in pure Python from VERIFIED claims only.
Discarded claims contribute zero.

```
S_fin    = min(35, sum severity x 2.0 x confidence)  [FINANCIAL]
S_leg    = min(25, sum severity x 2.0 x confidence)  [LEGAL]
P_contra = 25 if at least one CONTRADICTS edge exists else 0
S_rep    = min(15, sum severity x 1.2 x confidence)  [REPUTATION]
Total    = round(S_fin + S_leg + P_contra + S_rep)
```

Tiers: **0–34 LOW · 35–64 MODERATE · 65–100 HIGH**.

## Setup

Requirements: Python 3.11+, Docker (optional, for the judge test).

```bash
git clone <this repo>
cd receipts-app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For a zero credential run you need nothing else: the default
`SAMPLE_MODE=true` runs the whole pipeline on cached fixture data.

For a live run, fill in `.env` with your own values:

- `METERLESS_BASE_URL` — Nightshift Runtime URL from the Nightshift
  Console (for example `http://127.0.0.1:8088/v1`).
- `METERLESS_RUNTIME_TOKEN` — Nightshift Runtime token from the
  Console (Copy, never Reveal, never Rotate by accident).
- `METERLESS_MODEL` — the exact Nemotron model string from the
  Nightshift model picker (default
  `nvidia/nemotron-3.5-lightning-30b-a3b`).
- `ZETARIS_REST_URL` — Zetaris REST API (`http://localhost:8888/api/v1.0`).
  Port 8888 is REST; port 3000 is the web UI only, never use it for
  data calls.
- `ZETARIS_ORG_ID`, `ZETARIS_API_KEY`, `ZETARIS_USERNAME`,
  `ZETARIS_PASSWORD` — your Zetaris credentials.

Security rule: your NVIDIA API key lives ONLY inside Nightshift
(Providers tab). It must never appear in `.env`, in code, in Cursor
or any coding tool settings, or in a video frame. `.env` is in
`.gitignore` from the first commit.

## Usage

CLI (sample mode, zero credentials):

```bash
python run.py --vendor "Helios Semiconductor" --sample-mode
python run.py --vendor "Northwind Supply Co." --sample-mode
python run.py --vendor "Bluepeak Manufacturing" --sample-mode
```

CLI (live mode, needs a real `.env`):

```bash
python run.py --vendor "Intel Corporation" --live
```

API server (port 8000):

```bash
python run.py --serve
curl http://localhost:8000/health
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/01_helios.json
```

Docker judge test:

```bash
docker build -t oah-submission .
docker run --rm -p 8000:8000 --env-file .env oah-submission
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/01_helios.json
```

Keyless judge test (the step people skip): remove `.env` and run
with sample mode only — exactly how a keyless judge experiences it:

```bash
docker run --rm -p 8000:8000 -e SAMPLE_MODE=true oah-submission
curl -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d @input_examples/01_helios.json
```

## Dependencies

Python 3.11, FastAPI (programmatic API), uvicorn (server), httpx
(outbound calls), pydantic (validation), python-dotenv (env files),
pytest (tests). No LangGraph, no CrewAI, no GPU required. Any NVIDIA
compute is reached through hosted or cloud access via the Nightshift
Runtime; the app itself runs on CPU.

## Agent Roles

| Agent | Job |
|---|---|
| PlannerAgent | Decomposes vendor + context into 3 non-overlapping tasks |
| FinancialExecutor | Zetaris financial records (load-bearing) |
| LegalExecutor | Legal filings and news records |
| ReputationExecutor | PR statements and customer reviews |
| EvaluatorAgent | Citation audit, source authority + retry, contradiction catch |
| WriterAgent | Deterministic scoring, report.md + report.json, Greenlight table |

Every agent receives an injected `generate_fn(system_prompt,
user_prompt, response_schema)`. In live mode that function calls the
Nightshift Runtime; in sample mode it is a labeled mock (see the
Live-vs-Cached Honesty section). Every call logs latency, tokens,
model name and agent id to `logs/traces.jsonl`. Traces are runtime
output only and are never hand-written.

## Examples

`input_examples/` holds three JSON inputs; `output_examples/` holds
the matching reports, generated by RUNNING the app (never hand-written):

| Input | Vendor | Score | Tier |
|---|---|---|---|
| `01_helios.json` | Helios Semiconductor (synthetic fixture) | 76/100 | HIGH |
| `02_northwind_clean.json` | Northwind Supply Co. (synthetic fixture) | 14/100 | LOW |
| `03_bluepeak_moderate.json` | Bluepeak Manufacturing (synthetic fixture) | 39/100 | MODERATE |

Helios math lock (computed, not stored): financial 27.55 + legal
17.10 + contradiction 25.00 + reputation 6.48 = 76.13 → **76 HIGH**,
with 3 red flags, 1 contradiction and a remediation table. The
outputs differ meaningfully across examples because they are computed
from different fixture records each run.

## Limitations

- Sample mode covers exactly the three fixture vendors. An unknown
  vendor in sample mode returns a clear 404 listing the available
  sample vendors instead of a fabricated report.
- Live mode legal and reputation coverage depends on which Zetaris
  tables exist; when a secondary table is missing, those executors
  degrade to empty results with a note instead of crashing, while
  the financial executor still fails closed without Zetaris.
- There is no live web search in this build; live reputation data
  comes through Zetaris tables where available.
- The live Intel Corporation run happens on the builder laptop (real
  Nightshift + Zetaris) and is not part of this repo snapshot; the
  repo snapshot proves the pipeline end to end in sample mode.
- Scores use the severity and confidence recorded with each source
  record; the weighting formula is fixed and public (see Scoring
  Formula), but the input severities are source supplied judgments,
  not measured facts.

## AI Disclosure

This codebase was written with AI coding assistance (Muse, plus
Cursor and GitHub Copilot as editing tools). The architecture,
scoring formula, evaluator rules and fixture contents were designed
by the builder; the AI produced the implementation files. Every
generated file was verified by running it: the test suite, the
sample pipeline runs, the API runs and the secret scan in
`scripts/verify_submission.py` were all executed, not assumed.

## Pre-existing Declaration

Planning documents and blueprints for Receipts (architecture notes,
the master prompt, the decisions log and the roadmap) were drafted
before the build window opened on 22 Oct 2026, 00:00 UTC, and are
declared here as pre-existing work. **All implementation code in
this repository was written during the build window.** The only
pre-existing code is third party libraries installed via
`requirements.txt` (FastAPI, httpx, pydantic and friends, under
their own licenses). No product code was committed before the window.

## Live-vs-Cached Honesty

- **SAMPLE_MODE=true** runs the real pipeline (plan, execute,
  evaluate with retries, score, write) on **cached synthetic fixture
  data** for three fictional vendors. The model step uses a mock
  provider labeled `sample-mock` in every trace; it never claims to
  be Nemotron, and no live model is called. Reports carry the banner
  `[SYNTHETIC SANDBOX FIXTURE - SAMPLE DATA ONLY]`.
- **LIVE mode** (`--live`, `SAMPLE_MODE=false`) calls the real
  Nightshift Runtime (Nemotron lane) for every agent reasoning step
  and queries the real Zetaris REST API for financial data. Traces
  log the exact model string returned by the Runtime.
- Nothing in this repo replays a saved output: sample mode runs the
  full logic on cached records, and every output file in
  `output_examples/` was produced by executing the app.
- The demo video (recorded separately) shows the live Intel run on
  the builder laptop; any cached segment in that video is labeled on
  screen as cached.

## Sponsor Tech

- **Zetaris (load-bearing):** the financial executor queries Zetaris
  REST (`:8888/api/v1.0`, Bearer + X-Org-ID + fresh X-Request-ID).
  Without Zetaris in live mode the pipeline stops with a clear error
  (test: `test_zetaris_load_bearing`). Citations carry the Zetaris
  table and row locators.
- **Meterless (load-bearing):** Nightshift is the primary AI provider
  for every agent; the World Model and Markovian engines are custom
  code in `cognition/`. A passing test or a live demo of the engines
  is the proof: `test_evaluator_retry` exercises the Markovian loop,
  and traces show the World Model graph.
- **NVIDIA (where it contributes):** Nemotron, reached only through
  the Nightshift Runtime lane. No direct NVIDIA calls exist anywhere
  in this repo, and the value `meterless/auto` is never used because
  it may route to a non NVIDIA model.
- **Cursor (development tool):** the scaffold and completion used
  Cursor and GitHub Copilot. Per the 2026-10-22 HackOS onboarding
  update, Cursor is optional and any AI coding tool is allowed; the
  code is tool agnostic.
