-- Migration 023_provider_price_v0_1
-- SED Local Search Intelligence Platform
--
-- Versioned provider cost assumption (NOT a methodology change). CLAUDE.md:
-- "Store versioned cost assumptions, not hard-coded prices." The QA / Wave-
-- Acceptance financial reconciliation compares realized DataForSEO unit cost to
-- an *active expected* unit price; without a seeded price the reconciliation can
-- only report PENDING. This seeds the v1 expected price for the DataForSEO SERP
-- standard task (Maps + Organic task_post), measured at 600 µUSD/task on the
-- 2026-09-14 production single-coordinate spike (Maps + Organic both $0.0006).
--
-- This changes no research population/treatment/estimand/geometry/result-depth —
-- it is an ops cost-registry seed only. Drift from this baseline is *measured*
-- (CST001/CST002), never silently absorbed.
--
-- Hand-written + idempotent (INSERT ... SELECT joined to the provider natural
-- key, ON CONFLICT DO NOTHING). No secrets.

insert into ops.provider_price_version
  (provider_id, price_code, endpoint_or_product, billing_unit, unit_amount_microusd,
   currency, effective_from, source_url, source_observed_at, metadata)
select p.provider_id, v.price_code, v.endpoint_or_product, v.billing_unit,
       v.unit_amount_microusd, 'USD', v.effective_from::timestamptz,
       v.source_url, v.source_observed_at::timestamptz, v.metadata::jsonb
from ops.provider p
cross join (values
  ('DFS_SERP_STD_TASK_V1',
   'google/maps + google/organic SERP standard task_post (advanced)',
   'task', 600::bigint, '2026-09-01T00:00:00Z',
   'https://dataforseo.com/pricing', '2026-09-14T00:00:00Z',
   '{"note": "Measured 600 uUSD/task on the 2026-09-14 production single-coordinate spike (Maps + Organic).", "methodology_probe": "SPIKE-20260914", "queue": "standard"}')
) as v(price_code, endpoint_or_product, billing_unit, unit_amount_microusd,
       effective_from, source_url, source_observed_at, metadata)
where p.provider_code = 'dataforseo'
on conflict (provider_id, price_code, effective_from) do nothing;
