-- Migration 011_chatgpt
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
-- CHATGPT SURFACE
-- ============================================================================

create table chatgpt.observation (
  observation_id uuid primary key references ops.observation(observation_id),
  response_outcome text not null check (response_outcome in (
    'answered_local','clarification_requested','generic_guidance_only',
    'no_local_recommendations','refusal','error','other'
  )),
  response_text_raw text,
  response_markdown_raw text,
  product_name text,
  model_name text,
  search_available boolean,
  search_invoked boolean,
  search_invocation_status text,
  observable_tool_metadata jsonb not null default '{}'::jsonb,
  account_context_metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table chatgpt.product_event (
  product_event_id uuid primary key default gen_random_uuid(),
  event_code text not null unique,
  event_at timestamptz not null,
  product_name text not null default 'ChatGPT',
  event_type text not null,
  description text not null,
  source_url text,
  observed_evidence jsonb not null default '{}'::jsonb,
  comparability_impact text,
  methodology_version_id uuid references manifest.methodology_version(methodology_version_id),
  created_at timestamptz not null default now()
);

create table chatgpt.fanout_query (
  fanout_query_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  sequence integer not null check (sequence >= 1),
  origin text not null check (origin in ('observed','derived_inferred')),
  query_text text not null,
  stage text,
  provider_raw text,
  query_timestamp timestamptz,
  location_context jsonb not null default '{}'::jsonb,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, sequence, origin)
);

create table chatgpt.retrieved_source (
  retrieved_source_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  fanout_query_id uuid references chatgpt.fanout_query(fanout_query_id),
  source_sequence integer not null check (source_sequence >= 1),
  retrieval_position integer,
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  source_url_raw text,
  source_title_raw text,
  publisher_raw text,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, source_sequence)
);

create table chatgpt.citation (
  citation_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  retrieved_source_id uuid not null references chatgpt.retrieved_source(retrieved_source_id),
  citation_sequence integer not null check (citation_sequence >= 1),
  marker_raw text,
  cited_span_raw text,
  created_at timestamptz not null default now(),
  unique (observation_id, citation_sequence)
);

create table chatgpt.entity_mention (
  entity_mention_id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references chatgpt.observation(observation_id),
  mention_sequence integer not null check (mention_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  raw_span text not null,
  mention_position integer,
  polarity text check (polarity in ('positive','neutral','cautionary','negative')),
  mention_linked boolean,
  supporting_citation_present boolean,
  provider_fields jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (observation_id, mention_sequence)
);

create table chatgpt.recommendation (
  recommendation_id uuid primary key default gen_random_uuid(),
  entity_mention_id uuid not null unique references chatgpt.entity_mention(entity_mention_id),
  recommended boolean not null,
  recommendation_strength smallint not null check (recommendation_strength between 0 and 4),
  recommendation_position integer,
  shortlist_member boolean not null default false,
  top_choice boolean not null default false,
  explicit_ranking boolean not null default false,
  explicit_rank integer,
  created_at timestamptz not null default now(),
  check (
    (recommended = false and recommendation_strength = 0)
    or
    (recommended = true and recommendation_strength between 1 and 4)
  ),
  check (recommendation_position is null or recommendation_position >= 1),
  check (explicit_rank is null or explicit_rank >= 1),
  check (recommended = true or (shortlist_member = false and top_choice = false))
);

create table chatgpt.rationale (
  rationale_id uuid primary key default gen_random_uuid(),
  recommendation_id uuid not null references chatgpt.recommendation(recommendation_id),
  rationale_sequence integer not null check (rationale_sequence >= 1),
  category text not null check (category in (
    'review_reputation','service_match','availability','location','price_value',
    'experience_longevity','specialization','credentials','brand_reputation',
    'third_party_recognition','other','unclear'
  )),
  raw_text text,
  raw_span text,
  classifier_version_id uuid references ops.component_version(component_version_id),
  confidence numeric(8,6),
  created_at timestamptz not null default now(),
  unique (recommendation_id, rationale_sequence),
  check (confidence is null or confidence between 0 and 1)
);

create table chatgpt.destination (
  destination_id uuid primary key default gen_random_uuid(),
  entity_mention_id uuid not null references chatgpt.entity_mention(entity_mention_id),
  destination_sequence integer not null check (destination_sequence >= 1),
  observed_object_id uuid not null references core.observed_object(observed_object_id),
  destination_url_raw text not null,
  destination_type text not null check (destination_type in (
    'business_homepage','business_service_page','business_location_page','business_other_page',
    'google_maps','google_business_profile','directory_profile','review_platform',
    'publisher_editorial','social_profile','booking_contact','other'
  )),
  direct_business_link boolean,
  third_party_business_link boolean,
  created_at timestamptz not null default now(),
  unique (entity_mention_id, destination_sequence)
);

create table chatgpt.evidence_link (
  chatgpt_evidence_link_id uuid primary key default gen_random_uuid(),
  citation_id uuid not null references chatgpt.citation(citation_id),
  entity_mention_id uuid references chatgpt.entity_mention(entity_mention_id),
  recommendation_id uuid references chatgpt.recommendation(recommendation_id),
  relationship_type text not null check (relationship_type in (
    'supports_business','supports_claim','supports_comparison','supports_list','general_background','unclear'
  )),
  claim_text_raw text,
  created_at timestamptz not null default now(),
  check (entity_mention_id is not null or recommendation_id is not null)
);
