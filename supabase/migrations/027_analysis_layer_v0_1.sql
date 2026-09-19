-- Migration 027_analysis_layer_v0_1
-- SED Local Search Intelligence Platform -- research analysis layer v0.1
--
-- Turns the immutable outcome panel (Maps + Organic + the co-returned AIO context)
-- into rebuildable RESEARCH ROLLUPS: coverage, distance-decay by ring, entity
-- dominance, Maps<->Organic overlap, and AIO<->organic overlap. These are pure
-- read-only views over the normalized tables -- NEVER a source of raw truth, always
-- rebuildable from raw (CLAUDE.md hard rule). No methodology change: this file adds
-- no research population/treatment/geometry, it only reads what was collected.
--
-- Design of record: docs/design/analysis-layer-v0_1.md.
--
-- METHODOLOGY FAITHFULNESS (enforced by construction here):
--   * NO composite visibility score, within or across surfaces. Each rollup keeps a
--     single raw outcome family (coverage / rank / overlap / prevalence) separate.
--   * Missing != zero. Coverage denominators use ELIGIBLE points (from the wave's own
--     eligible jobs); structurally-excluded coordinates are never counted as rank 0 /
--     no-visibility. An absent AIO block is a valid negative, not a null hole.
--   * Outcome-only. No enrichment/predictor is read (none is collected yet).
--   * Provider parsing already happened deterministically upstream; these views do no
--     re-extraction and no LLM work.
--
-- IDEMPOTENT + RE-RUN SAFE. scripts/railway_run.sh re-applies 019_* and 02[0-9]_*
-- on every deploy, so everything here is CREATE SCHEMA IF NOT EXISTS / CREATE OR
-- REPLACE FUNCTION / CREATE OR REPLACE VIEW -- cheap to re-run and never rebuilds a
-- heavy artifact at deploy time (no materialized views; consumers materialize on
-- demand). Research schemas are private: no anon/authenticated grants.

create schema if not exists analysis;

-- ============================================================================
-- 0) Deterministic domain normalization -- MUST mirror collector/normalize.py
--    normalize_domain(): lower-case bare host, strip scheme / userinfo / port /
--    surrounding dots / a single leading 'www.'. Public-suffix registered-domain
--    logic is intentionally out of scope (same as the collector), so the normalized
--    host doubles as the registrable key. IMMUTABLE so it can index/inline.
-- ============================================================================

create or replace function analysis.norm_domain(raw text)
returns text
language sql
immutable
returns null on null input
as $$
  select nullif(
    regexp_replace(                                   -- strip a single leading 'www.'
      btrim(                                           -- strip surrounding dots
        split_part(                                    -- strip ':port'
          split_part(                                  -- take host after any 'userinfo@'
            split_part(                                -- take netloc before first '/'
              regexp_replace(lower(btrim(raw)),        -- strip 'scheme://'
                             '^[a-z][a-z0-9+.-]*://', ''),
              '/', 1),
            '@', -1),
          ':', 1),
        '.'),
      '^www\.', ''),
    '');
$$;

comment on function analysis.norm_domain(text) is
  'Deterministic registrable-host normalization mirroring collector/normalize.py normalize_domain (lowercase host; strip scheme/userinfo/port/dots/leading www.).';

-- ============================================================================
-- 1) observation_dim -- the backbone: ONE row per returned observation, fully
--    dimensioned. Only executable (eligible) coordinates have an observation, so
--    this view is naturally scoped to the science; excluded coordinates carry no
--    observation and are handled as denominators elsewhere (missing != zero).
-- ============================================================================

create or replace view analysis.observation_dim as
select
  o.observation_id,
  w.wave_id,
  w.wave_code,
  w.wave_kind,
  s.surface_code,
  i.industry_id,
  i.industry_code,
  i.industry_name,
  m.market_id,
  m.market_code,
  m.city,
  m.state_region,
  j.coordinate_id,
  gp.point_code,
  gp.point_label,
  gp.distance_miles                                    as ring_miles,
  gp.bearing_deg,
  (gp.distance_miles = 0)                              as is_center,
  j.planned_eligibility,
  t.treatment_set_code,
  t.treatment_code,
  t.family                                             as query_family,
  t.core_query_class,
  t.exact_template                                     as query_text,
  o.observation_state,
  o.observed_at
