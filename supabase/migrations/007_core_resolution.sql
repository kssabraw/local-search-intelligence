-- Migration 007_core_resolution
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
-- CORE OBSERVED OBJECTS + VERSIONED ENTITY RESOLUTION
-- ============================================================================

create table core.observed_object (
  observed_object_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references ops.observation(observation_id),
  surface_id uuid not null references manifest.surface(surface_id),
  object_kind text not null,
  local_sequence integer not null check (local_sequence >= 1),
  raw_name text,
  raw_url text,
  raw_domain text,
  raw_phone text,
  raw_address text,
  raw_text_span text,
  raw_external_ids jsonb not null default '{}'::jsonb,
  raw_attributes jsonb not null default '{}'::jsonb,
  parser_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (observation_id, object_kind, local_sequence)
);

create table core.entity_graph_release (
  entity_graph_release_id uuid primary key default gen_random_uuid(),
  release_code text not null unique,
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  parent_release_id uuid references core.entity_graph_release(entity_graph_release_id),
  status manifest.version_status not null default 'draft',
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  notes text,
  check ((status <> 'frozen') or frozen_at is not null)
);

create table core.resolution_run (
  resolution_run_id uuid primary key default gen_random_uuid(),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  resolver_version_id uuid not null references ops.component_version(component_version_id),
  resolver_stage text not null,
  input_sha256 char(64),
  run_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create table core.resolution_candidate (
  resolution_candidate_id uuid primary key default gen_random_uuid(),
  resolution_run_id uuid not null references core.resolution_run(resolution_run_id),
  candidate_entity_id uuid not null references core.entity(entity_id),
  candidate_rank integer,
  match_score numeric(12,6),
  score_semantics text not null default 'uncalibrated',
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (resolution_run_id, candidate_entity_id)
);

create table core.resolution_assertion (
  resolution_assertion_id uuid primary key default gen_random_uuid(),
  resolution_run_id uuid not null references core.resolution_run(resolution_run_id),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  resolved_entity_id uuid references core.entity(entity_id),
  resolution_state core.resolution_state not null,
  confidence_value numeric(8,6),
  confidence_semantics text,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.resolution_assertion(resolution_assertion_id),
  analyst_override boolean not null default false,
  analyst_note text,
  created_at timestamptz not null default now(),
  check (
    (resolution_state in ('resolved','probable_match') and resolved_entity_id is not null)
    or
    (resolution_state not in ('resolved','probable_match') and resolved_entity_id is null)
  ),
  check (confidence_value is null or confidence_value between 0 and 1)
);

create table core.entity_relationship_assertion (
  relationship_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  from_entity_id uuid not null references core.entity(entity_id),
  relationship_type_code text not null references core.relationship_type(relationship_type_code),
  to_entity_id uuid not null references core.entity(entity_id),
  action core.assertion_action not null default 'assert',
  effective_from timestamptz,
  effective_to timestamptz,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  source_observed_object_id uuid references core.observed_object(observed_object_id),
  resolver_version_id uuid references ops.component_version(component_version_id),
  supersedes_assertion_id uuid references core.entity_relationship_assertion(relationship_assertion_id),
  created_at timestamptz not null default now(),
  check (from_entity_id <> to_entity_id)
);

create table core.external_identifier (
  external_identifier_id uuid primary key default gen_random_uuid(),
  namespace text not null,
  identifier_type text not null,
  identifier_value text not null,
  normalized_value text,
  created_at timestamptz not null default now(),
  unique (namespace, identifier_type, identifier_value)
);

create table core.external_identifier_assertion (
  external_identifier_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  external_identifier_id uuid not null references core.external_identifier(external_identifier_id),
  entity_id uuid not null references core.entity(entity_id),
  resolution_state core.resolution_state not null,
  supporting_evidence jsonb not null default '{}'::jsonb,
  conflicting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.external_identifier_assertion(external_identifier_assertion_id),
  created_at timestamptz not null default now(),
  check (resolution_state in ('resolved','probable_match'))
);

create table core.entity_alias_assertion (
  entity_alias_assertion_id uuid primary key default gen_random_uuid(),
  entity_graph_release_id uuid not null references core.entity_graph_release(entity_graph_release_id),
  entity_id uuid not null references core.entity(entity_id),
  alias_type text not null,
  alias_text text not null,
  normalized_alias text not null,
  source_observed_object_id uuid references core.observed_object(observed_object_id),
  supporting_evidence jsonb not null default '{}'::jsonb,
  supersedes_assertion_id uuid references core.entity_alias_assertion(entity_alias_assertion_id),
  created_at timestamptz not null default now()
);
