-- Migration 010_aio
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
-- AIO / AI MODE SURFACE
-- ============================================================================

create table aio.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  aio_triggered boolean,
  response_text_raw text,
  response_markdown_raw text,
  provider_model text,
  response_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table aio.presentation_unit (
  presentation_unit_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  unit_sequence integer not null check (unit_sequence >= 1),
  unit_type text not null,
  presentation_zone text,
  heading_raw text,
  text_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, unit_sequence)
);

create table aio.business_appearance (
  business_appearance_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  appearance_sequence integer not null check (appearance_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  appearance_type text,
  local_business_card boolean,
  embedded_gbp boolean,
  selected boolean,
  raw_label text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, appearance_sequence)
);

create table aio.source_occurrence (
  source_occurrence_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  source_sequence integer not null check (source_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  source_url_raw text,
  source_title_raw text,
  publisher_raw text,
  retrieval_position integer,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, source_sequence)
);

create table aio.citation (
  citation_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references aio.observation(observation_id),
  source_occurrence_id uuid not null references aio.source_occurrence(source_occurrence_id),
  presentation_unit_id uuid references aio.presentation_unit(presentation_unit_id),
  citation_sequence integer not null check (citation_sequence >= 1),
  marker_raw text,
  cited_span_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, citation_sequence)
);

create table aio.destination (
  destination_id uuid primary key default gen_random_uuid(),
  business_appearance_id uuid not null references aio.business_appearance(business_appearance_id),
  destination_sequence integer not null check (destination_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  destination_url_raw text not null,
  destination_type text,
  direct_business_link boolean,
  third_party_business_link boolean,
  created_at timestamptz not null default now(),
  unique (business_appearance_id, destination_sequence)
);

create table aio.evidence_link (
  aio_evidence_link_id uuid primary key default gen_random_uuid(),
  citation_id uuid not null references aio.citation(citation_id),
  business_appearance_id uuid references aio.business_appearance(business_appearance_id),
  relationship_type text not null check (relationship_type in (
    'supports_business','supports_claim','supports_comparison','supports_list','general_background','unclear'
  )),
  claim_text_raw text,
  created_at timestamptz not null default now()
);