from ops.observation o
join ops.collection_job j       on j.job_id = o.job_id
join ops.collection_wave w      on w.wave_id = j.wave_id
join manifest.surface s         on s.surface_id = j.surface_id
join manifest.industry i        on i.industry_id = j.industry_id
join manifest.market m          on m.market_id = j.market_id
join manifest.surface_treatment st on st.surface_treatment_id = j.surface_treatment_id
join manifest.treatment t       on t.treatment_id = st.treatment_id
left join manifest.market_coordinate mc on mc.coordinate_id = j.coordinate_id
left join manifest.geometry_point gp    on gp.geometry_point_id = mc.geometry_point_id;

comment on view analysis.observation_dim is
  'One fully-dimensioned row per returned observation (wave/surface/industry/market/coordinate/ring/query). Backbone for the analysis rollups.';

-- Per-(wave, market) ELIGIBLE-point denominator, derived from the wave''s own jobs
-- (the set actually collected == the eligible set for that wave''s geometry). Used as
-- the coverage denominator so coverage never divides by an assumed count.
create or replace view analysis.market_eligible_points as
select
  w.wave_id,
  w.wave_code,
  j.market_id,
  count(distinct j.coordinate_id) filter (where j.planned_eligibility = 'eligible_land') as eligible_points
from ops.collection_wave w
join ops.collection_job j on j.wave_id = w.wave_id
group by w.wave_id, w.wave_code, j.market_id;

comment on view analysis.market_eligible_points is
  'Eligible-point count per (wave, market), from the wave''s own eligible jobs -- the coverage denominator (missing != zero).';

-- ============================================================================
-- 2) coverage_summary -- grid fill per (wave, surface, industry, market, query):
--    of the market''s eligible points, how many returned an observation, and how
--    many results/distinct entities on average. Coverage of the PANEL (not of a
--    single client), keeping coverage separate from rank.
-- ============================================================================

-- Per-observation result counts, computed set-based (one GROUP BY scan per result
-- table) rather than a correlated subquery per observation -- so the view stays fast
-- at full-panel scale. An observation_id is unique to one surface, so the two LEFT
-- JOINs never both hit for the same row.
create or replace view analysis.observation_result_count as
select
  od.observation_id, od.wave_id, od.wave_code, od.surface_code, od.industry_code,
  od.market_id, od.market_code, od.treatment_code, od.query_family, od.coordinate_id,
  od.ring_miles,
  case od.surface_code when 'maps' then coalesce(mc.c, 0)
                       else coalesce(oc.c, 0) end                     as result_count
from analysis.observation_dim od
left join (
  select observation_id, count(*) as c
  from maps.result where provider_item_type = 'maps_search' group by observation_id
) mc on mc.observation_id = od.observation_id
left join (
  select observation_id, count(*) as c
  from organic.result where result_type = 'organic' group by observation_id
) oc on oc.observation_id = od.observation_id;

create or replace view analysis.coverage_summary as
select
  orr.wave_code,
  orr.surface_code,
  orr.industry_code,
  orr.market_code,
  orr.treatment_code,
  orr.query_family,
  mep.eligible_points,
  count(distinct orr.coordinate_id)                                   as observed_points,
  round(count(distinct orr.coordinate_id)::numeric
        / nullif(mep.eligible_points, 0), 4)                          as coverage_rate,
  count(distinct orr.observation_id)                                  as observations,
  count(*) filter (where coalesce(orr.result_count,0) > 0)            as nonempty_observations,
  round(avg(orr.result_count)::numeric, 3)                            as avg_results_per_point,
  sum(orr.result_count)                                               as total_result_rows
from analysis.observation_result_count orr
join analysis.market_eligible_points mep
  on mep.wave_id = orr.wave_id and mep.market_id = orr.market_id
group by
  orr.wave_code, orr.surface_code, orr.industry_code, orr.market_code,
  orr.treatment_code, orr.query_family, mep.eligible_points;

