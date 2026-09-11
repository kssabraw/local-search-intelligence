# Physical Schema Contract v0.1

**Status:** DRAFT — awaiting owner sign-off. Pre-provisioning (no Supabase project exists yet). This contract is the authority the first migrations implement; it is not itself applied.

**Scope:** the **shared foundation** + the **Maps/Organic** surface (Stage 1 of the plan of record). It covers exactly what the 15-cell Maps/Organic pilot exercises, designed so AIO and ChatGPT extend it without a parallel stack. Enrichment / signal warehouse, transition/event tables, finding & intervention registries, Strategy Evidence, and Client Mode are **explicitly out of v0.1** (see §7).

**Inherits (parent PRD, unchanged here):** provider/economic-unit deduplication semantics, content-addressed asset rules, Python/SQL-before-LLM, missingness states, cost-ledger gross-vs-net semantics.

---

## 1. Conventions

- **Database:** one Supabase/Postgres project. v0.1 tables live in `public`; a dedicated `research` schema is an option at provisioning (decide then).
- **IDs:** universe dimensions use the manifest's natural string keys (`IND010`, `MKT008`); everything else uses `uuid` (`gen_random_uuid()`).
- **Timestamps:** `timestamptz`. Every observation carries `collected_at` (when the provider produced it) and `created_at` (when we stored it); never conflate them.
- **Immutability:** `raw_observation`, `provider_task`, and the normalized observation tables are **append-only**. Enforced by grant (workers get INSERT/SELECT, not UPDATE/DELETE on these) + convention; derived/mutable-metadata tables (`business`, `domain`, resolution state) may be updated.
- **Versioning:** every run and observation records the `methodology_version`, `collector_version`, and `parser_version` in effect, plus `git_commit`, so methodology change is separable from real change.
- **Raw is authoritative:** normalized tables point back to a `raw_observation` and are rebuildable; raw is never rebuilt.
- **Missing ≠ zero:** the `eligibility_status` / `status` enums below carry the distinct missingness states; a structurally-excluded coordinate is never rank 0.

---

## 2. Universe & methodology

```sql
create table methodology_version (
  id              text primary key,          -- e.g. 'maps_organic_pilot_2026-09-11'
  surface_scope   text not null,             -- 'maps_organic' | 'aio' | 'chatgpt' | 'shared'
  status          text not null,             -- 'draft' | 'frozen' | 'superseded'
  description     text,
  git_commit      text,
  frozen_at       timestamptz,
  created_at      timestamptz not null default now()
);

create table research_industry (
  industry_id           text primary key,    -- 'IND010'
  industry_name         text not null,       -- 'Locksmith'
  vertical_group        text,
  canonical_service_term text not null,
  q1 text not null, q2 text not null, q3 text not null, q4 text not null,
  q3_rationale          text,
  methodology_version_id text not null references methodology_version(id),
  active                boolean not null default true,
  created_at            timestamptz not null default now()
);

create table research_market (
  market_id             text primary key,    -- 'MKT008'
  city                  text not null,
  state                 text not null,
  country               text not null default 'US',
  region_stratum        text,
  size_stratum          text,
  center_lat            double precision not null,
  center_lon            double precision not null,
  center_status         text not null,       -- 'CIVIC_ANCHOR_FROZEN' | 'PRE_WATER' | 'CONFIGURATION_FAILURE'
  center_method_version text not null,       -- 'CIVIC_CENTER_ANCHOR_V1_...'
  center_source_url     text,
  census_place_name     text,
  census_geoid          text,
  methodology_version_id text not null references methodology_version(id),
  created_at            timestamptz not null default now()
);

-- Per-industry query condition templates. [CITY] is resolved to the market at collection time only.
create table query_condition (
  id                    uuid primary key default gen_random_uuid(),
  industry_id           text not null references research_industry(industry_id),
  surface               text not null,       -- 'maps' | 'organic'
  condition_slot        text not null,       -- 'q1'..'q4'
  query_family_id       text,
  intent_class          text,                -- transactional | recommendation | ...
  geo_class             text,                -- geo_neutral | explicit_city | near_me
  literal_template      text not null,       -- 'locksmith in [CITY]'
  methodology_version_id text not null references methodology_version(id),
  unique (industry_id, surface, condition_slot, methodology_version_id)
);

-- One row per candidate coordinate. Coordinates never drift; regeneration mints a new geometry_version.
create table research_coordinate (
  coordinate_id         uuid primary key default gen_random_uuid(),
  market_id             text not null references research_market(market_id),
  geometry_version      text not null,       -- 'maps_organic_pilot_13'
  point_index           int not null,
  bearing_deg           double precision,    -- null for center
  distance_miles        double precision not null default 0,  -- 0 | 1 | 3 | 5
  latitude              double precision not null,
  longitude             double precision not null,
  coordinate_hash       text not null,
  is_full_13_member     boolean not null default true,
  is_nested_9_member    boolean not null default false,
  is_incremental_4_member boolean not null default false,
  eligibility_status    text not null,       -- 'eligible' | 'structural_water_exclusion' | 'outside_country_exclusion' | 'configuration_failure'
  exclusion_reason      text,
  boundary_source_version text,
  water_source_version  text,
  created_at            timestamptz not null default now(),
  unique (market_id, geometry_version, point_index)
);

-- Cohort membership (Full Panel vs the fixed Sentinel subset).
create table research_panel (
  id            text primary key,            -- 'sentinel' | 'full_panel'
  description   text
);
create table research_panel_membership (
  panel_id      text not null references research_panel(id),
  industry_id   text not null references research_industry(industry_id),
  market_id     text not null references research_market(market_id),
  effective_from timestamptz not null default now(),
  effective_to  timestamptz,
  primary key (panel_id, industry_id, market_id, effective_from)
);
```

