-- Migration 016_views
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
-- REBUILDABLE "LATEST" VIEWS — CONVENIENCE, NEVER SOURCE OF RAW TRUTH
-- ============================================================================

create view ops.current_wave_state as
select distinct on (we.wave_id)
  we.wave_id,
  we.status,
  we.event_at,
  we.actor,
  we.details
from ops.wave_event we
order by we.wave_id, we.event_at desc, we.wave_event_id desc;

create view ops.current_job_state as
select distinct on (je.job_id)
  je.job_id,
  je.status,
  je.event_at,
  je.attempt_no,
  je.actor,
  je.reason_code,
  je.details
from ops.job_event je
order by je.job_id, je.event_at desc, je.job_event_id desc;

create view core.latest_resolution as
select distinct on (rr.observed_object_id)
  rr.observed_object_id,
  ra.resolution_assertion_id,
  ra.entity_graph_release_id,
  ra.resolved_entity_id,
  ra.resolution_state,
  ra.confidence_value,
  ra.confidence_semantics,
  ra.created_at
from core.resolution_assertion ra
join core.resolution_run rr on rr.resolution_run_id = ra.resolution_run_id
order by rr.observed_object_id, ra.created_at desc, ra.resolution_assertion_id desc;

create view enrichment.latest_signal_snapshot as
select distinct on (ss.entity_id, ss.signal_type_code)
  ss.*
from enrichment.signal_snapshot ss
order by ss.entity_id, ss.signal_type_code, ss.observed_at desc, ss.signal_snapshot_id desc;
