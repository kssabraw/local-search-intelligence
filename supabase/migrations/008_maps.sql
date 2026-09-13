-- Migration 008_maps
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
-- MAPS SURFACE
-- ============================================================================

create table maps.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  returned_result_count integer check (returned_result_count is null or returned_result_count >= 0),
  provider_depth integer,
  search_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table maps.result (
  maps_result_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references maps.observation(observation_id),
  result_sequence integer not null check (result_sequence >= 1),
  rank_absolute integer,
  rank_group integer,
  provider_item_type text,
  title_raw text,
  category_raw text,
  rating numeric(4,2),
  review_count integer,
  address_raw text,
  phone_raw text,
  latitude numeric(10,7),
  longitude numeric(10,7),
  url_raw text,
  observed_object_id uuid references core.observed_object(observed_object_id),
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, result_sequence),
  check (rank_absolute is null or rank_absolute >= 1),
  check (review_count is null or review_count >= 0),
  check (latitude is null or latitude between -90 and 90),
  check (longitude is null or longitude between -180 and 180)
);
