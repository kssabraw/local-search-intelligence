# collector — Stage-1 vertical-slice spike (Maps + Organic)

Minimal, **single-coordinate** vertical slice for the Governing build sequence
step 7:

```
one DataForSEO Maps/Organic task_post
  -> immutable content-addressed raw (fail-on-exists, gzipped)
  -> parse
  -> normalize (<surface>.observation / <surface>.result / core.observed_object)
  -> resolve entity
  -> cost ledger (ops.cost_event)
```

This is **not** the production scheduler/worker. It is the smallest end-to-end
path that proves the shared foundation on the cheapest, most-settled surfaces.

Both Google surfaces ride the **one shared foundation** (ADR-0004); the spike
dispatches on `manifest.surface.surface_code`:

| surface | parser | normalizer | resolver | canonical entity |
|---|---|---|---|---|
| `maps` | `parse_maps.py` | `maps.observation` / `maps.result` | place_id-first (`resolve_maps_item`) | `business_location` |
| `organic` | `parse_organic.py` | `organic.observation` / `organic.result` | URL-first, then domain (`resolve_organic_item`) | `web_url` under `web_domain` |

**Organic specifics.** A DataForSEO organic *advanced* response is a
heterogeneous item list (`organic`, `local_pack`, `people_also_ask`,
`related_searches`, …). **Every** block is preserved as an `organic.result` row
with its `result_type` and `rank_absolute`; only an organic web destination
(`type == 'organic'` with a domain/URL) additionally becomes a
`core.observed_object` and is resolved. `returned_result_count` counts the
organic-type items (the Organic surface's result depth); the total block count
is preserved in `serp_metadata`. Per contract §14, organic surfacing creates a
normalized **web** object (`core.web_url` / `core.web_domain`) and **never** a
canonical-business truth — no `business_location` is ever minted from Organic.

## Design

- External effects are behind interfaces so the pipeline is testable offline and
  validatable against the real schema without a paid call:
  - `MapsProvider` (`dataforseo.py`) — real `HttpMapsProvider` vs a fake fixture.
    The same `task_post` → `task_get/advanced` protocol serves Organic (endpoints
    come from the resolved `provider_profile`).
  - `RawStore` (`raw_store.py`) — real Supabase Storage vs an in-memory fake.
- `parse_maps.py`, `parse_organic.py`, `resolve.py`, and `normalize.py` are
  **pure** (no I/O) → unit-tested directly.
- `repository.py` performs all DB writes via `psycopg`, honoring the schema's
  NOT NULL / FK / CHECK constraints and the append-only immutability triggers.
- Idempotency: `job_key = sha256(methodology|wave|surface|industry|market|treatment|coordinate|replicate)`
  (`idempotency.py`). A technical retry never duplicates a paid call; a valid
  short/empty result is a real observation, never retried for a "better" one.

## Configuration (env only — never committed)

Secrets come from the environment (injected by Railway/Supabase secret
management), never from the repo:

| var | purpose |
|---|---|
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | DataForSEO Basic auth |
| `SUPABASE_DB_URL` | Postgres connection (service-role / direct) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Storage REST for the raw bucket |
| `LSI_METHODOLOGY_CODE` | default `MANIFEST_V1_0` |

## Running the spike

**Gated: the live run makes the first paid DataForSEO call.** Only after the
owner confirms and the secrets above are set, and migrations `001`–`021` are
applied to the target database:

```bash
python -m collector.spike --industry IND010 --market MKT008 --point C --treatment Q1 --surface maps
python -m collector.spike --industry IND010 --market MKT008 --point C --treatment Q1 --surface organic
```

Add `--dry-run` to build and print the request + resolve the manifest context
without calling the provider (no paid call, no writes).

## The 3×5 pilot batch run harness (`pilot.py`)

`spike.py` is deliberately single-coordinate. `pilot.py` iterates the **frozen
v1.0 executable job matrix** for the bounded Stage-1 pilot and drives one
`run_spike` per executable job:

- **Matrix:** 3 industries (`IND010/IND019/IND022`) × 5 markets
  (`MKT008/MKT011/MKT021/MKT040/MKT049`) × 4 queries (`Q1–Q4` GOOGLE_QUERY_V1) ×
  13 `MAPORG13_V1` points × 2 surfaces = **1,560 pre-water jobs**. Generation
  order follows job-generator contract v0.7 (industry → market → surface →
  condition → point).
- **Water gate:** a coordinate whose eligibility ≠ `eligible_land` is **never**
  submitted (COL008 / PRE009). It is still recorded as a planned
  `blocked_structural` job so the denominator reconciles
  (`planned = executable + structurally_excluded`). For the pilot markets this is
  **1,368 executable** (57 eligible coordinates × 3 × 4 × 2) + **192 structurally
  excluded**.
- **Idempotency / resume:** the existing `job_key` + the `run_spike` observation
  short-circuit make a re-run resume where it stopped and never re-pay.
- **Bounded retries:** transport/provider-infra failures only, exponential
  backoff, same job (a new technical attempt, never a new paid scientific call).
  A valid short/empty result (DFS `40102`) is a real observation, never retried.
- **QA telemetry:** `evaluate_wave` reads the wave back and emits **COMPLETE /
  PARTIAL / FAILED / QUARANTINED** under QA/Wave-Acceptance v0.1 (per-wave,
  per-surface, per industry×market×surface stratum ≥20), plus a separate
  financial-reconciliation block. Optionally persisted to `ops.wave_evaluation` +
  `ops.qa_event`.
- **Parallelism (`--workers` N):** work is partitioned by (industry, market,
  surface) and a group is never split across workers, so a Maps `place_id` —
  local to one such cell — is never created by two workers at once. Organic web
  entities (domains/URLs) recur across cells, so their get-or-create is
  concurrency-safe in the repository layer (a single-key advisory lock serializes
  *creation* — deadlock-free — with a unique-constraint + SAVEPOINT recovery
  backstop). Each worker owns its own DB connection + provider client; per-job
  commit/idempotency means a paid task is still POSTed exactly once. DataForSEO's
  ~30 s async-queue latency makes the sequential run ~12 h, ~1 h at 10 workers.

```bash
# Plan only — water gate + accounting, NO writes, NO provider call (also the
# default when --execute is absent):
python -m collector.pilot --dry-run

# Narrow to one cell for a cautious first paid batch:
python -m collector.pilot --dry-run --industries IND010 --markets MKT008 --surfaces maps

# LIVE (MANY paid calls) — gated on --execute AND, on Railway, RUN_PAID_PILOT=1.
# --workers parallelizes the run (partitioned by industry×market×surface so entity
# resolution stays correct); DataForSEO's ~30s async-queue latency makes the
# sequential run ~12h, ~1h at 10 workers:
python -m collector.pilot --execute --workers 10 --persist-evaluation

# Resume an interrupted paid pilot without re-paying for completed jobs
# (idempotency is per wave; on Railway set PILOT_RESUME=1):
python -m collector.pilot --execute --resume --persist-evaluation

# Evaluate an already-collected wave under the QA contract:
python -m collector.pilot --evaluate-only PILOT-3x5-<ts> --persist-evaluation
```

## Full Panel / Sentinel generator (`panel.py`)

Step 10 (ADR-0007, `docs/design/full-panel-sentinel-scheduler-v0_1.md`). Scales
collection from the bounded pilot to the frozen 25×50 universe for **Maps +
Organic**, reading the scope from the manifest instead of hardcoded cells:

- **Two wave kinds**, both a *selection over the frozen universe* (not new
  science): `full_panel` (all 25 industries × 50 markets, monthly) and
  `sentinel` (the fixed `SENTINEL_V1` subset, 5 industries × 10 markets, weekly —
  except the week a Full Panel runs, which is a strict superset and doubles as
  that week's Sentinel).
- **`generate_wave_specs(conn, kind=…)`** loads scope/treatments/points from the
  manifest and reuses the validated `pilot.expand_matrix` expansion verbatim (the
  job-generator v0.7 order industry → market → surface → treatment → point).
- **`plan_wave(conn, kind=…)`** is a **set-based** dry-run: it computes the
  water-gated accounting (planned / executable / structurally_excluded /
  per-surface / strata) + a cost estimate from the versioned price (migration
  023) in one grouped query, applying the same eligibility gate the runner
  applies per spec — no per-job loop at panel scale.
- **Executable counts** (from the production manifest, validated offline): Full
  Panel **130,000 planned → 118,000 executable / 12,000 structurally excluded**
  (≈ $70.80); weekly Sentinel **5,200 → 4,400 / 800** (≈ $2.64).

This module **plans only** — it makes no provider call and no DB write. Live
panel collection runs through the Standard decoupled runner below, behind a
`RUN_PAID_PANEL` gate (the cadence driver, design doc step 3); `panel.py
--execute` is refused.

```bash
# Water-gated accounting + cost estimate (no writes, no provider call):
python -m collector.panel --kind full_panel --dry-run
python -m collector.panel --kind sentinel   --dry-run
```

`scripts/validate_panel.py` applies the migrations to an ephemeral pgvector
Postgres and asserts the generator lengths, the v0.7 order, the water accounting
(130,000 → 118,000/12,000 and 5,200 → 4,400/800), that the set-based plan equals
the per-spec water gate at Sentinel scale, that Sentinel is a strict subset of
the Full Panel, and the cost estimate — all with no paid call.

## Decoupled panel runner (`panel_run.py`)

Step 2 (ADR-0007, design doc §6). The pilot's `PilotRunner` does one synchronous
`task_post` → poll `task_get` per job, which does not scale to the Full Panel
(~118,000 executable jobs). `PanelRunner` uses DataForSEO's Standard **decoupled**
method in three phases:

- **submit** — water-gate, then batched `task_post` (≤100 tasks/POST,
  `dataforseo.MAX_TASKS_PER_POST`), persisting **one paid task per job**
  (`collection_attempt.provider_task_id`);
- **collect** — poll the per-surface `tasks_ready` roster and pull each ready task
  with `task_get_advanced`, then drive the **shared** scientific back half
  (`spike.finalize_collected` — the exact immutable-raw → parse → normalize →
  resolve → cost path the spike and pilot use);
- **reconcile** — a submitted task never seen ready within the collect window is
  recorded as an accounted `terminal_failure` (`collect_timeout`), resumable,
  never re-POSTed.

Guardrails carried over verbatim: immutable raw before normalization; missing ≠
zero (structural coords gated out, `blocked_structural`); **one paid task per
scientific job** with idempotency **at submission** — a job with a committed
observation is skipped, and a job that already carries a submitted
`provider_task_id` is collect-only on resume (never re-POSTed). The QA evaluator
(`pilot.evaluate_wave`) is reused unchanged.

`DataForSEO` gains `task_post_batch` / `tasks_ready` (behind the injectable
`BatchProvider` seam). `PanelRunner` makes **no paid call on its own** — providers
are injected and replaced by fakes offline. The paid CLI + `RUN_PAID_PANEL` gate +
cadence are the driver (design doc step 3, not yet built).

`scripts/validate_panel_run.py` drives a small real scope (IND010 × {MKT008,
MKT011} = 208 planned → 200 executable / 8 excluded) through a fake batch provider
on ephemeral pgvector and asserts: one observation + cost per executable job, one
paid task per job (200 attempts, all with a `provider_task_id`), QA **COMPLETE**;
an idempotent **resume** that re-POSTs nothing (0 new attempts) and collects the
outstanding tasks; and **reconcile** (never-ready → accounted `collect_timeout` →
QA **FAILED**, not QUARANTINED) — all with no paid call.

## Tests

`pytest` — provider and storage are mocked; no test hits an external provider.
`scripts/validate_spike.py` applies the migrations to an ephemeral pgvector
Postgres and runs the full parse→normalize→resolve→cost path for **both** the
Maps and Organic surfaces against synthetic fixtures, asserting the rows land
correctly and that a second run is idempotent (still no paid call).
`scripts/validate_pilot.py` drives the **whole 1,560-job pilot matrix** through
fake providers on an ephemeral schema, asserting the 1,560 → 1,368 / 192 water
accounting, that excluded coordinates produce no observation/cost, that a full
re-run is idempotent, and that the QA evaluator returns **COMPLETE** on a clean
wave and **FAILED** on a provider-failure wave (technical loss, integrity
intact) — all with no paid call.