comment on view analysis.coverage_summary is
  'Panel grid-fill per (wave, surface, industry, market, query): eligible vs observed points, coverage_rate, avg results/point. Coverage kept separate from rank.';

-- ============================================================================
-- 3) maps_entity_dominance -- which canonical BUSINESSES dominate a cell. Grain is
--    the resolved business_location (ADR-0003, place_id-first); appearances that did
--    not resolve to a canonical business are excluded (they can''t be attributed).
--    coverage_share = distinct eligible points where the business appears / market
--    eligible points -- the business''s grid footprint (Effective Ranking Radius).
-- ============================================================================

create or replace view analysis.maps_entity_dominance as
with appear as (
  select
    od.wave_id, od.wave_code, od.industry_code, od.market_id, od.market_code,
    od.coordinate_id, od.treatment_code,
    lr.resolved_entity_id                                        as entity_id,
    r.rank_absolute
  from analysis.observation_dim od
  join maps.result r
    on r.observation_id = od.observation_id and r.provider_item_type = 'maps_search'
  join core.latest_resolution lr
    on lr.observed_object_id = r.observed_object_id
   and lr.resolution_state in ('resolved','probable_match')
  where od.surface_code = 'maps'
)
select
  a.wave_code,
  a.industry_code,
  a.market_code,
  a.entity_id,
  e.operational_label                                            as business_name,
  count(*)                                                       as appearances,
  count(distinct a.coordinate_id)                                as distinct_points,
  count(distinct a.treatment_code)                               as distinct_queries,
  round(count(distinct a.coordinate_id)::numeric
        / nullif(mep.eligible_points, 0), 4)                     as coverage_share,
  min(a.rank_absolute)                                           as best_rank,
  round(avg(a.rank_absolute)::numeric, 3)                        as avg_rank
from appear a
join core.entity e on e.entity_id = a.entity_id
join analysis.market_eligible_points mep
  on mep.wave_id = a.wave_id and mep.market_id = a.market_id
group by a.wave_code, a.industry_code, a.market_code, a.entity_id, e.operational_label, mep.eligible_points;

comment on view analysis.maps_entity_dominance is
  'Canonical-business dominance per (wave, industry, market): appearances, distinct points/queries, grid coverage_share, best/avg rank. Grain = resolved business_location (place_id-first).';

-- ============================================================================
-- 4) organic_domain_dominance -- which WEB DOMAINS dominate organic results in a
--    cell. Grain is the normalized domain taken directly off the organic result
--    (URL-first->domain, contract Sec.14; organic never mints a business). Restricted
--    to result_type = 'organic' (the true web results), excluding local_pack/PAA/etc.
-- ============================================================================

create or replace view analysis.organic_domain_dominance as
with appear as (
  select
    od.wave_id, od.wave_code, od.industry_code, od.market_id, od.market_code,
    od.coordinate_id, od.treatment_code,
    analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) as domain,
    r.rank_absolute
  from analysis.observation_dim od
  join organic.result r
    on r.observation_id = od.observation_id and r.result_type = 'organic'
  where od.surface_code = 'organic'
    and analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) is not null
)
select
  a.wave_code,
  a.industry_code,
  a.market_code,
  a.domain,
  count(*)                                                       as appearances,
  count(distinct a.coordinate_id)                                as distinct_points,
  count(distinct a.treatment_code)                               as distinct_queries,
  round(count(distinct a.coordinate_id)::numeric
        / nullif(mep.eligible_points, 0), 4)                     as coverage_share,
  min(a.rank_absolute)                                           as best_rank,
  round(avg(a.rank_absolute)::numeric, 3)                        as avg_rank
from appear a
join analysis.market_eligible_points mep
  on mep.wave_id = a.wave_id and mep.market_id = a.market_id
group by a.wave_code, a.industry_code, a.market_code, a.domain, mep.eligible_points;

comment on view analysis.organic_domain_dominance is
  'Organic web-domain dominance per (wave, industry, market): appearances, distinct points/queries, grid coverage_share, best/avg rank. result_type=organic only; domain per contract Sec.14.';

