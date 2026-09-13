-- Migration 006_ops_collection_and_raw
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
-- OPS: WAVES, JOBS, RAW BLOBS, ATTEMPTS, OBSERVATIONS, COSTS
-- ============================================================================

create table ops.collection_wave (
  wave_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  panel_subset_id uuid references manifest.panel_subset(panel_subset_id),
  wave_code text not null unique,
  wave_kind ops.wave_kind not null,
  scheduled_for timestamptz not null,
  collection_window_start timestamptz,
  collection_window_end timestamptz,
  parent_wave_id uuid references ops.collection_wave(wave_id),
  notes text,
  created_at timestamptz not null default now()
);

create table ops.wave_event (
  wave_event_id uuid primary key default gen_random_uuid(),
  wave_id uuid not null references ops.collection_wave(wave_id),
  status ops.wave_status not null,
  event_at timestamptz not null default now(),
  actor text,
  details jsonb not null default '{}'::jsonb
);

create table ops.collection_job (
  job_id uuid primary key default gen_random_uuid(),
  job_key char(64) not null unique,
  wave_id uuid not null references ops.collection_wave(wave_id),
  methodology_version_id uuid not null references manifest.methodology_version(methodology_version_id),
  surface_id uuid not null references manifest.surface(surface_id),
  industry_id uuid not null references manifest.industry(industry_id),
  market_id uuid not null references manifest.market(market_id),
  surface_treatment_id uuid not null references manifest.surface_treatment(surface_treatment_id),
  coordinate_id uuid references manifest.market_coordinate(coordinate_id),
  provider_profile_id uuid not null references manifest.provider_profile(provider_profile_id),
  replicate_no smallint not null default 1 check (replicate_no >= 1 and replicate_no <= 99),
  rendered_input_text text not null,
  rendered_request jsonb not null,
  rendered_request_sha256 char(64) not null,
  planned_eligibility manifest.coordinate_eligibility,
  generated_by_component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now()
);

create table ops.job_event (
  job_event_id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ops.collection_job(job_id),
  status ops.job_status not null,
  event_at timestamptz not null default now(),
  attempt_no integer,
  actor text,
  reason_code text,
  details jsonb not null default '{}'::jsonb
);

create table ops.raw_blob (
  blob_id uuid primary key default gen_random_uuid(),
  sha256 char(64) not null unique,
  storage_bucket text not null,
  storage_path text not null,
  byte_size bigint not null check (byte_size >= 0),
  mime_type text not null,
  content_encoding text,
  created_at timestamptz not null default now(),
  unique (storage_bucket, storage_path)
);

