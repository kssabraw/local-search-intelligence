# Full Panel / Sentinel scheduler — design v0.1 (Step 10, Maps + Organic)

Companion to `docs/adr/0007-full-panel-sentinel-operation.md`. This is the
engineering design for standing collection up at panel scale on the validated
Stage-1 foundation. Scope: **Maps + Organic only**. No methodology change (see
ADR-0007 → *Not a methodology change*). No paid call runs without owner "go" and
the `RUN_PAID_PANEL` gate.

> Status: **DRAFT for owner sign-off.** Nothing here is built yet. On sign-off it
> becomes the build plan for the manifest-driven wave generator, the Standard
> decoupled DataForSEO adapter mode, and the cadence driver.

---

## 1. What already exists (reused, not rebuilt)

| Concern | Where | Reuse |
|---|---|---|
| `full_panel` / `sentinel` wave kinds | `ops.wave_kind` enum (migration 002) | as-is |
| Wave rows w/ panel + parent links | `ops.collection_wave.panel_subset_id`, `.parent_wave_id` (006) | as-is |
| Cadence declaration | `manifest.surface_config.full_panel_cadence='monthly'`, `sentinel_cadence='weekly'` (019) | as-is |
| Fixed Sentinel membership | `manifest.panel_subset 'SENTINEL_V1'` = 5 ind × 10 mkt (019) | as-is |
| Per-job primitive | `collector.spike.run_spike` | as-is |
| Water gate + missingness | `PilotRunner._record_excluded` / `blocked_structural` | as-is |
| Idempotency + resume | `job_key` + observation short-circuit | as-is |
| Entity resolution | Maps place_id-first / Organic URL-first→domain | as-is |
| Cost ledger | `ops.cost_event` + versioned price `DFS_SERP_STD_TASK_V1` (023) | as-is |
| QA acceptance | `collector.pilot.evaluate_wave` | as-is |

The only genuinely new code is: a **manifest-driven wave generator**, a
**Standard decoupled collection mode** in the DataForSEO adapter, and a **thin
cadence driver**. Everything downstream of "here is an executable job" is the
proven pilot path.

---

## 2. Executable counts (derived from the production manifest)

Read-only from the production Supabase project (`wbqcvqxmhqyspgqsdpsm`),
`MAPORG13_V1` geometry, `GOOGLE_QUERY_V1` treatments (4 queries/industry, both
surfaces):

- **MAPORG13_V1 coordinates, all 50 markets:** 650 total → **590 eligible_land** /
  55 `structural_water_exclusion` / 5 `outside_country_exclusion`.
- **Sentinel 10 markets:** **110 eligible_land** coordinates.

Job count = `eligible_coords_in_scope × n_industries × 4 queries × 2 surfaces`.
This is the same formula the pilot reconciled exactly (57 eligible coords × 3 ind
× 4 q × 2 surf = 1,368 executable ✓).

| Wave | Formula | Executable | Struct. excluded | Planned |
|---|---|---|---|---|
| **Full Panel** | 590 × 25 × 4 × 2 | **118,000** | 12,000 | 130,000 |
| **Sentinel (weekly)** | 110 × 5 × 4 × 2 | **4,400** | 800 | 5,200 |

The manifest's headline "258,000/month" and "9,800/week" are the **all-four-surface**
counts; the in-scope Maps+Organic subset is 118,000 and 4,400 respectively.
`planned = executable + structurally_excluded` is preserved so denominators
reconcile (every structurally-excluded coordinate is still recorded as a
`blocked_structural` planned job, never submitted, never rank 0).

---

## 3. Cost estimate (owner budget confirmation)

Versioned price `DFS_SERP_STD_TASK_V1` = 600 µUSD/task = **$0.0006/task** (the
pilot realized ~$0.000595/job, so this is accurate). Standard queue is the priced
tier; the decoupled method does not change per-task price.

| Wave | Jobs | Cost |
|---|---|---|
| Full Panel (once) | 118,000 | **$70.80** |
| Sentinel (once) | 4,400 | **$2.64** |

**Monthly** (1 Full Panel + 3 Sentinel-only weeks; the Full Panel week's Sentinel
is the Full Panel itself): $70.80 + 3 × $2.64 ≈ **$78.72/month**.

