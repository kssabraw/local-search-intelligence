-- Migration 018_seed_lookups
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
-- SEED CONTROLLED LOOKUPS
-- ============================================================================

insert into manifest.surface(surface_code, surface_name, is_primary_observation_surface) values
  ('maps','Google Maps / Local Pack',true),
  ('organic','Google Organic',true),
  ('aio','Google AIO / AI Mode',true),
  ('chatgpt','ChatGPT Local Search',true),
  ('google_top50','Google Top-50 Brand/Service/Location Evidence',false)
on conflict (surface_code) do nothing;

insert into core.entity_type(entity_type_code, description) values
  ('organization','Operating/legal organization'),
  ('brand','Brand, trade name, or DBA'),
  ('business_location','Specific local location or service operation'),
  ('google_business_profile','Google Business Profile / Google Place asset'),
  ('domain','Canonical web domain'),
  ('url','Canonical URL/page asset'),
  ('directory_profile','Directory profile asset'),
  ('review_profile','Review-platform profile asset'),
  ('social_profile','Official or observed social profile asset'),
  ('booking_destination','Booking/contact destination asset'),
  ('publisher_source','Publisher/editorial source entity'),
  ('source_asset','Generic evidence/source asset'),
  ('other','Other canonical entity type')
on conflict (entity_type_code) do nothing;

insert into core.relationship_type(relationship_type_code, description) values
  ('operated_by','Business location/service operation is operated by an organization'),
  ('brand_of','Brand relationship'),
  ('franchisee_of','Franchisee relationship'),
  ('member_of','Membership/brand-network relationship'),
  ('gbp_for','GBP represents a business location/service operation'),
  ('domain_for','Domain represents an entity'),
  ('url_for','URL/page represents or belongs to an entity'),
  ('profile_for','External profile represents an entity'),
  ('source_supports','Source asset supports/relates to an entity'),
  ('merged_into','Later canonical merge relationship'),
  ('same_as','Asserted equivalent entity relationship')
on conflict (relationship_type_code) do nothing;

insert into enrichment.signal_type(signal_type_code, economic_unit_type, description, universal_or_selective) values
  ('business_identity','business/location','Slow-changing business identity facts','universal'),
  ('gbp_state','GBP','GBP categories, rating, review count, services, attributes, website destination and profile state','universal'),
  ('review_state','business/location','Cheap current review count/rating/recency state','universal'),
  ('review_body','review','Append-only individual review text/history','selective'),
  ('website_site','domain','Site/sitemap/change-detection state','universal'),
  ('website_page','URL/content hash','Versioned page content and parsed state','universal'),
  ('backlinks','domain/URL','Approved link/referring-domain/authority history','universal'),
  ('brand_demand','brand/business','Approved brand-demand/search-volume history','universal'),
  ('social_profile','social profile','Direct social profile/activity evidence where selectively authorized','selective'),
  ('source_content','source URL/content hash','AIO/ChatGPT/source evidence content snapshot','selective'),
  ('top50_evidence','business/query','Brand + service + location Top-50 Google evidence layer','universal')
on conflict (signal_type_code) do nothing;

-- ============================================================================
-- COMMENTS ON CRITICAL SEMANTICS
-- ============================================================================

comment on table ops.provider_price_version is
'Versioned provider pricing evidence used for cost drift and budget checks. Price changes create new rows rather than overwriting history.';

comment on table ops.qa_contract_version is
'Frozen/versioned operational QA and wave-acceptance contract. Threshold changes create a new version and are never retrofitted after seeing outcomes.';

comment on table ops.qa_rule is
'Machine-readable QA rule bound to a versioned QA contract. qa_event rows should reference the rule that fired.';

comment on table ops.collection_job is
'One deterministic planned scientific collection unit. job_key is a SHA-256 idempotency key over methodology/wave/surface/industry/market/treatment/coordinate/replicate. Rows are append-only.';

comment on table ops.observation is
'One terminal scientific observation per planned job. Technical attempts are separate. Failed/refusal/clarification/no-recommendation outcomes remain observations rather than being silently replaced.';

comment on table ops.raw_blob is
'Content-addressed immutable raw bytes. Store complete provider payloads in a private Supabase Storage bucket; this table stores hash/path/size metadata.';

comment on table core.observed_object is
'Normalized extraction of an observed business/source/URL/profile/etc. It is NOT canonical identity. Raw returned values remain immutable.';

comment on table core.resolution_assertion is
'Append-only versioned identity adjudication. Later resolution may supersede an earlier assertion without rewriting the original observation or observed object.';

comment on view core.latest_resolution is
'Convenience view of latest resolution assertions. It is rebuildable and MUST NOT replace historical resolution-version provenance in analyses.';

comment on table enrichment.signal_snapshot is
'Temporal shared signal history. Cached reuse must reference prior snapshots; it must never be represented as a newly observed fresh snapshot.';

comment on table enrichment.embedding is
'Content-hash and model-version keyed shared embeddings. Stored once and reused across surfaces when scientifically equivalent; no ANN index is created until a fixed model/dimension and measured query need justify it.';

comment on table chatgpt.product_event is
'Versioned registry of observed/known ChatGPT product changes that may create structural breaks or comparability concerns.';

comment on table research.dataset_build is
'Reproducible derived dataset build with methodology version, entity-graph release, analysis specification, source cutoff, code/config provenance and artifact hashes.';

comment on table research.finding is
'Research finding registry. Predictive/associational findings are not causal unless association_or_causal = causal under a qualifying design.';
