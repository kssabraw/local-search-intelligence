-- Migration 003_provider_component_and_price_registries
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
-- SHARED PROVIDER / COMPONENT VERSION REGISTRIES
-- ============================================================================

create table ops.provider (
  provider_id uuid primary key default gen_random_uuid(),
  provider_code text not null unique,
  provider_name text not null,
  provider_kind text not null,
  homepage_url text,
  created_at timestamptz not null default now()
);

create table ops.provider_price_version (
  provider_price_version_id uuid primary key default gen_random_uuid(),
  provider_id uuid not null references ops.provider(provider_id),
  price_code text not null,
  endpoint_or_product text,
  billing_unit text not null,
  unit_amount_microusd bigint not null check (unit_amount_microusd >= 0),
  currency char(3) not null default 'USD',
  effective_from timestamptz not null,
  effective_to timestamptz,
  source_url text,
  source_observed_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (provider_id, price_code, effective_from)
);

create table ops.component_version (
  component_version_id uuid primary key default gen_random_uuid(),
  component_kind text not null check (component_kind in (
    'collector','parser','resolver','classifier','embedder','llm','sql','analysis_code','job_generator','other'
  )),
  component_name text not null,
  version_code text not null,
  git_sha text,
  config_sha256 char(64),
  artifact_uri text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (component_kind, component_name, version_code)
);
