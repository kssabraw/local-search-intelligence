-- Migration 028_aio_prevalence_trend
-- SED Local Search Intelligence Platform -- analysis layer v0.2 addition
--
-- Adds ONE read-only view, analysis.aio_prevalence_trend, that turns the
-- per-wave AIO prevalence (already exposed by analysis.aio_overview_prevalence,
-- migration 027) into a CROSS-WAVE longitudinal series: for each grid + query
-- family, prevalence per wave in chronological order, plus the wave-over-wave
-- delta. This is the free "AIO over time" signal the monthly Maps+Organic Full
-- Panel already captures for ~$0 -- the organic SERP returns the `ai_overview`
-- block presence at the plain 600 uUSD price (no load_async add-on), so AIO
-- APPEARANCE trend is measurable without a dedicated (paid) AIO panel.
--
-- NO paid call, NO methodology change, NO new research population/treatment/
-- geometry. Pure CREATE OR REPLACE VIEW over existing normalized tables + the
-- 027 backbone. Design of record: docs/design/analysis-layer-v0_1.md (v0.2 note).
--
-- METHODOLOGY FAITHFULNESS (enforced by construction here):
--   * Missing != zero. Prevalence is share of organic/aio observations carrying a
--     standalone `ai_overview` block; an absent block is a valid negative, exactly
--     as in analysis.aio_overview_prevalence -- this view reuses that definition.
--   * NO composite score. A single outcome family (AIO prevalence) over time.
--   * CROSS-GRID SAFE. The wave-over-wave delta is computed only WITHIN one grid
--     (geometry_code) partition, so the MAPORG13_V1 -> GEOGRID13E_V1 repoint
--     (ADR-0009) never produces a spurious delta across incomparable geometries.
--     The first wave on a grid has a NULL delta (no comparable predecessor), per
--     the HANDOFF cross-grid caveat ("the clean prevalence trend starts from
--     GEOGRID13E_V1 forward").
--   * Query-family aware. AIO prevalence is strongly query-dependent (bare
--     "near me" ~4% vs high-need ~14%), so the series is partitioned by query
--     family; a family-rollup row (query_family = NULL, all_query_families = true)
--     gives the overall per-wave prevalence.
--
-- IDEMPOTENT + RE-RUN SAFE. scripts/railway_run.sh re-applies 019_* and 02[0-9]_*
-- on every deploy; this is a single CREATE OR REPLACE VIEW -- cheap to re-run,
-- no materialized view, no deploy-time rebuild. Research schema stays private.

-- ============================================================================
-- aio_prevalence_trend -- longitudinal AIO prevalence with wave-over-wave delta.
--   Grain: one row per (wave, geometry_code, query_family), PLUS a family-rollup
--   row per (wave, geometry_code) (query_family = NULL, all_query_families=true).
--   Ordered/deltaed within (geometry_code, query-family partition) by the wave's
--   scheduled_for (wave_code as a stable tiebreaker).
-- ============================================================================

create or replace view analysis.aio_prevalence_trend as
with wave_geo as (
  -- The geometry (grid) a wave was collected on, for cross-grid safety. One wave
  -- = one methodology_version = one active grid per surface_group, so min()
  -- collapses to that single grid and never fans out the observation join below.
  select
    j.wave_id,
    min(gv.geometry_code)                                          as geometry_code
  from ops.collection_job j
  join manifest.surface s            on s.surface_id = j.surface_id
  join manifest.market_coordinate mc on mc.coordinate_id = j.coordinate_id
  join manifest.geometry_point gp    on gp.geometry_point_id = mc.geometry_point_id
  join manifest.geometry_version gv  on gv.geometry_version_id = gp.geometry_version_id
  where s.surface_code in ('organic', 'aio')
  group by j.wave_id
),
hits as (
  -- Same "AIO present" definition as analysis.aio_overview_prevalence (027): the
  -- organic SERP carries a standalone ai_overview block (async stub or expanded).
  select distinct observation_id from organic.result where result_type = 'ai_overview'
),
base as (
  select
    od.wave_id,
    od.wave_code,
    w.scheduled_for,
    wg.geometry_code,
    od.query_family,
    (h.observation_id is not null)                                 as aio_present
  from analysis.observation_dim od
  join ops.collection_wave w on w.wave_id = od.wave_id
  join wave_geo wg           on wg.wave_id = od.wave_id
  left join hits h           on h.observation_id = od.observation_id
  where od.surface_code in ('organic', 'aio')
),
agg as (
  select
    wave_id,
    wave_code,
    scheduled_for,
    geometry_code,
    query_family,
    grouping(query_family)                                         as family_rollup,
    count(*)                                                       as observations,
    count(*) filter (where aio_present)                           as aio_present_observations,
    round(count(*) filter (where aio_present)::numeric
          / nullif(count(*), 0), 4)                               as aio_prevalence
  from base
  group by grouping sets (
    (wave_id, wave_code, scheduled_for, geometry_code, query_family),
    (wave_id, wave_code, scheduled_for, geometry_code)
  )
)
select
  wave_code,
  scheduled_for,
  geometry_code,
  query_family,                                                    -- NULL on a family-rollup row
  (family_rollup = 1)                                              as all_query_families,
  observations,
  aio_present_observations,
  aio_prevalence,
  lag(aio_prevalence) over w                                       as prev_wave_prevalence,
  round(aio_prevalence - lag(aio_prevalence) over w, 4)            as prevalence_delta,
  row_number() over w                                              as wave_ordinal
from agg
window w as (
  partition by geometry_code, family_rollup, query_family
  order by scheduled_for, wave_code
);

comment on view analysis.aio_prevalence_trend is
  'Longitudinal AIO prevalence: per (wave, grid, query family) prevalence in chronological order + wave-over-wave delta. Delta is cross-grid safe (partitioned by geometry_code; first wave on a grid = NULL delta). query_family=NULL / all_query_families=true is the overall per-wave rollup. Absence of an ai_overview block = valid negative (missing != zero).';
