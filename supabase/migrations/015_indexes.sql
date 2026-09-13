-- Migration 015_indexes
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
-- INDEXES
-- ============================================================================

create index provider_price_effective_idx
  on ops.provider_price_version(provider_id, endpoint_or_product, effective_from desc);

create index methodology_industry_lookup_idx
  on manifest.methodology_industry(methodology_version_id, ordinal);

create index methodology_market_lookup_idx
  on manifest.methodology_market(methodology_version_id, ordinal);

create index market_coordinate_exec_idx
  on manifest.market_coordinate(methodology_version_id, market_id, eligibility);

create index treatment_lookup_idx
  on manifest.treatment(methodology_version_id, industry_id, treatment_kind, sequence);

create index surface_treatment_lookup_idx
  on manifest.surface_treatment(methodology_version_id, surface_id, active);

create index collection_wave_method_time_idx
  on ops.collection_wave(methodology_version_id, scheduled_for);

create index wave_event_latest_idx
  on ops.wave_event(wave_id, event_at desc);

create index collection_job_wave_surface_idx
  on ops.collection_job(wave_id, surface_id);

create index collection_job_market_industry_idx
  on ops.collection_job(market_id, industry_id, surface_id);

create index collection_job_treatment_coordinate_idx
  on ops.collection_job(surface_treatment_id, coordinate_id);

create index job_event_latest_idx
  on ops.job_event(job_id, event_at desc);

create index provider_payload_task_idx
  on ops.provider_payload(provider_id, provider_task_id);

create index attempt_job_idx
  on ops.collection_attempt(job_id, attempt_no);

create index attempt_event_latest_idx
  on ops.collection_attempt_event(attempt_id, event_at desc);

create index observation_observed_at_brin
  on ops.observation using brin(observed_at);

create index cost_event_wave_provider_idx
  on ops.cost_event(wave_id, provider_id, occurred_at);

create index cost_event_entity_idx
  on ops.cost_event(economic_unit_entity_id, occurred_at);

create index qa_rule_contract_idx
  on ops.qa_rule(qa_contract_version_id, severity, rule_code);

create index qa_event_wave_code_idx
  on ops.qa_event(wave_id, qa_code, severity);

create index observed_object_observation_idx
  on core.observed_object(observation_id, object_kind);

create index observed_object_name_trgm_idx
  on core.observed_object using gin (raw_name gin_trgm_ops);

create index resolution_run_object_idx
  on core.resolution_run(observed_object_id, run_at desc);

create index resolution_candidate_run_rank_idx
  on core.resolution_candidate(resolution_run_id, candidate_rank);

create index resolution_assertion_object_idx
  on core.resolution_assertion(resolution_run_id, created_at desc);

create index resolution_assertion_entity_idx
  on core.resolution_assertion(resolved_entity_id, created_at desc)
  where resolved_entity_id is not null;

create index entity_alias_trgm_idx
  on core.entity_alias_assertion using gin (normalized_alias gin_trgm_ops);

create index entity_relationship_from_idx
  on core.entity_relationship_assertion(from_entity_id, relationship_type_code, created_at desc);

create index entity_relationship_to_idx
  on core.entity_relationship_assertion(to_entity_id, relationship_type_code, created_at desc);

create index maps_result_observation_rank_idx
  on maps.result(observation_id, rank_absolute);

create index maps_result_object_idx
  on maps.result(observed_object_id);

create index organic_result_observation_rank_idx
  on organic.result(observation_id, rank_absolute);

create index organic_result_object_idx
  on organic.result(observed_object_id);

create index aio_business_obs_idx
  on aio.business_appearance(observation_id, appearance_sequence);

create index aio_source_obs_idx
  on aio.source_occurrence(observation_id, source_sequence);

create index aio_citation_source_idx
  on aio.citation(source_occurrence_id);

create index chatgpt_product_event_time_idx
  on chatgpt.product_event(event_at desc);

create index chatgpt_fanout_observed_idx
  on chatgpt.fanout_query(observation_id, sequence)
  where origin = 'observed';

create index chatgpt_source_fanout_idx
  on chatgpt.retrieved_source(fanout_query_id, retrieval_position);

create index chatgpt_mention_obs_idx
  on chatgpt.entity_mention(observation_id, mention_sequence);

create index chatgpt_destination_mention_idx
  on chatgpt.destination(entity_mention_id, destination_sequence);

create index enrichment_request_economic_unit_idx
  on enrichment.enrichment_request(signal_type_code, economic_unit_key, requested_at desc);

create index signal_snapshot_entity_signal_time_idx
  on enrichment.signal_snapshot(entity_id, signal_type_code, observed_at desc);

create index signal_snapshot_observed_at_brin
  on enrichment.signal_snapshot using brin(observed_at);

create index review_business_time_idx
  on enrichment.review(business_entity_id, published_at desc);

create unique index review_provider_id_unique_idx
  on enrichment.review(provider_id, provider_review_id)
  where provider_review_id is not null;

create unique index review_hash_fallback_unique_idx
  on enrichment.review(business_entity_id, content_sha256, coalesce(published_at, first_seen_at));

create index page_version_url_time_idx
  on enrichment.website_page_version(url_entity_id, observed_at desc);

create index source_content_entity_time_idx
  on enrichment.source_content_version(source_entity_id, observed_at desc);

create index source_content_hash_idx
  on enrichment.source_content_version(source_entity_id, content_sha256);

create index embedding_entity_model_idx
  on enrichment.embedding(entity_id, embedding_model_version_id)
  where entity_id is not null;

create index embedding_object_model_idx
  on enrichment.embedding(observed_object_id, embedding_model_version_id)
  where observed_object_id is not null;

create index dataset_build_method_time_idx
  on research.dataset_build(methodology_version_id, source_observation_cutoff desc);

create index feature_value_entity_idx
  on research.feature_value(entity_id, feature_build_id)
  where entity_id is not null;

create index feature_value_observation_idx
  on research.feature_value(observation_id, feature_build_id)
  where observation_id is not null;

create index cohort_member_entity_idx
  on research.cohort_member(entity_id, cohort_id);

create index finding_status_idx
  on research.finding(status, evidence_label);
