-- Migration 014_client
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
-- CLIENT MODE: REFERENCES SHARED RESEARCH TRUTH; DOES NOT DUPLICATE IT
-- ============================================================================

create table client.case_record (
  client_case_id uuid primary key default gen_random_uuid(),
  client_entity_id uuid not null references core.entity(entity_id),
  industry_id uuid references manifest.industry(industry_id),
  market_id uuid references manifest.market(market_id),
  opened_at timestamptz not null default now(),
  closed_at timestamptz,
  metadata jsonb not null default '{}'::jsonb
);

create table client.assessment (
  assessment_id uuid primary key default gen_random_uuid(),
  client_case_id uuid not null references client.case_record(client_case_id),
  finding_id uuid references research.finding(finding_id),
  recommendation_state client.recommendation_state not null,
  client_observation jsonb not null default '{}'::jsonb,
  competitive_gap jsonb not null default '{}'::jsonb,
  rationale text,
  created_at timestamptz not null default now()
);