create table ops.provider_payload (
  payload_id uuid primary key default gen_random_uuid(),
  provider_id uuid not null references ops.provider(provider_id),
  blob_id uuid not null references ops.raw_blob(blob_id),
  payload_kind ops.payload_kind not null,
  provider_task_id text,
  captured_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table ops.collection_attempt (
  attempt_id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ops.collection_job(job_id),
  attempt_no integer not null check (attempt_no >= 1),
  provider_id uuid not null references ops.provider(provider_id),
  provider_task_id text,
  request_payload_id uuid references ops.provider_payload(payload_id),
  submitted_at timestamptz not null,
  collector_component_version_id uuid references ops.component_version(component_version_id),
  created_at timestamptz not null default now(),
  unique (job_id, attempt_no),
  unique (attempt_id, job_id)
);

create table ops.collection_attempt_event (
  attempt_event_id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references ops.collection_attempt(attempt_id),
  event_type ops.attempt_event_type not null,
  event_at timestamptz not null default now(),
  response_payload_id uuid references ops.provider_payload(payload_id),
  provider_status_code text,
  error_code text,
  details jsonb not null default '{}'::jsonb
);

create table ops.observation (
  observation_id uuid primary key default gen_random_uuid(),
  job_id uuid not null unique references ops.collection_job(job_id),
  accepted_attempt_id uuid references ops.collection_attempt(attempt_id),
  observation_state ops.observation_state not null,
  observed_at timestamptz not null,
  received_at timestamptz,
  raw_payload_id uuid references ops.provider_payload(payload_id),
  parser_version_id uuid references ops.component_version(component_version_id),
  normalized_output_sha256 char(64),
  parser_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  constraint observation_attempt_same_job_fk
    foreign key (accepted_attempt_id, job_id)
    references ops.collection_attempt(attempt_id, job_id)
);

create table ops.cost_event (
  cost_event_id uuid primary key default gen_random_uuid(),
  provider_id uuid references ops.provider(provider_id),
  provider_price_version_id uuid references ops.provider_price_version(provider_price_version_id),
  wave_id uuid references ops.collection_wave(wave_id),
  job_id uuid references ops.collection_job(job_id),
  attempt_id uuid references ops.collection_attempt(attempt_id),
  economic_unit_entity_id uuid references core.entity(entity_id),
  purpose text not null,
  billing_unit text,
  billed_units numeric(20,6),
  amount_microusd bigint not null check (amount_microusd >= 0),
  currency char(3) not null default 'USD',
  provider_reference text,
  occurred_at timestamptz not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table ops.cost_allocation (
  cost_allocation_id uuid primary key default gen_random_uuid(),
  cost_event_id uuid not null references ops.cost_event(cost_event_id),
  job_id uuid references ops.collection_job(job_id),
  entity_id uuid references core.entity(entity_id),
  allocation_microusd bigint not null check (allocation_microusd >= 0),
  allocation_basis text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (job_id is not null or entity_id is not null)
);

create table ops.qa_contract_version (
  qa_contract_version_id uuid primary key default gen_random_uuid(),
  contract_code text not null,
  version_code text not null,
  status manifest.version_status not null default 'draft',
  effective_from timestamptz,
  effective_to timestamptz,
  artifact_uri text,
  artifact_sha256 char(64),
  notes text,
  created_at timestamptz not null default now(),
  frozen_at timestamptz,
  unique (contract_code, version_code),
  check ((status <> 'frozen') or frozen_at is not null)
);

create table ops.qa_rule (
  qa_rule_id uuid primary key default gen_random_uuid(),
  qa_contract_version_id uuid not null references ops.qa_contract_version(qa_contract_version_id),
  rule_code text not null,
  scope text not null,
  severity text not null check (severity in ('info','warning','error','critical')),
  description text not null,
  rule_config jsonb not null,
  created_at timestamptz not null default now(),
  unique (qa_contract_version_id, rule_code)
);

create table ops.qa_event (
  qa_event_id uuid primary key default gen_random_uuid(),
  qa_rule_id uuid references ops.qa_rule(qa_rule_id),
  wave_id uuid references ops.collection_wave(wave_id),
  job_id uuid references ops.collection_job(job_id),
  observation_id uuid references ops.observation(observation_id),
  severity text not null check (severity in ('info','warning','error','critical')),
  qa_code text not null,
  expected_value jsonb,
  observed_value jsonb,
  disposition text,
  created_at timestamptz not null default now()
);

create table ops.wave_evaluation (
  wave_evaluation_id uuid primary key default gen_random_uuid(),
  wave_id uuid not null references ops.collection_wave(wave_id),
  qa_contract_version_id uuid not null references ops.qa_contract_version(qa_contract_version_id),
  status ops.wave_status not null,
  expected_jobs integer not null check (expected_jobs >= 0),
  executable_jobs integer not null check (executable_jobs >= 0),
  returned_observations integer not null check (returned_observations >= 0),
  structurally_excluded_jobs integer not null check (structurally_excluded_jobs >= 0),
  failed_jobs integer not null check (failed_jobs >= 0),
  quarantined_jobs integer not null check (quarantined_jobs >= 0),
  metrics jsonb not null default '{}'::jsonb,
  evaluated_at timestamptz not null default now(),
  evaluator_component_version_id uuid references ops.component_version(component_version_id),
  unique (wave_id, evaluated_at)
);
