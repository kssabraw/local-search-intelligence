# Research analysis layer v0.1 — coverage / distance-decay / dominance / cross-surface overlap

Status: **BUILT + offline-validated + applied to production** (read-only views;
migration `027_analysis_layer_v0_1.sql`). No paid call, no methodology change, no
data mutation. Turns the immutable outcome panel into rebuildable research rollups.

Governs the first pass of *analysis* over the Maps + Organic Full Panel
(`FULLPANEL-202609-G13E`, 119,000 executable observations) and the graduated AIO
wave (`AIO-20260918`). Pairs with the parent PRD (outcome families kept separate;
no composite score) and the Maps/Organic child PRD (coverage vs rank vs reach,
distance/proximity).

## What this is / is not

- **Is:** a `analysis` schema of pure `CREATE OR REPLACE VIEW`s + one immutable
  `analysis.norm_domain()` function, reading only the normalized outcome tables
  (`maps.*`, `organic.*`, `aio.*`, `core.*`, `manifest.*`). Every view is
  rebuildable from raw; none is a source of truth.
- **Is not:** a new measurement, a predictor/enrichment layer (none is collected —
  out of scope, `docs/design/enrichment-pricing-probe-v0_1.md`), or a composite
  visibility score. It re-reads what was already parsed deterministically upstream;
  no LLM, no re-extraction.

## Methodology faithfulness (enforced by construction)

- **No composite visibility score**, within or across surfaces. Each view carries a
  single outcome family (coverage / rank / overlap / prevalence) — never blended.