-- ============================================================================
-- 5) ring_profile -- descriptive distance-decay: per (wave, surface, industry,
--    ring_miles), the average result-set size and (Maps) the average top-result
--    rating/review depth. Shows whether outer rings surface systematically different
--    result sets than the center.
-- ============================================================================

create or replace view analysis.ring_profile as
with per_obs as (
  select
    od.wave_code, od.surface_code, od.industry_code, od.ring_miles,
    case od.surface_code when 'maps' then coalesce(mc.c, 0)
                         else coalesce(oc.c, 0) end                as results,
    mc.ar as avg_rating, mc.rc as avg_review_count
  from analysis.observation_dim od
  left join (
    select observation_id, count(*) as c, avg(rating) as ar, avg(review_count) as rc
    from maps.result where provider_item_type = 'maps_search' group by observation_id
  ) mc on mc.observation_id = od.observation_id
  left join (
    select observation_id, count(*) as c
    from organic.result where result_type = 'organic' group by observation_id
  ) oc on oc.observation_id = od.observation_id
  where od.ring_miles is not null
)
select
  wave_code,
  surface_code,
  industry_code,
  ring_miles,
  count(*)                                                       as observations,
  round(avg(results)::numeric, 3)                               as avg_results_per_point,
  round(avg(avg_rating)::numeric, 3)                            as avg_top_rating,
  round(avg(avg_review_count)::numeric, 1)                      as avg_top_review_count
from per_obs
group by wave_code, surface_code, industry_code, ring_miles;

comment on view analysis.ring_profile is
  'Descriptive distance-decay per (wave, surface, industry, ring_miles): avg result-set size + (Maps) avg rating/review depth of the returned set.';

-- ============================================================================
-- 6) maps_center_retention -- the true distance-decay signal: for each non-center
--    point, what fraction of the CENTER''s Local-Pack businesses are still present at
--    that distance (set retention vs center), averaged per ring within a cell. Low
--    retention at larger rings == the local result set diverges quickly with distance.
--    Grain: (wave, industry, market, query, ring_miles).
-- ============================================================================

create or replace view analysis.maps_center_retention as
with appear as (
  select distinct
    od.wave_id, od.wave_code, od.industry_code, od.market_code, od.treatment_code,
    od.coordinate_id, od.ring_miles, lr.resolved_entity_id as entity_id
  from analysis.observation_dim od
  join maps.result r
    on r.observation_id = od.observation_id and r.provider_item_type = 'maps_search'
  join core.latest_resolution lr
    on lr.observed_object_id = r.observed_object_id
   and lr.resolution_state in ('resolved','probable_match')
  where od.surface_code = 'maps'
),
center_set as (
  select wave_id, industry_code, market_code, treatment_code, entity_id
  from appear where ring_miles = 0
),
center_size as (
  select wave_id, industry_code, market_code, treatment_code, count(*) as center_entities
  from center_set
  group by wave_id, industry_code, market_code, treatment_code
),
per_point as (
  select
    p.wave_id, p.wave_code, p.industry_code, p.market_code, p.treatment_code,
    p.coordinate_id, p.ring_miles,
    count(*)                                                    as point_entities,
    count(cs.entity_id)                                         as retained_from_center
  from appear p
  left join center_set cs
    on cs.wave_id = p.wave_id and cs.industry_code = p.industry_code
   and cs.market_code = p.market_code and cs.treatment_code = p.treatment_code
   and cs.entity_id = p.entity_id
  where p.ring_miles > 0
  group by p.wave_id, p.wave_code, p.industry_code, p.market_code, p.treatment_code,
           p.coordinate_id, p.ring_miles
)
select
  pp.wave_code,
  pp.industry_code,
  pp.market_code,
  pp.treatment_code,
  pp.ring_miles,
  count(*)                                                      as points,
  round(avg(pp.retained_from_center::numeric
            / nullif(csz.center_entities, 0)), 4)               as avg_center_retention,
  round(avg(pp.point_entities)::numeric, 3)                     as avg_point_entities,
  round(avg(csz.center_entities)::numeric, 3)                   as avg_center_entities
from per_point pp
join center_size csz
  on csz.wave_id = pp.wave_id and csz.industry_code = pp.industry_code
 and csz.market_code = pp.market_code and csz.treatment_code = pp.treatment_code
