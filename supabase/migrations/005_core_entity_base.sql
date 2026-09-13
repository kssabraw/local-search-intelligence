-- Migration 005_core_entity_base
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
-- CORE CANONICAL ENTITY GRAPH
-- ============================================================================

create table core.entity_type (
  entity_type_code text primary key,
  description text not null
);

create table core.entity (
  entity_id uuid primary key default gen_random_uuid(),
  entity_type_code text not null references core.entity_type(entity_type_code),
  operational_label text,
  lifecycle_state text not null default 'active' check (lifecycle_state in ('active','retired','merged','unknown')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table core.organization (
  entity_id uuid primary key references core.entity(entity_id),
  organization_kind text,
  metadata jsonb not null default '{}'::jsonb
);

create table core.brand (
  entity_id uuid primary key references core.entity(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.business_location (
  entity_id uuid primary key references core.entity(entity_id),
  preferred_analysis_grain boolean not null default true,
  metadata jsonb not null default '{}'::jsonb
);

create table core.google_business_profile (
  entity_id uuid primary key references core.entity(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.web_domain (
  entity_id uuid primary key references core.entity(entity_id),
  normalized_domain text not null unique,
  registered_domain text,
  metadata jsonb not null default '{}'::jsonb
);

create table core.web_url (
  entity_id uuid primary key references core.entity(entity_id),
  normalized_url text not null unique,
  domain_entity_id uuid references core.web_domain(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.profile_entity (
  entity_id uuid primary key references core.entity(entity_id),
  profile_kind text not null,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.source_asset (
  entity_id uuid primary key references core.entity(entity_id),
  source_kind text not null,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  metadata jsonb not null default '{}'::jsonb
);

create table core.relationship_type (
  relationship_type_code text primary key,
  description text not null
);