- **Missing ≠ zero.** Coverage denominators use *eligible* points
  (`analysis.market_eligible_points`, derived from the wave's own eligible jobs);
  structurally-excluded coordinates carry no observation and are never counted as
  rank 0 / no-visibility. An absent AIO block is a valid negative, not a null hole.
- **Outcome-only.** No backlink/on-page/GBP-audit/NAP/review-velocity field is read.
- **Canonical grains.** Maps dominance/retention key on the resolved
  `business_location` (place_id-first, ADR-0003); Organic/overlap key on the
  normalized web domain (URL-first→domain, contract §14). `analysis.norm_domain()`
  mirrors `collector/normalize.py` `normalize_domain()` byte-for-byte (validated),
  so a maps GBP-website domain and an organic domain compare on the same key.

## The views (migration `027`)

| View | Grain | Outcome family | Notes |
|---|---|---|---|
| `norm_domain(text)` | — | — | immutable; mirrors the collector's domain normalization |
| `observation_dim` | 1 row / observation | dimension backbone | wave·surface·industry·market·coordinate·ring·query |
| `market_eligible_points` | wave × market | denominator | eligible points from the wave's own jobs |
| `observation_result_count` | 1 row / observation | helper | per-obs result count (set-based) |
| `coverage_summary` | wave·surface·industry·market·query | **coverage** | eligible vs observed points, avg results/point |
| `maps_entity_dominance` | wave·industry·market·business | **dominance** | appearances, distinct points, grid coverage_share, best/avg rank |
| `organic_domain_dominance` | wave·industry·market·domain | **dominance** | organic-only; coverage_share, ranks |
| `ring_profile` | wave·surface·industry·ring | **distance-decay (descriptive)** | avg result-set size + Maps rating/review depth by ring |
| `maps_center_retention` | wave·industry·market·query·ring | **distance-decay (set)** | fraction of the CENTER pack still present at each outer ring |
| `maps_organic_overlap` | wave·industry·market·query·point | **cross-surface overlap** | Local-Pack website domains vs Organic domains |
| `aio_overview_prevalence` | wave·industry·market·query·ring | **AIO prevalence** | share of organic obs carrying an `ai_overview` block |
| `aio_organic_source_overlap` | 1 row / AIO observation | **AIO↔organic overlap** | AIO sidebar sources vs co-returned organic; SearchViewer/GBP + inline links excluded |
| `aio_prevalence_trend` *(028)* | wave × grid × query family (+ family rollup) | **AIO prevalence over time** | chronological prevalence + wave-over-wave delta; cross-grid safe |

### Semantics notes

- **Coverage denominator.** `market_eligible_points` counts distinct eligible
  coordinates *in the wave itself* — the set actually collected equals the eligible
  set for that wave's geometry, so coverage never divides by an assumed count. For a
  complete Full Panel `observed_points == eligible_points` (coverage 1.0); the view
  still surfaces any short-fall honestly.
- **`maps_center_retention`** is the true distance-decay signal: for each non-center
  point it computes |businesses ∩ center| / |center|, averaged per ring within a
  (industry, market, query) cell. Low retention at larger rings = the local result
  set diverges quickly with distance.
- **`maps_organic_overlap`** joins the *separate* Maps and Organic observations at
  the same (wave, industry, market, query, coordinate). The Maps side is the GBP
  *website* domain (`norm_domain(url_raw)`); the Organic side is the ranked domain.
  This is the only cross-surface link available from outcome-only data (Maps mints
  `business_location`, Organic mints `web_domain`; they share no key otherwise).
- **`aio_overview_prevalence`** reads prevalence straight from the organic SERP
  (`organic.result.result_type = 'ai_overview'`), so it works at *full-panel scale*
  — not only from a dedicated AIO wave. On the Maps/Organic profile (no
  `load_async_ai_overview`) the block is usually an async stub; presence is still a
  valid prevalence signal (ADR-0008 §2).
- **`aio_organic_source_overlap`** counts only reference-card web sources with a
  publisher domain. SearchViewer/GBP inline references (no publisher domain) are
  business appearances, not web sources, and are excluded — they belong to
  `aio.business_appearance`/`aio.destination`.

## v0.2 addition — `aio_prevalence_trend` (migration `028`)

The longitudinal view of AIO *appearance*, the owner's "AIO / engine over time"
goal. It reads the same `ai_overview`-block prevalence as
`aio_overview_prevalence`, then lays the waves out chronologically and computes the
wave-over-wave delta — so the free, ~$0 signal the monthly Maps+Organic Full Panel
already captures (`organic.result.result_type = 'ai_overview'` at the plain 600 µUSD
price, no `load_async` add-on) becomes a trend without any paid AIO panel.

- **Grain.** One row per (`wave_code`, `geometry_code`, `query_family`), plus a
  family-rollup row per (`wave_code`, `geometry_code`) with `query_family = NULL` /
  `all_query_families = true` for the whole-wave prevalence. AIO prevalence is
  strongly query-dependent (bare "near me" ~4 % vs high-need ~14 %), so the default
  grain keeps families separate; the rollup gives the headline per-wave number.
- **Cross-grid safe (the key methodology guard).** The `prevalence_delta` /
  `prev_wave_prevalence` / `wave_ordinal` window is partitioned by `geometry_code`,
  so the `MAPORG13_V1 → GEOGRID13E_V1` repoint (ADR-0009) never yields a spurious
  delta across incomparable geometries. The first wave on a grid has a **NULL**
  delta — exactly the HANDOFF caveat that "the clean prevalence trend starts from
  `GEOGRID13E_V1` forward". `geometry_code` is derived per wave from its own
  organic/aio coordinates (one wave = one grid), never assumed.
- **Ordering.** Within a (grid, query-family) partition, waves order by
  `scheduled_for` (with `wave_code` as a stable tiebreaker).
- **Missing ≠ zero.** Prevalence denominator = organic/aio observations that
  returned; an absent `ai_overview` block is a valid negative, identical to
  `aio_overview_prevalence`.
- **Cadence note.** Because prevalence rides the plain monthly Maps+Organic panel,
  this trend fills in for free each month even if the paid full AIO panel is never
  run; a paid AIO wave (`AIO-<date>`) also appears in the series (its own
  `query_family` values, `AIO_QUERY_V1`), separate from the Maps/Organic
  (`GOOGLE_QUERY_V1`) families. Engine *content* drift (citation/business churn,
  body-vs-sidebar, GBP-embed rate) still needs the loaded body and is out of scope
  for this appearance-only view.

## Performance & the deploy contract

- Idempotent + re-run-safe: everything is `CREATE SCHEMA IF NOT EXISTS` /
  `CREATE OR REPLACE FUNCTION` / `CREATE OR REPLACE VIEW`. `scripts/railway_run.sh`
  re-applies `02[0-9]_*` on every deploy; migration `027` re-runs cheaply and builds
  no heavy artifact at deploy time (no materialized views — no stale-refresh footgun,
  no deploy-time rebuild over 1.4 M rows).
- The full-panel-scale views (`coverage_summary`, `ring_profile`,
  `aio_overview_prevalence`) are written **set-based** (one GROUP-BY scan per result
  table) rather than per-observation correlated subqueries, so they stay tractable.
- Even so, full-panel aggregations over ~1.4 M result rows exceed a 60 s
  statement window. Consumers should either **filter by `wave_code`** and a
  dimension, or run with a raised `statement_timeout` (the notebook sets
  `statement_timeout = 600s` on a direct connection). The session pooler's default
  timeout is the same constraint noted in `HANDOFF.md`. If a permanent fast path is
  wanted later, an analyst can `CREATE MATERIALIZED VIEW … AS SELECT * FROM
  analysis.<view> WHERE wave_code = …` on demand and `REFRESH` after a new wave — an
  explicit, opt-in cost, deliberately not baked into the deploy.

## Validation

`scripts/validate_analysis_views.py` applies migrations `001`–`028` to an ephemeral
pgvector Postgres, builds a small hand-computable panel through the **production
write path** (`collector.repository.Repo` → real entity resolution), and asserts
every view's rollup (54 checks, ALL PASS): `norm_domain` parity with the collector,
`027` re-run safety, coverage math, dominance grain + coverage_share, ring profile,
center-retention set math, Maps↔Organic overlap, AIO prevalence (absence = valid
negative), AIO↔organic source overlap (SearchViewer/inline exclusion), and — for
`028` — the cross-wave prevalence trend: a two-wave same-grid series with the correct
wave-over-wave delta and ordinal, a family-rollup row, and cross-family/cross-grid
partition isolation. No paid call, no network.

## Headline findings (see the notebook + `analysis/README.md`)

Computed on production (2026-09-18/19):

- **Coverage:** 119,000 / 119,000 eligible observations returned (100%); 595
  eligible points × 25 industries × 4 queries × 2 surfaces.
- **Distance-decay (Maps, "near me"):** the center Local-Pack diverges fast — ~18–22 %
  of center businesses remain at 3 mi, ~7–9 % at 4 mi, ~3–4 % at 5 mi (consistent
  across locksmith / urgent-care / Chinese-restaurant). Confirms strong
  per-coordinate proximity signal and the 13-point grid's spatial resolution.
- **Maps↔Organic overlap:** only ~16 % of Local-Pack business websites also rank
  organically at the same point (locksmith Q1) — the two surfaces reward largely
  different players (proximate GBP businesses vs web publishers).
- **AIO prevalence (full panel):** a standalone AI Overview appears in **9.86 %** of
  near-me local SERPs — 4.3 % for bare "near me", rising to 9.7 % (in-[CITY]),
  11.7 % ("best"), 13.7 % (high-need). AIO is rare and query-dependent.
- **AIO↔organic redundancy:** when a triggered AIO cites web sources, they are
  ~100 % already in the co-returned organic top results (small n); AIO's *independent*
  signal is the GBP carousel (SearchViewer), not web citations.
- **Implication for the AIO-widen go/no-go:** AIO is rare and its web layer is
  largely redundant with organic already collected; its only independent contribution
  is GBP-carousel embedding. This argues for a **targeted** widen (high-AIO query
  classes / GBP-embedding capture) rather than a full 148,750-task panel — or
  deferral — pending the notebook's full-panel generalization.
