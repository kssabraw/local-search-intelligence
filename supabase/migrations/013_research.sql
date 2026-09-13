-- Migration 013_research
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
-- RESEARCH: ANALYSIS CONTRACTS, REPRODUCIBLE DERIVED DATA, FINDINGS
-- ============================================================================

create table research.analysis_specification (
  analysis_specification_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  spec_code text not null,
  spec_version text not null,
  title text not null,
  population_definition jsonb not null,
  estimand text not null,
  exposure_definition jsonb not null,
  confounder_plan jsonb not null default '{}'::jsonb,
  mediator_collider_plan jsonb not null default '{}'::jsonb,
  timing_lag_plan jsonb not null default '{}'::jsonb,
  missingness_plan jsonb not null default '{}'::jsonb,
  repeated_measures_plan jsonb not null default '{}'::jsonb,
  multiple_testing_plan jsonb not null default '{}'::jsonb,
  validation_holdout_plan jsonb not null default '{}'::jsonb,
  practical_effect_plan jsonb not null default '{}'::jsonb,
  code_provenance jsonb not null default '{}'::jsonb,
  status text not null default 'draft',
  created_at timestamptz not null default now(),
  unique (methodology_version_id, spec_code, spec_version)
);

alter table enrichment.enrichment_request
  add column analysis_specification_id uuid references research.analysis_specification(analysis_specification_id);

create table research.dataset_build (
  dataset_build_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  entity_graph_release_id uuid references core.entity_graph_release(entity_graph_release_id),
  analysis_specification_id uuid references research.analysis_specification(analysis_specification_id),
  dataset_code text not null,
  build_version text not null,
  source_observation_cutoff timestamptz not null,
  sql_component_version_id uuid references ops.component_version(component_version_id),
  resolver_component_version_id uuid references ops.component_version(component_version_id),
  parser_bundle jsonb not null default '{}'::jsonb,
  input_manifest_uri text not null,
  input_manifest_sha256 char(64) not null,
  output_artifact_uri text,
  output_sha256 char(64),
  exclusion_manifest_uri text,
  exclusion_manifest_sha256 char(64),
  row_count bigint,
  build_metrics jsonb not null default '{}'::jsonb,
  build_config jsonb not null default '{}'::jsonb,
  status research.build_status not null default 'planned',
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (methodology_version_id, dataset_code, build_version)
);

create table research.feature_definition (
  feature_definition_id uuid primary key default gen_random_uuid(),
  feature_code text not null,
  feature_version text not null,
  description text not null,
  subject_grain text not null,
  value_type text not null check (value_type in ('numeric','boolean','text','jsonb','timestamp')),
  derivation_spec jsonb not null,
  component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (feature_code, feature_version)
);

create table research.feature_build (
  feature_build_id uuid primary key default gen_random_uuid(),
  dataset_build_id uuid not null references research.dataset_build(dataset_build_id),
  feature_definition_id uuid not null references research.feature_definition(feature_definition_id),
  status research.build_status not null,
  build_config jsonb not null default '{}'::jsonb,
  built_at timestamptz not null default now(),
  output_artifact_uri text,
  output_sha256 char(64),
  unique (dataset_build_id, feature_definition_id)
);

create table research.feature_value (
  feature_value_id uuid primary key default gen_random_uuid(),
  feature_build_id uuid not null references research.feature_build(feature_build_id),
  entity_id uuid references core.entity(entity_id),
  observation_id uuid references ops.observation(observation_id),
  wave_id uuid references ops.collection_wave(wave_id),
  numeric_value numeric,
  boolean_value boolean,
  text_value text,
  jsonb_value jsonb,
  timestamp_value timestamptz,
  created_at timestamptz not null default now(),
  check (
    entity_id is not null or observation_id is not null or wave_id is not null
  ),
  check (
    num_nonnulls(numeric_value, boolean_value, text_value, jsonb_value, timestamp_value) = 1
  )
);

create table research.cohort (
  cohort_id uuid primary key default gen_random_uuid(),
  analysis_specification_id uuid not null references research.analysis_specification(analysis_specification_id),
  cohort_code text not null,
  cohort_version text not null,
  role text,
  definition jsonb not null,
  created_at timestamptz not null default now(),
  unique (analysis_specification_id, cohort_code, cohort_version)
);

create table research.cohort_member (
  cohort_member_id uuid primary key default gen_random_uuid(),
  cohort_id uuid not null references research.cohort(cohort_id),
  entity_id uuid not null references core.entity(entity_id),
  wave_id uuid references ops.collection_wave(wave_id),
  effective_from timestamptz,
  effective_to timestamptz,
  inclusion_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table research.model_version (
  model_version_id uuid primary key default gen_random_uuid(),
  model_code text not null,
  version_code text not null,
  model_kind text not null,
  artifact_uri text,
  artifact_sha256 char(64),
  git_sha text,
  parameters jsonb not null default '{}'::jsonb,
  training_dataset_build_id uuid references research.dataset_build(dataset_build_id),
  created_at timestamptz not null default now(),
  unique (model_code, version_code)
);

create table research.analysis_run (
  analysis_run_id uuid primary key default gen_random_uuid(),
  analysis_specification_id uuid not null references research.analysis_specification(analysis_specification_id),
  dataset_build_id uuid not null references research.dataset_build(dataset_build_id),
  model_version_id uuid references research.model_version(model_version_id),
  analysis_component_version_id uuid references ops.component_version(component_version_id),
  run_code text not null,
  run_parameters jsonb not null default '{}'::jsonb,
  result_artifact_uri text,
  result_sha256 char(64),
  status research.build_status not null,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (analysis_specification_id, run_code)
);

create table research.hypothesis (
  hypothesis_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  hypothesis_code text not null,
  statement text not null,
  preregistered_at timestamptz,
  status text not null default 'active',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (methodology_version_id, hypothesis_code)
);

create table research.finding (
  finding_id uuid primary key default gen_random_uuid(),
  hypothesis_id uuid references research.hypothesis(hypothesis_id),
  analysis_run_id uuid not null references research.analysis_run(analysis_run_id),
  finding_code text not null,
  statement text not null,
  evidence_label text,
  population_of_inference text not null,
  association_or_causal text not null check (association_or_causal in ('descriptive','associational','predictive','causal')),
  practical_effect_summary text,
  uncertainty_summary text,
  status research.finding_status not null default 'draft',
  supersedes_finding_id uuid references research.finding(finding_id),
  created_at timestamptz not null default now(),
  unique (analysis_run_id, finding_code)
);

create table research.finding_evidence (
  finding_evidence_id uuid primary key default gen_random_uuid(),
  finding_id uuid not null references research.finding(finding_id),
  evidence_kind text not null,
  evidence_ref_uri text,
  evidence_sha256 char(64),
  observation_id uuid references ops.observation(observation_id),
  dataset_build_id uuid references research.dataset_build(dataset_build_id),
  analysis_run_id uuid references research.analysis_run(analysis_run_id),
  notes text,
  created_at timestamptz not null default now()
);