**Annualized** (12 Full Panels + 40 Sentinel-only weeks = 52 − 12 covered weeks):
$849.60 + $105.60 ≈ **$955/year**.

Cost is not the constraint. Throughput and reliability are. **No paid wave runs
without explicit owner "go"**; the graduated first step is one Sentinel wave
(~$2.64).

---

## 4. Wave & cadence model

Sentinel is a **selection over the frozen universe**, not a separate science:

- **Full Panel wave** — `wave_kind='full_panel'`, `panel_subset_id=NULL`, all 25
  industries × 50 markets. Monthly anchor.
- **Sentinel wave** — `wave_kind='sentinel'`, `panel_subset_id=SENTINEL_V1`,
  5 industries × 10 markets. Weekly, **except** the week a Full Panel runs.
- **"Monthly wave doubles as that week's Sentinel"** → in a Full-Panel week we run
  **only** the Full Panel. The Sentinel time series is derived by selecting the
  `SENTINEL_V1` cells from whichever wave covered them (a Full-Panel observation
  *is* the Sentinel observation when they coincide). No double-collection, no
  double-pay. `parent_wave_id` is available to annotate a Sentinel wave that was
  subsumed, if we ever want an explicit marker row; the default is simply "no
  Sentinel wave that week".

Cadence anchoring (proposed, engineering choice, revisable without amendment):
Full Panel on the **1st scheduled run of each calendar month**; Sentinel on every
other scheduled weekly run. Anchor date stored on the wave (`scheduled_for`) so
the series is reconstructable.

---

## 5. Manifest-driven wave generator

Generalize the pilot's hardcoded `expand_matrix` into
`generate_wave_specs(conn, *, kind, methodology_code)`:

- Pulls industries/markets from the manifest — **all** for `full_panel`, or the
  `panel_subset_industry` / `panel_subset_market` membership of `SENTINEL_V1` for
  `sentinel`.
- Pulls treatments from `GOOGLE_QUERY_V1` (4/industry) and points from
  `MAPORG13_V1`, surfaces `{maps, organic}`.
- Emits `PilotJobSpec`-shaped specs in the **job-generator v0.7 order**
  (industry → market → surface → treatment → point) — identical ordering
  contract to the pilot, so the generator is a scope change only.
- The water gate, idempotency, and `blocked_structural` accounting are unchanged
  and applied by the existing runner.

`--dry-run` produces the same accounting shape as today (planned / executable /
structurally_excluded / per-surface / strata) — validated offline against the
real schema before any paid call, exactly as the pilot was.

> The pilot module is `collector/pilot.py`; the panel path will live alongside it
> (working name `collector/panel.py`) reusing `PilotRunner`/`evaluate_wave`.
> Naming/refactor is an implementation detail settled at build time; no behavior
> forks from the validated path.

---

## 6. Throughput — Standard decoupled DataForSEO mode

**Problem.** The pilot's `HttpMapsProvider.run` does `task_post` → poll
`task_get` synchronously per job. For 118,000 jobs at ~30 s/task:

- Sequential: ~984 h (~41 days) — infeasible.
- 10 synchronous workers: ~98 h (~4 days), holding 10 pooler connections the
  whole time — fragile and slow.

**Solution — the DataForSEO Standard method, decoupled:**

1. **Submit phase.** Batch `task_post` up to **100 tasks/POST**. 118,000 jobs →
   1,180 POSTs. Persist each returned provider `task_id` against its `job_key`
   immediately (a new lightweight submission record; the paid task exists exactly
   once and is attributable). Submission is I/O-cheap and fast.
2. **Collect phase.** Poll `tasks_ready`; for each ready task pull it with
   `task_get` and drive the **existing** parse → immutable-raw → normalize →
   resolve → cost path. The provider queue processes tasks in parallel
   server-side, so wall-clock is bounded by provider throughput + a small bounded
   collector pool, not by `n × 30 s`.
3. **Reconcile phase.** Any submitted `task_id` never seen ready within a bounded
   window is a terminal, accounted state (diagnosable, resumable) — never a
   silent drop and never a re-POST (a re-POST would duplicate a paid task).

Guardrail preservation:

- **One paid task per scientific job.** Idempotency moves to *submission*: a
  `job_key` that already has a submitted `task_id` (or a committed observation) is
  never re-POSTed. Resume re-enters the collect phase for outstanding tasks only.
