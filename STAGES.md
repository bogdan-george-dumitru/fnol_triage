# Build progress — AI-assisted FNOL triage

Living tracker of the incremental build. Each stage ends **runnable** and reviewed
before the next. Legend: ✅ done · 🔨 in progress · ⬜ pending.

| # | Stage | Status | How to see it |
|---|---|---|---|
| 0 | Skeleton, config, provider abstraction | ✅ | `uv run uvicorn app.main:app` → `/health` |
| 1 | Domain models + versioned business config | ✅ | `uv run python -m scripts.seed`; inspect `data/app.db` |
| 2 | Ingest + extraction (mock + OpenAI, incl. vision) | ✅ | `uv run python -m scripts.extract samples/<f>` |
| 3 | Classify → deterministic route → status | ✅ | `uv run python -m scripts.triage samples/<f>` |
| 4 | Review UI + claim creation (idempotent) | ✅ | `uvicorn app.main:app` → open `/` |
| 5 | Config UI + preview/test + versioning | ✅ | `uvicorn app.main:app` → "Workflow config" tab |
| 6 | Observability (JSON logs, `/metrics`) | ✅ | `uvicorn app.main:app` → "Metrics" tab or `GET /metrics` |
| 7 | Test set + eval (mock vs OpenAI baseline) | ✅ | `uv run python -m eval.run_eval --provider mock\|openai` |
| 8 | README + customer-context note + presentations | ✅ | `README.md`, `docs/CUSTOMER_CONTEXT.md`, `docs/PRESENTATIONS.md` |

Run tests any time: `uv run pytest -q`. Default provider is **mock** (free); OpenAI
runs only when `LLM_PROVIDER=openai` is set.

---

## Stage 0 — Skeleton ✅
Project scaffolding: `uv`/pip setup, `.env` config (`pydantic-settings`), FastAPI
`/health`, the `LLMProvider` interface with OpenAI + mock implementations, `.gitignore`
(excludes `.env`, `data/*.db`).
- **Files:** `app/config.py`, `app/main.py`, `app/providers/`.
- **Verified:** app boots, `/health` ok, 1 test.

## Stage 1 — Domain + versioned config ✅
The foundation: FNOL domain types and the **business-owned workflow config** (taxonomy,
queues, flag rules, routing rules, templates, thresholds) with referential-integrity
validation and a **versioned store** (save / activate / rollback). Realistic starter
config for Home/Property + Life CPI.
- **Files:** `app/models.py`, `app/workflow/{schema,seed,store}.py`, `app/db.py`.
- **Ownership split:** business owns taxonomy/LOB (as data); code owns `Severity`/`Status`.
- **Verified:** 9 tests (determinism, validation, save→edit→rollback).

## Stage 2 — Ingest + extraction ✅
Ingest `.txt/.eml/.pdf/.png/.jpg` with a **tunable text-layer heuristic** (chars/page +
garbage ratio → text vs. vision). Extraction: mock (regex/keyword baseline) + OpenAI
(`gpt-5-mini` structured output; vision for scans/handwriting). Schema-invalid → 1 retry
→ manual.
- **Files:** `app/ingest.py`, `app/providers/{mock,openai_provider}.py`, `samples/`.
- **Bug found & fixed:** `.eml` without a charset header decoded as ASCII → mangled RO
  diacritics → broke the policy-number match. Now decodes raw payload as UTF-8.
- **Verified:** 22 tests; OpenAI validated on 4 text samples + a handwritten image.
- **Cost note:** ~$0.003 / document; output (reasoning) tokens dominate.

## Stage 3 — Classify → route → status ✅
LLM classification against the business taxonomy; deterministic triage (flags, severity
floors, routing with flag-forced queues, required-field checks, **simulated policy master**
for contestability/fraud/in-force), status 🟢🟡🔴 + reasons + alternatives + template draft.
Fallbacks: extraction fail → 🔴 manual; classify fail → baseline, forced 🟡.
- **Files:** `app/triage.py`, `app/pipeline.py`, `app/policy.py`.
- **3 bugs found & fixed (via live runs):**
  1. `catastrophe` false-fired on a burst-pipe water claim → **flags scoped by claim type**.
  2. death-only flags fired on an unemployment claim → same claim-type scoping.
  3. `bodily_injury` missed "arsuri" and false-fired on "nu sunt răniți" → **driven by the
     model's structured field, not keywords**; `catastrophe` broadened to stems.
- **Verified:** 38 tests; OpenAI end-to-end on typed + font-image + real handwritten samples.

## Stage 4 — Review UI + claim creation ✅
FastAPI endpoints + a single static HTML/JS review screen: the **original document beside
the editable proposal** (text, image, or PDF preview). The handler edits LOB / claim type
(incl. one-click alternatives) / severity / queue / status, sees flags, reasons, the policy
check and the draft ack, then approves. A **simulated claims API books the claim, idempotent
by document hash** — re-uploading/re-approving the same document never books twice. Human
edits vs. the AI proposal are recorded (feeds the Stage 6 override-rate metric).
- **Files:** `app/api.py`, `app/main.py`, `app/review_store.py`, `app/claims.py`, `static/index.html`.
- **Verified:** 43 tests incl. upload→proposal, approve→claim, idempotent re-approve,
  re-upload-same-doc→no second claim, edit tracking. Driven end-to-end in the browser
  (upload → review → approve → BOOKED).

