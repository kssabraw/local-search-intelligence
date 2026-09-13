-- Migration 012_enrichment
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
-- ENRICHMENT: SHARED, TEMPORAL, DEDUPLICATED SIGNAL HISTORY
-- ============================================================================

create table enrichment.signal_type (
  signal_type_code text primary key,
  economic_unit_type text not null,
  description text not null,
  universal_or_selective text not null check (universal_or_selective in ('universal','selective','analysis_contract')),
  metadata jsonb not null default '{}'::jsonb
);

create table enrichment.freshness_policy (
  freshness_policy_id uuid primary key default gen_random_uuid(),
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  policy_code text not null,
  ttl interval,
  refresh_mode text not null,
  effective_from timestamptz,
  effective_to timestamptz,
  policy jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (signal_type_code, policy_code)
);

create table enrichment.enrichment_request (
  enrichment_request_id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references core.entity(entity_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  wave_id uuid references ops.collection_wave(wave_id),
  trigger_job_id uuid references ops.collection_job(job_id),
  trigger_observation_id uuid references ops.observation(observation_id),
  trigger_reason text not null,
  economic_unit_key text not null,
  freshness_policy_id uuid references enrichment.freshness_policy(freshness_policy_id),
  freshness_decision enrichment.freshness_state not null default 'unknown',
  status enrichment.request_status not null default 'planned',
  dedup_reused_snapshot_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  requested_at timestamptz not null default now()
);

create table enrichment.enrichment_run (
  enrichment_run_id uuid primary key default gen_random_uuid(),
  enrichment_request_id uuid not null references enrichment.enrichment_request(enrichment_request_id),
  provider_id uuid references ops.provider(provider_id),
  component_version_id uuid references ops.component_version(component_version_id),
  request_payload_id uuid references ops.provider_payload(payload_id),
  response_payload_id uuid references ops.provider_payload(payload_id),
  cost_event_id uuid references ops.cost_event(cost_event_id),
  status enrichment.request_status not null,
  started_at timestamptz,
  finished_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table enrichment.signal_snapshot (
  signal_snapshot_id uuid primary key default gen_random_uuid(),
  entity_id uuid not null references core.entity(entity_id),
  signal_type_code text not null references enrichment.signal_type(signal_type_code),
  enrichment_run_id uuid references enrichment.enrichment_run(enrichment_run_id),
  provider_id uuid references ops.provider(provider_id),
  source_payload_id uuid references ops.provider_payload(payload_id),
  freshness_policy_id uuid references enrichment.freshness_policy(freshness_policy_id),
  observed_at timestamptz not null,
  effective_at timestamptz,
  last_verified_at timestamptz,
  freshness_state enrichment.freshness_state not null,
  value_sha256 char(64),
  value_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table enrichment.enrichment_request
  add constraint enrichment_request_reused_snapshot_fk
  foreign key (dedup_reused_snapshot_id)
  references enrichment.signal_snapshot(signal_snapshot_id);

create table enrichment.business_identity_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  display_name text,
  physical_location_known boolean,
  serves_research_market boolean,
  service_area_business boolean,
  phone text,
  address_text text,
  founding_year integer,
  business_type text,
  license_identifiers jsonb not null default '{}'::jsonb
);

create table enrichment.gbp_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  primary_category text,
  additional_categories text[],
  rating numeric(4,2),
  review_count integer,
  website_url_entity_id uuid references core.web_url(entity_id),
  phone text,
  address_text text,
  services jsonb not null default '[]'::jsonb,
  attributes jsonb not null default '{}'::jsonb,
  posts_summary jsonb not null default '{}'::jsonb,
  photos_summary jsonb not null default '{}'::jsonb,
  check (review_count is null or review_count >= 0)
);

create table enrichment.review_state_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  rating numeric(4,2),
  review_count integer,
  newest_review_at timestamptz,
  oldest_review_at timestamptz,
  provider_summary jsonb not null default '{}'::jsonb,
  check (review_count is null or review_count >= 0)
);

