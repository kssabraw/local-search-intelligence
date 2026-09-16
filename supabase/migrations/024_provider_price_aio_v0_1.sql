-- Migration 024_provider_price_aio_v0_1
-- SED Local Search Intelligence Platform
--
-- Versioned provider cost assumption for the AIO surface (NOT a methodology
-- change). CLAUDE.md: "Store versioned cost assumptions, not hard-coded prices."
-- Migration 023 seeded the Maps/Organic SERP standard price (600 µUSD/task);
-- the AIO (DataForSEO AI Mode) task price was unknown until the Stage-2
-- capture-feasibility probe measured it on production: 30 AI-Mode tasks billed
-- 72,000 µUSD total = 2,400 µUSD/task (wave AIOPROBE-AIOPROBE_V0-20260916,
-- 2026-09-16). This seeds that measured v1 expected price so the QA / Wave-
-- Acceptance financial reconciliation can compare realized AIO unit cost to an
-- active expected price (drift is measured, never silently absorbed).
--
-- This changes no research population/treatment/estimand/geometry/result-depth —
-- it is an ops cost-registry seed only.
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
  ('DFS_AIO_AIMODE_TASK_V1',
   'google/ai_mode SERP standard task_post (advanced)',
   'task', 2400::bigint, '2026-09-16T00:00:00Z',
   'https://dataforseo.com/pricing', '2026-09-16T00:00:00Z',
   '{"note": "Measured 2400 uUSD/task on the 2026-09-16 production AIO capture-feasibility probe (30 AI-Mode tasks = 72000 uUSD).", "methodology_probe": "AIOPROBE-AIOPROBE_V0-20260916", "queue": "standard", "surface": "aio"}')
) as v(price_code, endpoint_or_product, billing_unit, unit_amount_microusd,
       effective_from, source_url, source_observed_at, metadata)
where p.provider_code = 'dataforseo'
on conflict (provider_id, price_code, effective_from) do nothing;