## Stage 5 — Config UI + preview/test + versioning ✅
The maintainability centerpiece. A "Workflow config" screen lets a non-technical owner
edit thresholds, routing-rule queues, and flag keywords/forced-queues; **preview** the
proposed config against a labeled sample set (10 cases) and see exactly which cases flip
status/queue — with an Expected column acting as a mini-accuracy check; then **save as a
new version** (validated) or **roll back** to any prior version.
- **Design:** preview holds extraction + classification fixed and recomputes only the
  deterministic triage, so it is **free and instant** (no model calls). Stated plainly that
  it does not re-simulate model classification.
- **Files:** `eval/dataset.py` (labeled cases, reused by Stage 7), `app/preview.py`,
  config endpoints in `app/api.py`, config view in `static/index.html`.
- **Bug found & fixed:** a red manual proposal was still routed to its classified queue —
  now a red status always routes to `manual_intake` (status and queue never disagree).
- **Verified:** 49 tests incl. all 10 dataset cases matching expected labels, preview diff,
  save->rollback, invalid-config rejection. Driven in the browser (edit -> preview -> flip).

## Stage 6 — Observability ✅
Structured JSON logs + a metrics endpoint.
- **Structured logs:** one JSON line per run to stdout, tagged with a `request_id`,
  carrying per-stage latency (extract/classify/triage), token usage, estimated cost,
  status and queue.
- **`/metrics`** (and `/api/metrics`, plus a "Metrics" UI tab): documents processed,
  latency p50/p95/max, cost per document, avg tokens/doc, status/queue/LOB/ingestion/
  provider distributions, and the **human override rate** (how often reviewers changed the
  AI, with a per-field breakdown) computed from the recorded edits.
- **Cost model:** per-1M-token rates are configurable in `.env` (defaults are rough
  gpt-5-mini figures); mock runs are free (0 tokens, $0).
- **Files:** `app/observability.py`, `app/metrics.py`, `runs` table, wiring in
  `app/api.py` + `app/pipeline.py`, Metrics view in `static/index.html`.
- **Verified:** 52 tests incl. cost estimation, run aggregation, override rate, and the
  metrics endpoint. Driven in the browser (Metrics tab) + JSON logs inspected.

## Stage 7 — Test set + eval ✅
A hand-labeled test set of **17 documents** (`eval/testset/labels.json`) covering the brief's
scenarios: clean email, free-text, typos/abbreviations, clean typed PDF (text layer),
handwritten images (font + real), English, ambiguous, policy-not-found, lapsed policy, large
loss, death within contestability, prompt injection, and no-policy. `eval/run_eval.py
--provider mock|openai` runs the full pipeline on a fresh temp DB and reports extraction P/R,
classification/routing accuracy, high-severity recall, **green-line precision (key metric)**,
status distribution, latency p50/p95 and cost per document, writing JSON to `eval/results/`.
- **Files:** `eval/testset/` (docs + labels), `eval/run_eval.py`, `scripts/make_sample_pdf.py`.
- **Result — OpenAI vs mock baseline:** extraction F1 1.00 vs 0.86; routing 0.88 vs 0.47;
  status accuracy 0.94 vs 0.18; **green precision 1.00 (zero false auto-approvals)** vs N/A.
  The real cost is latency: ~13s/doc (reasoning + vision) vs sub-ms for mock; ~$0.004/doc.
- **Verified:** 53 tests incl. an eval smoke test; both result files in `eval/results/`.

## Stage 8 — README + customer-context note ✅
Final documentation.
- **`README.md`** — setup (uv + pip), assumptions, architecture (flow, components, data
  model, the AI-vs-code split, failure handling), **trade-offs** backed by the real eval
  numbers (green precision 1.00, ~13s/doc latency, ~$0.004/doc), known limitations, where
  AI is used (runtime + in building this), out of scope.
- **`docs/CUSTOMER_CONTEXT.md`** — the customer, team, pain, volumes, the proposes/checks/decides
  principle, why it is business-maintainable (incl. natural-language AI-judged flags), and
  trust/rollout notes.
- **`docs/PRESENTATIONS.md`** + **`docs/PRESENTATION_RUNSHEET_RO.md`** — the two interview decks
  (index + links) and the speaker runsheet.
- All stages complete; 61 tests passing.

## Post-stage refactor — persistence port/adapter ✅
Applied dependency inversion at the storage boundary (symmetric with the model-provider port).
- **New:** `app/persistence/base.py` (the `Repository` / `TriageRepository` Protocols + port
  record types `StoredDocument`, `VersionMeta`, `ConfigValidationError`) and
  `app/persistence/sqlite/` — **all** SQLite code consolidated here (`schema`, `documents`,
  `claims`, `policies`, `dedup`, `runs`, `config`, `repository`).
- **Moved out of the domain:** the former top-level `app/{db,claims,review_store,dedup,metrics}.py`
  and `app/workflow/store.py` became the SQLite adapter's internals; `Claim` moved to
  `app/models.py`; `Policy` + seed stayed domain-only in `app/policy.py`.
- **Result:** `app/pipeline.py` and `app/triage.py` no longer import `sqlite3`; they depend on
  the port. `get_document` returns a `StoredDocument`, not a `sqlite3.Row` (no driver leak).
  A Postgres adapter would implement the same Protocols without touching the domain or the API.
- **Verified:** 61 tests passing; live end-to-end smoke + mock eval re-run green.