---

## 3. Collection, tasks & cost ledger

```sql
create table research_run (
  run_id            uuid primary key default gen_random_uuid(),
  methodology_version_id text not null references methodology_version(id),
  cohort_type       text not null,           -- 'PILOT' | 'FULL_PANEL' | 'SENTINEL' | 'EXPERIMENT'
  surface           text not null,           -- 'maps' | 'organic'
  started_at        timestamptz not null default now(),
  completed_at      timestamptz,
  expected_tasks    int,
  successful_tasks  int not null default 0,
  failed_tasks      int not null default 0,
  collector_version text not null,
  parser_version    text not null,
  git_commit        text,
  status            text not null default 'running',  -- 'running' | 'complete' | 'partial' | 'error'
  created_at        timestamptz not null default now()
);

create table provider_task (
  task_id           uuid primary key default gen_random_uuid(),
  run_id            uuid not null references research_run(run_id),
  provider          text not null,           -- 'dataforseo'
  endpoint          text not null,           -- '/v3/serp/google/maps/task_post'
  surface           text not null,
  query_condition_id uuid references query_condition(id),
  coordinate_id     uuid references research_coordinate(coordinate_id),
  request_signature text not null,           -- canonical dedup signature (provider+endpoint+econ unit+scope+loc+freshness)
  request_params    jsonb not null,
  provider_task_id  text,                    -- provider-side id
  idempotency_key   text not null unique,    -- job_type + coordinate + condition + run + provider/version
  status            text not null default 'pending',  -- pending|running|succeeded|failed|excluded
  attempts          int not null default 0,
  max_attempts      int not null default 3,
  scheduled_at      timestamptz,
  started_at        timestamptz,
  completed_at      timestamptz,
  last_error        text,
  estimated_cost    numeric(12,6),
  created_at        timestamptz not null default now()
);

create table raw_observation (
  raw_id            uuid primary key default gen_random_uuid(),
  provider_task_id  uuid not null references provider_task(task_id),
  storage_path      text not null unique,    -- content-addressed, fail-on-exists
  content_sha256    text not null,
  byte_size         bigint,
  provider          text not null,
  parser_version_at_capture text,
  collected_at      timestamptz not null,
  created_at        timestamptz not null default now()
);

-- Cost ledger. Supports gross-demand vs net-purchased so avoided-duplicate spend is reportable.
create table api_usage (
  id                uuid primary key default gen_random_uuid(),
  run_id            uuid references research_run(run_id),
  provider_task_id  uuid references provider_task(task_id),
  provider          text not null,
  endpoint          text not null,
  economic_unit     text,                    -- 'serp_page' | 'canonical_business' | 'canonical_domain' | ...
  request_count     int not null default 1,
  returned_records  int,
  provider_reported_cost numeric(12,6),
  estimated_cost    numeric(12,6),
  gross_demand_cost numeric(12,6),           -- what independent fulfillment would have cost
  net_purchased_cost numeric(12,6),          -- what we actually bought after dedup/reuse
  currency          text not null default 'USD',
  surface           text,
  research_reason   text,
  collected_at      timestamptz not null default now()
);
```

---

## 4. Normalized surface observations

One request-level record per (query condition × coordinate × run), then per-surface result children. Maps and Organic outcomes are kept in **separate** child tables and never collapsed.