- **Immutable raw still first.** The collect phase writes content-addressed raw
  fail-on-exists before normalization, exactly as today.
- **Missing ≠ zero.** Structural coordinates are still gated out before submission.
- **Batched POST failure is pre-submission-safe per task** only where the whole
  POST demonstrably never reached the provider; partial-batch ambiguity is
  treated as submitted (terminal/accounted, resumable), never re-POSTed.

Connection limits: the collect phase uses a **bounded writer pool on the
transaction pooler (6543)** for short high-frequency writes, rather than holding
many long-lived session-pooler connections (the pilot's 10 session-pooler workers
hit a transient drop; the resilient-worker path tolerated it, but decoupling
removes the exposure). Worker/pool sizes are tunable config, defaulting
conservatively.

Optional later optimization (not v0.1): DataForSEO **postback/pingback** URLs to
push ready tasks instead of polling `tasks_ready`. Deferred — polling is simpler
and sufficient at this scale.

---

## 7. Cadence driver

A thin scheduler that, on each scheduled invocation:

1. Decides `kind` (Full Panel on the monthly anchor, else Sentinel).
2. Mints the wave (`get_or_create_wave` with the right `wave_kind` /
   `panel_subset_id`), or resumes the latest open wave of that kind.
3. Runs generator → submit → collect → `evaluate_wave` (persisted).
4. Emits the QA status; on anything below COMPLETE, surfaces it (no silent
   partials).

Mechanism: a Railway scheduled run invoking the panel entrypoint behind
`RUN_PAID_PANEL=1`. Panel scope/cadence knobs mirror the pilot's env vars
(`PANEL_KIND`, `PANEL_WAVE_CODE`, `PANEL_RESUME`, `PANEL_WORKERS`, …). Exact
scheduling wiring is finalized at build time; the design constraint is that the
driver is **declarative over the manifest** — it never hardcodes the universe.

---

## 8. QA acceptance per wave

`evaluate_wave` is reused unchanged. Every panel wave is evaluated under
QA/Wave-Acceptance v0.1 → COMPLETE / PARTIAL / FAILED / QUARANTINED, plus the
separate financial-reconciliation block, persisted to `ops.wave_evaluation` +
`ops.qa_event`. At panel scale the ≥20-executable per-stratum floor now covers
far more strata (every industry × market × surface with ≥20 eligible jobs);
the COMPLETE gate and thresholds are identical to those the pilot passed.

Production promotion of a wave requires COMPLETE, same as Stage 1. A FAILED or
QUARANTINED wave is diagnosed and resumed (idempotent, no re-pay of collected
jobs), never force-passed.

---

## 9. Build sequence (on sign-off)

1. `collector` manifest-driven generator + `--dry-run` accounting for both wave
   kinds; offline validation on ephemeral pgvector (asserts the 118,000/12,000
   and 4,400/800 splits, generation order, water accounting) — **no paid call**.
2. Standard decoupled adapter mode (batched submit + `tasks_ready`/`task_get`
   collect + reconcile), submission record, idempotency-at-submission; providers
   mocked in tests; offline validation of one-paid-task-per-job and resume.
3. Cadence driver + `RUN_PAID_PANEL` gate + Railway wiring; dry-run on deploy.
4. **Graduated live step (owner "go" required):** one **Sentinel** wave (~4,400
   jobs, ~$2.64) → evaluate COMPLETE → only then a Full Panel.

No step 4 paid activity happens without an explicit owner "go", and even then the
Sentinel wave precedes any Full Panel.

---

## 10. Open engineering questions (non-blocking; defaults chosen)

- **Submission record shape** — reuse `ops.collection_job` + a `job_event`
  (`submitted`, carrying the provider `task_id`) vs. a dedicated column/table.
  Default: a `submitted` job_event with the `task_id` in `details`, no new table.
- **Collect-window bound** — how long a submitted task may stay un-ready before it
  becomes an accounted terminal state. Default: generous (hours), tunable.
- **Full Panel chunking** — run the 118,000 as one wave with internal batching
  (default) vs. shard by industry across days. Default single wave; resume makes
  a multi-day run safe.

These are implementation tickets, not methodology or acceptance decisions.
