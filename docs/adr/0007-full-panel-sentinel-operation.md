# 0007 — Full Panel / Sentinel operation for Maps + Organic (Stage-1 → Step 10)

The bounded 3×5 Stage-1 pilot is COMPLETE under QA/Wave-Acceptance v0.1 and
production-promotable (wave `PILOT-3x5-20260914`: 1,368/1,368 executable
returned, all 30 strata pass, 0 identifier splits, ~$0.8142). The Governing
build sequence step 10 is standing collection up at panel scale: the monthly
**Full Panel** and the weekly fixed **Research Sentinel**, for the Maps and
Organic surfaces only, on the already-validated shared foundation — **without
silently changing methodology**.

This ADR records the operational decisions for that step. The companion design
doc `docs/design/full-panel-sentinel-scheduler-v0_1.md` carries the mechanics,
the executable counts, and the cost estimate.

## Context

Two facts shape the decision:

1. **The cadence/panel model already exists in the frozen schema** (migrations
   `002`/`004`/`006`/`019`). `ops.wave_kind` already has `full_panel` and
   `sentinel`; `ops.collection_wave` already carries `panel_subset_id` and
   `parent_wave_id`; `manifest.surface_config` already declares
   `full_panel_cadence='monthly'` / `sentinel_cadence='weekly'`; and
   `manifest.panel_subset 'SENTINEL_V1'` is already seeded (5 industries × 10
   markets). So standing up cadence needs **no new migration** — only a
   manifest-driven wave generator and a thin cadence driver.

2. **The pilot's per-task synchronous collection does not scale.** The pilot
   drove one DataForSEO `task_post` → poll `task_get` per job (a Live-like
   pattern). The in-scope Full Panel is **118,000 executable Maps+Organic jobs**;
   at ~30 s/task even 10 workers is ~4 days of wall-clock and holds 10 pooler
   connections open the whole time.

## Decisions

1. **Sentinel is a fixed *selection*, never a second collection.** In a week that
   also runs the Full Panel, the Full Panel (a strict superset of the Sentinel
   cells) *is* that week's Sentinel; we do **not** additionally collect a
   Sentinel wave. The Sentinel longitudinal series is assembled by selecting the
   `SENTINEL_V1` cells from whichever wave covered them. This is the
   drift-safe reading of "the monthly wave doubles as that week's Sentinel": no
   double-collection, no double-pay, and Sentinel stays a subset of the frozen
   universe rather than a parallel panel with its own semantics.

2. **Adopt DataForSEO's Standard decoupled collection method** — batched
   `task_post` (≤100 tasks/POST) then POST-all-then-collect via `tasks_ready` +
   `task_get` — for panel-scale waves. Submission and collection decouple so the
   provider queue processes in parallel; wall-clock is bounded by provider-side
   concurrency and a small bounded collector pool, not by `n_jobs × 30 s`. The
   endpoint, the locked provider settings (`DFS_MAPS_V2` `14z`; Organic
   `,200`), the result depth (10), and the immutable-raw / normalize / resolve /
   cost path are all **unchanged** — this is an adapter transport mode, not a
   science change.

3. **Reuse the validated harness end to end.** The water gate, the deterministic
   `job_key` idempotency + resume, entity resolution, the cost ledger, and the
   `evaluate_wave` QA evaluator (COMPLETE/PARTIAL/FAILED/QUARANTINED + financial
   reconciliation) are carried over verbatim. Step 10 generalizes the pilot's
   hardcoded `expand_matrix` into a manifest-driven generator; it does not
   re-implement collection.

4. **A distinct closed paid gate.** Panel runs are gated behind a new
   `RUN_PAID_PANEL` env flag (default `0`, independent of `RUN_PAID_SPIKE` /
   `RUN_PAID_PILOT`), and no paid panel wave runs without explicit owner "go".
   The graduated first live step is a **single Sentinel wave** (4,400 jobs,
   ~$2.64), not a cold Full Panel.

## Scope & mechanics

- **In scope:** Maps + Organic collection + entity resolution + cost/QA telemetry
  at Full Panel and Sentinel cadence. Enrichment, findings, Client Mode, AIO, and
  ChatGPT stay out of scope (AIO/ChatGPT remain behind their ADR-0005 capture
  probes).
- **Executable counts (Maps + Organic, from the production manifest):** Full
  Panel **118,000** executable / 12,000 structurally excluded / 130,000 planned;
  weekly Sentinel **4,400** executable / 800 excluded / 5,200 planned. Derivation
  in the design doc.
- **No migration** is required for the core model. If operation later surfaces a
  genuine need (e.g. a cadence-anchor table), it will be its own reviewed
  migration, called out as such.

## Consequences

- Standing collection reuses a foundation already proven COMPLETE on real data,
  so the risk surface is throughput + reliability, not correctness.
- The Standard decoupled mode changes only *how* paid tasks are submitted and
  collected; every guardrail (immutable append-only raw, missing ≠ zero, a
  technical retry never duplicating a paid call, one paid POST per scientific
  job) is preserved. A batched POST is still exactly one paid task per job, and
  resume still short-circuits on a committed observation.
- Because Sentinel is a selection, the weekly time series and the monthly Full
  Panel remain mutually consistent by construction — a Sentinel-week
  observation is literally a Full-Panel observation when the two coincide.

## Not a methodology change

Population, treatment, estimand, cadence, geometry, result depth, replicate
behavior, missingness semantics, and enrichment eligibility are all exactly as in
Manifest v1.0. This ADR records *operational* decisions (collection transport,
wave orchestration, gating) — engineering, not methodology. Any future change to
a frozen dimension would require its own explicit amendment.
