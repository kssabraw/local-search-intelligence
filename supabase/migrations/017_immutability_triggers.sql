-- Migration 017_immutability_triggers
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
-- IMMUTABILITY PROTECTIONS
-- ============================================================================

create or replace function ops.reject_update_delete()
returns trigger
language plpgsql
as $$
begin
  raise exception 'table %.% is append-only; insert a new version/assertion/event instead',
    tg_table_schema, tg_table_name;
end;
$$;

-- Raw/blob/provider evidence
create trigger raw_blob_append_only
before update or delete on ops.raw_blob
for each row execute function ops.reject_update_delete();

create trigger provider_price_append_only
before update or delete on ops.provider_price_version
for each row execute function ops.reject_update_delete();

create trigger provider_payload_append_only
before update or delete on ops.provider_payload
for each row execute function ops.reject_update_delete();

create trigger collection_job_append_only
before update or delete on ops.collection_job
for each row execute function ops.reject_update_delete();

create trigger observation_append_only
before update or delete on ops.observation
for each row execute function ops.reject_update_delete();

-- Normalized raw surface evidence
create trigger observed_object_append_only
before update or delete on core.observed_object
for each row execute function ops.reject_update_delete();

create trigger maps_observation_append_only
before update or delete on maps.observation
for each row execute function ops.reject_update_delete();

create trigger maps_result_append_only
before update or delete on maps.result
for each row execute function ops.reject_update_delete();

create trigger organic_observation_append_only
before update or delete on organic.observation
for each row execute function ops.reject_update_delete();

create trigger organic_result_append_only
before update or delete on organic.result
for each row execute function ops.reject_update_delete();

create trigger aio_observation_append_only
before update or delete on aio.observation
for each row execute function ops.reject_update_delete();

create trigger aio_presentation_append_only
before update or delete on aio.presentation_unit
for each row execute function ops.reject_update_delete();

create trigger aio_business_append_only
before update or delete on aio.business_appearance
for each row execute function ops.reject_update_delete();

create trigger aio_source_append_only
before update or delete on aio.source_occurrence
for each row execute function ops.reject_update_delete();

create trigger aio_citation_append_only
before update or delete on aio.citation
for each row execute function ops.reject_update_delete();

create trigger aio_destination_append_only
before update or delete on aio.destination
for each row execute function ops.reject_update_delete();

create trigger aio_evidence_append_only
before update or delete on aio.evidence_link
for each row execute function ops.reject_update_delete();

create trigger chatgpt_observation_append_only
before update or delete on chatgpt.observation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_fanout_append_only
before update or delete on chatgpt.fanout_query
for each row execute function ops.reject_update_delete();

create trigger chatgpt_source_append_only
before update or delete on chatgpt.retrieved_source
for each row execute function ops.reject_update_delete();

create trigger chatgpt_citation_append_only
before update or delete on chatgpt.citation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_mention_append_only
before update or delete on chatgpt.entity_mention
for each row execute function ops.reject_update_delete();

create trigger chatgpt_recommendation_append_only
before update or delete on chatgpt.recommendation
for each row execute function ops.reject_update_delete();

create trigger chatgpt_rationale_append_only
before update or delete on chatgpt.rationale
for each row execute function ops.reject_update_delete();

create trigger chatgpt_destination_append_only
before update or delete on chatgpt.destination
for each row execute function ops.reject_update_delete();

create trigger chatgpt_evidence_append_only
before update or delete on chatgpt.evidence_link
for each row execute function ops.reject_update_delete();

-- Resolution history
create trigger resolution_run_append_only
before update or delete on core.resolution_run
for each row execute function ops.reject_update_delete();

create trigger resolution_candidate_append_only
before update or delete on core.resolution_candidate
for each row execute function ops.reject_update_delete();

create trigger resolution_assertion_append_only
before update or delete on core.resolution_assertion
for each row execute function ops.reject_update_delete();

create trigger relationship_assertion_append_only
before update or delete on core.entity_relationship_assertion
for each row execute function ops.reject_update_delete();

create trigger external_identifier_assertion_append_only
before update or delete on core.external_identifier_assertion
for each row execute function ops.reject_update_delete();

create trigger entity_alias_assertion_append_only
before update or delete on core.entity_alias_assertion
for each row execute function ops.reject_update_delete();

-- Temporal enrichment evidence
create trigger signal_snapshot_append_only
before update or delete on enrichment.signal_snapshot
for each row execute function ops.reject_update_delete();

create trigger review_append_only
before update or delete on enrichment.review
for each row execute function ops.reject_update_delete();

create trigger page_version_append_only
before update or delete on enrichment.website_page_version
for each row execute function ops.reject_update_delete();

create trigger source_content_append_only
before update or delete on enrichment.source_content_version
for each row execute function ops.reject_update_delete();

create trigger embedding_append_only
before update or delete on enrichment.embedding
for each row execute function ops.reject_update_delete();

create trigger cost_event_append_only
before update or delete on ops.cost_event
for each row execute function ops.reject_update_delete();

create trigger cost_allocation_append_only
before update or delete on ops.cost_allocation
for each row execute function ops.reject_update_delete();