create table enrichment.review (
  review_id uuid primary key default gen_random_uuid(),
  business_entity_id uuid not null references core.entity(entity_id),
  provider_id uuid references ops.provider(provider_id),
  provider_review_id text,
  content_sha256 char(64) not null,
  rating numeric(4,2),
  reviewer_identifier text,
  published_at timestamptz,
  first_seen_at timestamptz not null,
  body_raw text,
  source_payload_id uuid references ops.provider_payload(payload_id),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table enrichment.website_site_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  domain_entity_id uuid not null references core.web_domain(entity_id),
  sitemap_sha256 char(64),
  sitemap_state jsonb not null default '{}'::jsonb,
  last_modified_header text,
  etag text,
  metadata jsonb not null default '{}'::jsonb
);

create table enrichment.website_page_version (
  page_version_id uuid primary key default gen_random_uuid(),
  url_entity_id uuid not null references core.web_url(entity_id),
  domain_entity_id uuid references core.web_domain(entity_id),
  observed_at timestamptz not null,
  raw_blob_id uuid references ops.raw_blob(blob_id),
  content_sha256 char(64),
  rendered_text_sha256 char(64),
  structured_data_sha256 char(64),
  http_status integer,
  etag text,
  last_modified_header text,
  canonical_url_entity_id uuid references core.web_url(entity_id),
  parser_version_id uuid references ops.component_version(component_version_id),
  extraction_jsonb jsonb not null default '{}'::jsonb,
  first_seen_at timestamptz not null,
  last_checked_at timestamptz not null,
  last_changed_at timestamptz,
  created_at timestamptz not null default now(),
  unique (url_entity_id, observed_at)
);

create table enrichment.link_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  target_entity_id uuid not null references core.entity(entity_id),
  domain_rating numeric(10,4),
  url_rating numeric(10,4),
  referring_domains bigint,
  backlinks bigint,
  dofollow_backlinks bigint,
  metrics jsonb not null default '{}'::jsonb,
  check (referring_domains is null or referring_domains >= 0),
  check (backlinks is null or backlinks >= 0),
  check (dofollow_backlinks is null or dofollow_backlinks >= 0)
);

create table enrichment.brand_demand_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  brand_entity_id uuid references core.entity(entity_id),
  query_set jsonb not null default '[]'::jsonb,
  volume_metrics jsonb not null default '{}'::jsonb
);

create table enrichment.social_profile_snapshot (
  signal_snapshot_id uuid primary key references enrichment.signal_snapshot(signal_snapshot_id),
  profile_entity_id uuid not null references core.profile_entity(entity_id),
  platform text not null,
  profile_url_entity_id uuid references core.web_url(entity_id),
  activity_metrics jsonb not null default '{}'::jsonb,
  profile_metadata jsonb not null default '{}'::jsonb
);

create table enrichment.source_content_version (
  source_content_version_id uuid primary key default gen_random_uuid(),
  source_entity_id uuid not null references core.entity(entity_id),
  url_entity_id uuid references core.web_url(entity_id),
  observed_at timestamptz not null,
  raw_blob_id uuid references ops.raw_blob(blob_id),
  content_sha256 char(64) not null,
  rendered_text_sha256 char(64),
  parser_version_id uuid references ops.component_version(component_version_id),
  extraction_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (source_entity_id, observed_at)
);

create table enrichment.embedding (
  embedding_id uuid primary key default gen_random_uuid(),
  entity_id uuid references core.entity(entity_id),
  observed_object_id uuid references core.observed_object(observed_object_id),
  content_sha256 char(64) not null,
  embedding_model_version_id uuid not null references ops.component_version(component_version_id),
  embedding_dimension integer not null check (embedding_dimension > 0),
  embedding vector not null,
  source_content_uri text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (entity_id is not null or observed_object_id is not null),
  unique (entity_id, observed_object_id, content_sha256, embedding_model_version_id)
);