```sql
create table surface_observation (
  obs_id            uuid primary key default gen_random_uuid(),
  provider_task_id  uuid not null references provider_task(task_id),
  raw_id            uuid not null references raw_observation(raw_id),
  run_id            uuid not null references research_run(run_id),
  surface           text not null,           -- 'maps' | 'organic'
  query_condition_id uuid not null references query_condition(id),
  coordinate_id     uuid not null references research_coordinate(coordinate_id),
  market_id         text not null references research_market(market_id),
  collected_at      timestamptz not null,
  result_count      int,
  eligibility_status text not null,          -- mirrors coordinate; carries structural missingness
  status            text not null,           -- 'ok' | 'empty' | 'failed' | 'excluded'
  error_code        text,
  created_at        timestamptz not null default now()
);

-- Maps / Local Pack: the COMPLETE ordered result set at the coordinate (not just a tracked business).
create table local_result (
  id                uuid primary key default gen_random_uuid(),
  obs_id            uuid not null references surface_observation(obs_id),
  business_id       uuid references business(business_id),   -- null until resolved
  position          int not null,
  rank_absolute     int,
  name_as_returned  text,
  rating            numeric(2,1),
  review_count      int,
  primary_category  text,
  address           text,
  latitude          double precision,
  longitude         double precision,
  website_url       text,
  place_id          text,
  cid               text,
  is_sponsored      boolean,
  searcher_to_business_miles double precision,  -- derived; filled after resolution
  result_metadata   jsonb,
  created_at        timestamptz not null default now()
);

-- Organic Top-10.
create table organic_result (
  id                uuid primary key default gen_random_uuid(),
  obs_id            uuid not null references surface_observation(obs_id),
  position          int not null,
  url               text,
  normalized_url    text,
  domain_id         uuid references domain(domain_id),
  business_id       uuid references business(business_id),
  title             text,
  snippet           text,
  is_local_pack_ref boolean not null default false,
  serp_feature_type text,
  created_at        timestamptz not null default now()
);
```

---

## 5. Canonical entity graph

```sql
create table domain (
  domain_id     uuid primary key default gen_random_uuid(),
  domain        text not null unique,
  root_domain   text,
  subdomain     text,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now()
);

create table url (
  url_id        uuid primary key default gen_random_uuid(),
  domain_id     uuid not null references domain(domain_id),
  url           text not null unique,
  normalized_url text not null,
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now()
);

create table business (
  business_id       uuid primary key default gen_random_uuid(),
  place_id          text unique,             -- strong identifier; null for organic-only businesses
  cid               text,
  normalized_name   text not null,
  display_name      text,
  address           text, city text, state text, postal_code text,
  latitude          double precision, longitude double precision,
  phone             text,
  primary_category  text,
  website_domain_id uuid references domain(domain_id),
  first_seen_at     timestamptz not null default now(),
  last_seen_at      timestamptz not null default now()
);

-- Resolution evidence; ambiguous matches are NOT merged into `business`.
create table business_resolution (
  id                uuid primary key default gen_random_uuid(),
  business_id       uuid references business(business_id),
  status            text not null,           -- resolved|probable_match|ambiguous|unresolved|likely_nonexistent
  resolution_method text,
  confidence        numeric(4,3),
  matched_place_id  text, matched_cid text, matched_domain text,
  matched_phone     text, matched_address text,
  evidence          jsonb,
  resolver_version  text,
  resolved_at       timestamptz not null default now()
);

-- Physical location is time-aware; historical distances use the historically valid coordinate.
create table business_location_snapshot (
  id            uuid primary key default gen_random_uuid(),
  business_id   uuid not null references business(business_id),
  latitude      double precision not null,
  longitude     double precision not null,
  address       text,
  effective_from timestamptz not null,
  effective_to  timestamptz,
  source        text,
  collected_at  timestamptz not null default now()
);
```

> `gbp_location`, `social_entity`, and a general `entity_relationship` table are part of the parent graph but **deferred**: for the Maps/Organic pilot, `place_id`/`cid` on `business` carry GBP identity, and the only relationship needed is `business → website domain`. They land when AIO/enrichment needs them.

---

## 6. Immutability, distance & derived data

- Distance (searcher-coordinate ↔ business), bearing, and directional sector are **derived**, computed by a job after entity resolution, and written to `local_result.searcher_to_business_miles` (+ a later derived features table). Raw stays untouched.
- Coverage / rank / reach / excess-performance / persistence / transition metrics are **derived projections** built from these tables — not stored as authoritative source, and never collapsed into one score. (Their tables arrive with the metrics stage, post-pilot.)

---

## 7. Deliberately out of v0.1

Signal warehouse (`signal_definition`/`signal_value`), enrichment request/history, `url_content_version`, transition/event tables, `research_event`, `research_finding`/`finding_replication`, `client_account`/`client_entity_link`, `intervention`/`intervention_measurement`, and all AIO/ChatGPT surface tables. Each arrives with its stage; none is precluded by v0.1.

## 8. Open engineering decisions (inherited from parent §31)

- Object-storage path layout + bucket policy (Supabase Storage; content-addressed, fail-on-exists).
- First-pass entity-resolution confidence thresholds (place_id-first is deterministic; tune probabilistic domain matching from pilot data).
- Whether the durable job queue is a dedicated `collection_job` table or the shared worker's `async_jobs` equivalent (v0.1 assumes a Postgres-table queue mirroring AR Tools).
- `public` vs a dedicated `research` schema.

Resolve these at provisioning; none changes the tables above.
