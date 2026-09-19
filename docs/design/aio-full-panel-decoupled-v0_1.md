# Full AIO panel — decoupled collection + full-scope selection v0.1

Status: **BUILT + offline-validated (no paid call)**. Makes the full 25×50 ×
10-condition × 13-point AIO panel (**148,750 executable**, ADR-0008 + ADR-0009)
runnable efficiently, on explicit owner "go" behind the `RUN_PAID_AIO` gate.

## Why

The graduated first paid AIO wave (`AIO-20260918`, 30 tasks) rode
`pilot.PilotRunner` — one synchronous `task_post` → poll `task_get` per job. That is
fine at ~30 tasks but does not scale to 148,750: each job blocks on the async
AI-Overview load before the next starts. The Maps/Organic Full Panel hit the same
wall at ~118k and solved it with DataForSEO's Standard **decoupled** method
(batch `task_post` ≤100/POST, then collect each task by its stored id). This change
brings that same efficient path to the AIO surface, and fixes a scope gap:
`AIO_ALL_CONDITIONS=1` + `AIO_POINTS_FULL=1` alone only widens the **3×5 pilot
cells** (1,950 tasks) because the driver defaults industries/markets to pilot — the
full panel needs every industry × every market.

## What

- **`collector/aio_panel_run.py` — `AioPanelRunner(panel_run.PanelRunner)`.** A
  subclass of the validated Maps/Organic decoupled runner. It inherits the entire
  submit → collect → reconcile machinery, the water gate, one-paid-task-per-job
  idempotency, the parallel cell-partitioned collect, and the QA evaluator, and
  overrides only the surface seams:
  - wave kind `ad_hoc`, wave-code prefix `AIO`;
  - manifest context resolves against the `AIO_QUERY_V1` treatment set;
  - the request sets `load_async_ai_overview` (DFS_AIO_V2, migration 025);
  - the scientific back half is the two-track `spike.finalize_aio` (one observation
    carrying the `ai_overview` subtree → `aio.*` **and** the co-returned organic +
    Local-Pack context). KG-MID / web-entity split-safety under parallel collect is
    handled inside `finalize_aio` (ordered web-then-business advisory pre-locks).
  There is **no parallel per-surface collection stack** (parent-PRD rule): the base
  `PanelRunner` gained small behavior-preserving hooks (`_build_request`, `_finalize`,
  `_allowed_kinds`, `_wave_prefix`, `_treatment_set`) whose defaults reproduce the
  Maps/Organic path byte-for-byte (proven: `validate_panel_run.py` unchanged).
- **`collector/aio_run.load_full_panel_specs(conn)`** — the full panel matrix: every
  industry × every market (from the frozen manifest, never hardcoded) × all 10
  `AIO_QUERY_V1` conditions × the active AIO geometry's points (resolved from
  `surface_config`, so it tracks the ADR-0009 `GEOGRID13E_V1` repoint). 162,500
  planned → **148,750 executable** after the water gate.
- **`collector/aio_driver.py`** — `--full-panel` (implies the full scope + a per-month
  wave code `AIO-<YYYYMM>`, matching `FULLPANEL-<YYYYMM>`), plus decoupled knobs
  `--batch-size` / `--poll-interval` / `--collect-timeout` (mirroring `panel_driver`).
  `run_aio_collection` now drives `AioPanelRunner`. The `RUN_PAID_AIO` gate is
  unchanged (default closed; paid run needs `--execute` AND the gate).
- **`scripts/railway_run.sh`** — `AIO_FULL_PANEL=1` → `--full-panel`, plus
  `AIO_BATCH_SIZE` / `AIO_POLL_INTERVAL` / `AIO_COLLECT_TIMEOUT`.

## Guardrails (unchanged, inherited)

Immutable append-only raw before normalization; missing ≠ zero (structural
coordinates gated out, never submitted); ONE paid task per job (idempotency at
submission — a committed observation short-circuits, a submitted-but-uncollected task
is collect-only on resume, never re-POSTed); a valid short/empty result is a real
observation, never retried; QA/Wave-Acceptance evaluation reused unchanged
(anything below COMPLETE exits non-zero). Resume across the many collect passes a
148,750-task run needs is by re-invoking the same monthly wave code — zero re-pay.

## Validation (offline, no paid call, no network)

- `scripts/validate_aio_run.py` (now decoupled): a clean wave submits (batch) then
  collects → QA COMPLETE; a concurrent 5-worker run with the same cross-cell business
  KG-MID in every cell mints exactly ONE `business_location` (0 identifier split) and
  a clean web-entity graph (0 duplicate domains/URLs); idempotent resume re-collects /
  re-pays nothing; the water gate never submits a structural coordinate; and the
  **full-panel scope resolves to 162,500 planned / 148,750 executable**. ALL PASS.
- `scripts/validate_panel_run.py` (Maps/Organic decoupled runner) still passes —
  proving the base runner's behavior is unchanged by the extracted hooks. (Its
  5-worker concurrent stress case asserts exactly 0 transient collect faults and can
  flake on an ephemeral single-Postgres; it passes on re-run — a property of the
  fault-tolerant concurrent collector, not of this change.)
- `pytest` (129) + `validate_migrations` (001–028) + the other ephemeral validators
  all pass.

## To run (owner "go"; gate closed by default)

On the Railway `production` service, from `main`:
`RUN_PAID_AIO=1`, `AIO_FULL_PANEL=1`, `AIO_WORKERS=8` (optionally `AIO_BATCH_SIZE`,
`AIO_COLLECT_TIMEOUT`), redeploy → the wave `AIO-<YYYYMM>` runs (~$190 at the
measured ~1,280 µUSD/task). Re-close (`RUN_PAID_AIO=0`) after. Resume an interrupted
run by redeploying with the gate open and the same month (or `AIO_RESUME=1`) — zero
re-pay. The recurring monthly **scheduling** mechanism (auto vs on-demand) is a
separate owner decision, deferred until after the first full run.
