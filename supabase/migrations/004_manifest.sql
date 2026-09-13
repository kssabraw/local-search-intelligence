-- Migration 004_manifest
-- SED Local Search Intelligence Platform -- physical schema v0.1
--
-- Mechanical split of supabase/schema/physical-schema-v0_1.sql (the
-- authoritative artifact) at the deployment-order boundaries declared in
-- docs/contracts/physical-schema-contract-v0_1.md section 36. See
-- supabase/migrations/README.md. Do NOT hand-edit; regenerate with
-- scripts/split_schema_to_migrations.py.
--
-- Research schemas are private: no grants to anon/authenticated are issued.
-- Product-facing RLS/auth is deferred to a later security contract (migration
-- 020_security in the contract's order; intentionally not created yet).

-- ============================================================================
-- MANIFEST: VERSIONED ANSWER TO "WHAT EXACTLY DO WE RUN?"
-- ============================================================================

create table manifest.methodology_version (
  methodology_version_id uuid primary key default gen_random_uuid(),
  methodology_code text not null unique,
  status manifest.version_status not null default 'draft',
  effective_from timestamptz,
  effective_to timestamptz,
  parent_methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  manifest_sha256 char(64),
  manifest_artifact_uri text,
  governing_handoff_drive_id text,
  governing_parent_prd_drive_id text,
  notes text,
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  check ((status <> 'frozen') or frozen_at is not null)
);

create table manifest.surface (
  surface_id uuid primary key default gen_random_uuid(),
  surface_code text not null unique,
  surface_name text not null,
  is_primary_observation_surface boolean not null default true,
  created_at timestamptz not null default now()
);

create table manifest.industry (
  industry_id uuid primary key default gen_random_uuid(),
  industry_code text not null unique,
  industry_name text not null,
  canonical_service_term text not null,
  vertical_group text,
  created_at timestamptz not null default now()
);

create table manifest.market (
  market_id uuid primary key default gen_random_uuid(),
  market_code text not null unique,
  city text not null,
  state_region text not null,
  country_code char(2) not null default 'US',
  census_place_geoid text,
  center_lat numeric(10,7),
  center_lon numeric(10,7),
  center_source text,
  center_method_version text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (center_lat is null or center_lat between -90 and 90),
  check (center_lon is null or center_lon between -180 and 180)
);

create table manifest.methodology_industry (
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  industry_id uuid not null references manifest.industry(industry_id),
  ordinal smallint not null,
  registry_status text not null default 'approved',
  approval_basis text,
  primary key (methodology_version_id, industry_id),
  unique (methodology_version_id, ordinal)
);

create table manifest.methodology_market (
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  market_id uuid not null references manifest.market(market_id),
  ordinal smallint not null,
  registry_status text not null default 'approved',
  approval_basis text,
  primary key (methodology_version_id, market_id),
  unique (methodology_version_id, ordinal)
);

create table manifest.geometry_version (
  geometry_version_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  geometry_code text not null,
  geometry_name text not null,
  surface_group text not null,
  coordinate_crs text not null default 'EPSG:4326',
  coordinate_precision smallint not null default 7 check (coordinate_precision between 0 and 9),
  generation_method text not null,
  water_mask_version text,
  status manifest.version_status not null default 'draft',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, geometry_code)
);

create table manifest.geometry_point (
  geometry_point_id uuid primary key default gen_random_uuid(),
  geometry_version_id uuid not null references manifest.geometry_version(geometry_version_id),
  point_code text not null,
  point_label text not null,
  bearing_deg numeric(6,2),
  distance_miles numeric(8,3) not null default 0 check (distance_miles >= 0),
  full_geometry_member boolean not null default true,
  nested_candidate_member boolean not null default false,
  incremental_member boolean not null default false,
  ordinal smallint not null,
  metadata jsonb not null default '{}'::jsonb,
  unique (geometry_version_id, point_code),
  unique (geometry_version_id, ordinal),
  check (
    (distance_miles = 0 and bearing_deg is null)
    or
    (distance_miles > 0 and bearing_deg between 0 and 360)
  )
);

create table manifest.market_coordinate (
  coordinate_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  market_id uuid not null references manifest.market(market_id),
  geometry_point_id uuid not null references manifest.geometry_point(geometry_point_id),
  latitude numeric(10,7) not null check (latitude between -90 and 90),
  longitude numeric(10,7) not null check (longitude between -180 and 180),
  eligibility manifest.coordinate_eligibility not null default 'pending',
  structural_exclusion_reason text,
  water_feature_name text,
  water_feature_mtfcc text,
  water_feature_id text,
  water_mask_source text,
  water_mask_version text,
  eligibility_decided_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, market_id, geometry_point_id),
  check (
    (eligibility in ('structural_water_exclusion','configuration_failure') and structural_exclusion_reason is not null)
    or eligibility not in ('structural_water_exclusion','configuration_failure')
  )
);

create table manifest.treatment (
  treatment_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  industry_id uuid not null references manifest.industry(industry_id),
  treatment_set_code text not null,
  treatment_code text not null,
  treatment_kind manifest.treatment_kind not null,
  family text,
  core_query_class text,
  exact_template text not null,
  sequence smallint not null,
  city_slot_required boolean not null default false,
  is_locked boolean not null default false,
  approval_basis text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, industry_id, treatment_set_code, treatment_code),
  unique (methodology_version_id, industry_id, treatment_set_code, sequence)
);

create table manifest.surface_treatment (
  surface_treatment_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  treatment_id uuid not null references manifest.treatment(treatment_id),
  sequence smallint not null,
  active boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  unique (methodology_version_id, surface_id, treatment_id),
  unique (methodology_version_id, surface_id, sequence)
);

create table manifest.provider_profile (
  provider_profile_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  provider_id uuid not null references ops.provider(provider_id),
  profile_code text not null,
  method text not null,
  post_endpoint text,
  get_endpoint text,
  language_code text,
  device text,
  operating_system text,
  location_mode text,
  location_template text,
  result_depth integer,
  priority smallint,
  max_tasks_per_post integer,
  settings jsonb not null default '{}'::jsonb,
  settings_sha256 char(64),
  created_at timestamptz not null default now(),
  unique (methodology_version_id, profile_code)
);

create table manifest.surface_config (
  surface_config_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  provider_profile_id uuid not null references manifest.provider_profile(provider_profile_id),
  geometry_version_id uuid references manifest.geometry_version(geometry_version_id),
  full_panel_cadence text not null,
  sentinel_cadence text not null,
  replicates smallint not null default 1 check (replicates >= 1),
  result_depth integer,
  raw_response_required boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  unique (methodology_version_id, surface_id)
);

create table manifest.panel_subset (
  panel_subset_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  subset_code text not null,
  subset_kind text not null,
  fixed_membership boolean not null default true,
  description text,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, subset_code)
);

create table manifest.panel_subset_industry (
  panel_subset_id uuid not null references manifest.panel_subset(panel_subset_id) on delete cascade,
  industry_id uuid not null references manifest.industry(industry_id),
  ordinal smallint,
  primary key (panel_subset_id, industry_id)
);

create table manifest.panel_subset_market (
  panel_subset_id uuid not null references manifest.panel_subset(panel_subset_id) on delete cascade,
  market_id uuid not null references manifest.market(market_id),
  ordinal smallint,
  primary key (panel_subset_id, market_id)
);