group by pp.wave_code, pp.industry_code, pp.market_code, pp.treatment_code, pp.ring_miles;

comment on view analysis.maps_center_retention is
  'Distance-decay by ring: fraction of the CENTER point''s Local-Pack businesses still present at each outer ring (set retention vs center), per (wave, industry, market, query, ring).';

-- ============================================================================
-- 7) maps_organic_overlap -- cross-surface overlap at the SAME cell + query + point:
--    the set of business WEBSITE domains from the Maps Local Pack (norm_domain of the
--    GBP website url_raw) vs the set of Organic result domains. Answers "does a
--    business that wins the Local Pack also rank organically (via its site) here?".
--    Maps and Organic are separate observations, joined on
--    (wave, industry, market, query, coordinate). Grain: one row per that key.
-- ============================================================================

create or replace view analysis.maps_organic_overlap as
with maps_dom as (
  select distinct
    od.wave_id, od.wave_code, od.industry_code, od.market_code, od.treatment_code, od.coordinate_id,
    analysis.norm_domain(r.url_raw) as domain
  from analysis.observation_dim od
  join maps.result r
    on r.observation_id = od.observation_id and r.provider_item_type = 'maps_search'
  where od.surface_code = 'maps' and analysis.norm_domain(r.url_raw) is not null
),
org_dom as (
  select distinct
    od.wave_id, od.industry_code, od.market_code, od.treatment_code, od.coordinate_id,
    analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) as domain
  from analysis.observation_dim od
  join organic.result r
    on r.observation_id = od.observation_id and r.result_type = 'organic'
  where od.surface_code = 'organic'
    and analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) is not null
),
cell as (
  select distinct wave_id, wave_code, industry_code, market_code, treatment_code, coordinate_id
  from maps_dom
),
m_cnt as (
  select wave_id, industry_code, market_code, treatment_code, coordinate_id, count(*) as maps_domains
  from maps_dom group by 1,2,3,4,5
),
o_cnt as (
  select wave_id, industry_code, market_code, treatment_code, coordinate_id, count(*) as organic_domains
  from org_dom group by 1,2,3,4,5
),
x_cnt as (
  select md.wave_id, md.industry_code, md.market_code, md.treatment_code, md.coordinate_id,
         count(*) as overlap_domains
  from maps_dom md
  join org_dom od
    on od.wave_id = md.wave_id and od.industry_code = md.industry_code
   and od.market_code = md.market_code and od.treatment_code = md.treatment_code
   and od.coordinate_id = md.coordinate_id and od.domain = md.domain
  group by 1,2,3,4,5
)
select
  c.wave_code,
  c.industry_code,
  c.market_code,
  c.treatment_code,
  c.coordinate_id,
  coalesce(m.maps_domains, 0)      as maps_domains,
  coalesce(o.organic_domains, 0)   as organic_domains,
  coalesce(x.overlap_domains, 0)   as overlap_domains,
  round(coalesce(x.overlap_domains,0)::numeric
        / nullif(m.maps_domains, 0), 4)  as overlap_share_of_maps,
  round(coalesce(x.overlap_domains,0)::numeric
        / nullif(o.organic_domains, 0), 4) as overlap_share_of_organic
from cell c
left join m_cnt m on (m.wave_id,m.industry_code,m.market_code,m.treatment_code,m.coordinate_id)
                   = (c.wave_id,c.industry_code,c.market_code,c.treatment_code,c.coordinate_id)
left join o_cnt o on (o.wave_id,o.industry_code,o.market_code,o.treatment_code,o.coordinate_id)
                   = (c.wave_id,c.industry_code,c.market_code,c.treatment_code,c.coordinate_id)
left join x_cnt x on (x.wave_id,x.industry_code,x.market_code,x.treatment_code,x.coordinate_id)
                   = (c.wave_id,c.industry_code,c.market_code,c.treatment_code,c.coordinate_id);

comment on view analysis.maps_organic_overlap is
  'Maps<->Organic overlap per (wave, industry, market, query, point): business website domains from the Local Pack vs Organic result domains, intersection + share of each side.';

