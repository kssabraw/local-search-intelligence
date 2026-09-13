-- Migration 002_controlled_types
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
-- ENUMS / CONTROLLED STATES
-- ============================================================================

create type manifest.version_status as enum ('draft','frozen','retired');
create type manifest.treatment_kind as enum ('query','prompt');
create type manifest.coordinate_eligibility as enum (
  'pending',
  'eligible_land',
  'structural_water_exclusion',
  'outside_country_exclusion',
  'manual_review',
  'configuration_failure'
);

-- RECONCILIATION (not a methodology change): the value
-- 'outside_country_exclusion' is added to manifest.coordinate_eligibility.
-- The frozen Manifest v1.0 geography classifies 9 coordinates as
-- outside_country_exclusion and CONTEXT.md / CLAUDE.md define it as a
-- first-class missingness state; the authoritative single-file SQL omitted the
-- enum value. See supabase/migrations/README.md.


create type ops.wave_kind as enum ('full_panel','sentinel','pilot','validation','ad_hoc');
create type ops.wave_status as enum ('planned','running','complete','partial','failed','quarantined','cancelled');
create type ops.job_status as enum (
  'planned',
  'blocked_structural',
  'queued',
  'submitted',
  'succeeded',
  'retryable_failure',
  'terminal_failure',
  'quarantined',
  'skipped'
);
create type ops.attempt_event_type as enum (
  'submitted',
  'provider_acknowledged',
  'poll',
  'response_received',
  'retryable_failure',
  'terminal_failure',
  'succeeded',
  'cancelled'
);
create type ops.payload_kind as enum (
  'request',
  'task_post_response',
  'task_get_response',
  'rendered_response',
  'screenshot',
  'other'
);
create type ops.observation_state as enum (
  'returned',
  'terminal_error',
  'provider_failure',
  'parser_failure',
  'refusal',
  'clarification_requested',
  'generic_guidance_only',
  'no_local_recommendations',
  'other'
);

create type core.resolution_state as enum (
  'resolved',
  'probable_match',
  'ambiguous',
  'unresolved',
  'likely_nonexistent',
  'insufficient_information'
);
create type core.assertion_action as enum ('assert','retract');

create type enrichment.freshness_state as enum ('fresh','stale','unknown','not_applicable');
create type enrichment.request_status as enum ('planned','skipped_fresh','queued','running','succeeded','failed','quarantined');

create type research.build_status as enum ('planned','running','complete','failed','quarantined','superseded');
create type research.finding_status as enum ('draft','active','superseded','retired');

create type client.recommendation_state as enum (
  'TEST',
  'MONITOR',
  'LEAVE_ALONE',
  'insufficient_evidence',
  'ineligible'
);