-- ============================================================================
-- 8) aio_overview_prevalence -- AIO PREVALENCE at full-panel scale, read from the
--    organic SERP itself: the share of organic observations that carry an
--    'ai_overview' block (async stub or expanded). Absence is a valid negative
--    (missing != zero). Directly sizes the AIO-widen decision. Grain: (wave,
--    industry, market, query, ring_miles).
-- ============================================================================

create or replace view analysis.aio_overview_prevalence as
with hits as (
  select distinct observation_id from organic.result where result_type = 'ai_overview'
)
select
  od.wave_code,
  od.industry_code,
  od.market_code,
  od.treatment_code,
  od.ring_miles,
  count(*)                                                      as observations,
  count(*) filter (where h.observation_id is not null)         as aio_present_observations,
  round(count(*) filter (where h.observation_id is not null)::numeric
        / nullif(count(*), 0), 4)                               as aio_prevalence
from analysis.observation_dim od
left join hits h on h.observation_id = od.observation_id
where od.surface_code in ('organic','aio')
group by od.wave_code, od.industry_code, od.market_code, od.treatment_code, od.ring_miles;

comment on view analysis.aio_overview_prevalence is
  'AIO prevalence per (wave, industry, market, query, ring): share of organic observations carrying an ai_overview block (stub or expanded). Absence = valid negative.';

-- ============================================================================
-- 9) aio_organic_source_overlap -- for an AIO wave (organic AI Overview capture),
--    per observation: the set of AIO sidebar SOURCE domains vs the co-returned
--    Organic result domains, and the share of AIO sources that also rank organically.
--    SearchViewer/GBP inline references (no publisher domain) are excluded here --
--    they are business appearances, not web sources. Grain: one row per aio
--    observation (roll up as needed).
-- ============================================================================

create or replace view analysis.aio_organic_source_overlap as
with aio_dom as (
  select distinct
    od.observation_id, od.wave_code, od.industry_code, od.market_code, od.treatment_code,
    analysis.norm_domain(coalesce(nullif(so.source_domain_raw,''), so.source_url_raw)) as domain
  from analysis.observation_dim od
  join aio.source_occurrence so on so.observation_id = od.observation_id
  where od.surface_code = 'aio'
    and so.source_domain_raw is not null
    and analysis.norm_domain(coalesce(nullif(so.source_domain_raw,''), so.source_url_raw)) is not null
),
org_dom as (
  select distinct
    od.observation_id,
    analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) as domain
  from analysis.observation_dim od
  join organic.result r
    on r.observation_id = od.observation_id and r.result_type = 'organic'
  where od.surface_code = 'aio'
    and analysis.norm_domain(coalesce(nullif(r.domain_raw,''), r.url_raw)) is not null
),
base as (
  select
    od.observation_id, od.wave_code, od.industry_code, od.market_code, od.treatment_code,
    a.aio_triggered, a.aio_presentation_form
  from analysis.observation_dim od
  join aio.observation a on a.observation_id = od.observation_id
  where od.surface_code = 'aio'
)
select
  b.observation_id,
  b.wave_code,
  b.industry_code,
  b.market_code,
  b.treatment_code,
  b.aio_triggered,
  b.aio_presentation_form,
  (select count(*) from aio_dom d where d.observation_id = b.observation_id)  as aio_source_domains,
  (select count(*) from org_dom  g where g.observation_id = b.observation_id) as organic_domains,
  (select count(*) from aio_dom d
     join org_dom g on g.observation_id = d.observation_id and g.domain = d.domain
    where d.observation_id = b.observation_id)                                as overlap_domains,
  round(
    (select count(*) from aio_dom d
       join org_dom g on g.observation_id = d.observation_id and g.domain = d.domain
      where d.observation_id = b.observation_id)::numeric
    / nullif((select count(*) from aio_dom d where d.observation_id = b.observation_id), 0)
  , 4)                                                                        as share_of_aio_sources_in_organic
from base b;

comment on view analysis.aio_organic_source_overlap is
  'Per AIO observation: AIO sidebar source domains vs co-returned Organic result domains + share of AIO sources also ranking organically. SearchViewer/GBP refs excluded (business appearances, not web sources).';
