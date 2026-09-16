# Enrichment pricing probe — design v0.1

Status: **DESIGN for sign-off**. Offline spec; no paid calls until the owner opens
the gate and says "go". Produces the measured per-unit enrichment prices the parent
PRD §27 requires before any enrichment budget is treated as validated.

## 1. Why

Enrichment is currently out of scope and the repo stores **no** enrichment cost
assumptions (unlike SERP, which has versioned prices in migrations `023`/`024`).
Every enrichment dollar figure quoted so far (~$500–1,000/month core) is an
order-of-magnitude estimate on *unlocked* vendor prices. Parent PRD §27 is explicit:

> No percentage saving, fixed monthly target, or aspirational range should be
> represented as validated until the platform has measured unique entity counts,
> domain/URL/GBP overlap, cache reuse, provider usage, signal-refresh volume, and
> avoided duplicate purchases.

This probe follows the same "probe before you commit" pattern as ADR-0005 (per-
surface capture gates): run a small, real, sampled purchase per signal family,
record the actual per-economic-unit cost, and seed a versioned price assumption.
It measures **price**, not methodology — no permanent enrichment is started.

## 2. What gets priced (signal families × depth)

The economic unit differs per family (parent §8, §10 — one purchase per canonical
economic unit). Depth is the dominant cost lever, so each family is priced at the
depths the research would actually use (Maps child PRD §105–117).

| Signal family | Economic unit | Provider / endpoint (candidate) | Depths priced |
|---|---|---|---|
| GBP profile / My Business Info | business (place_id) | DataForSEO Business Data — Google My Business Info | single |
| Reviews | business (place_id) | DataForSEO Business Data — Google Reviews | **shallow** (count/rating/velocity) vs **deep** (review text for relevance) |
| Backlinks | domain | DataForSEO Backlinks — summary vs. detailed | **summary** (RD/DR/backlink counts) vs **detailed** (backlink list) |
| Page content / crawl *(optional)* | URL | DataForSEO On-Page / content fetch | single (for content-hash change detection, §11) |

Depth matters because parent §10 keeps *detailed* backlinks monthly for the full
research population — the single line item most likely to push enrichment above the
core estimate. Pricing summary vs. detailed separately is the point of the probe.

## 3. Sample design

Draw a **deterministic, stratified** sample from the entities already in the Full
Panel entity graph (real place_ids + domains we already observe — no new discovery):

- **Businesses:** 200, stratified across markets (size tiers), industries, and
  Maps rank bands — **including matched controls, not only top-rankers** (Maps §31).
- **Domains:** 100, stratified the same way, deduplicated (the backlinks economic
  unit is the domain).
- Deep/detailed depths use smaller sub-samples (e.g. 50 businesses for deep reviews,
  30 domains for detailed backlinks) since the unit price, not variance, is the goal.

Sampling is seeded and written to a manifest so the probe is reproducible and the
same units can be re-priced later to detect vendor price drift (§17 cost
effectiveness).

## 4. Method

1. **Gate.** Add a paid gate `RUN_ENRICH_PROBE` (default `0`/closed), mirroring
   `RUN_AIO_PROBE`. Owner opens it for the run, re-closes after. No call fires
   without the open gate **and** explicit owner "go".
2. **Batching / Standard pricing** (parent §15) — async endpoints; latency
   irrelevant.
3. For each sampled unit × family × depth, issue **one** real call, store the
   immutable `raw_observation`, and record an `api_usage` / `cost_event` row with
   provider, endpoint, task count, **economic unit**, module attribution, research
   reason, and actual cost.
4. **Dedup check:** confirm one purchase per canonical economic unit even when a
   business/domain appears under multiple sample strata (validates §8/§12 dedup).
5. Compute **measured µUSD per economic unit** per family × depth, with the spread.

## 5. Outputs

1. **A price-version migration** (`provider_price_version` rows) seeding measured
   `µUSD/unit` per (provider, endpoint, economic unit, depth) — the same mechanism
   as `023`/`024`. Versioned, not hard-coded.
2. **A measured enrichment cost model:** unit prices × the real entity counts
   (~100k businesses / ~62k domains for `GEOGRID13E_V1`) × freshness/reuse
   assumptions → **first-month** and **recurring** enrichment cost, replacing the
   ~$500–1,000 estimate with a measured figure and an explicit detailed-backlinks
   line.
3. **A depth recommendation** (parent §17): which depths justify monthly cadence vs.
   event-triggered (§13) vs. Sentinel-only lightweight (§10), by measured cost.

## 6. Cost of the probe itself

Tiny — it prices, it doesn't enrich the panel. Rough envelope (the probe *measures*
the true unit prices; these are the illustrative ones it replaces):

| Family × depth | Units | ~Unit | ~Cost |
|---|---|---|---|
| GBP | 200 | $0.002 | $0.40 |
| Reviews shallow | 200 | $0.003 | $0.60 |
| Reviews deep | 50 | $0.010 | $0.50 |
| Backlinks summary | 100 | $0.02 | $2.00 |
| Backlinks detailed | 30 | $0.05–0.10 | $1.50–3.00 |
| **Total** | | | **~$5–7** |

## 7. Scope guards

- Probe only: small sample, no permanent enrichment, no signal warehouse build.
- Enrichment remains **out of current scope**; this measures price to unblock the
  §27 baseline, nothing more.
- All providers stay gated; secrets stay server-side (never in this repo).
- Prices land as **versioned assumptions**, never hard-coded (parent §16, Conventions).

## 8. Acceptance checklist (on owner "go")

1. Land the `RUN_ENRICH_PROBE` gate (closed) + the sampler (deterministic, from the
   existing entity graph) — offline, validated with mocked providers.
2. Owner opens the gate → run the ~$5–7 probe on the sample.
3. Record measured unit prices → `provider_price_version` migration.
4. Publish the measured enrichment cost model (first-month + recurring) and depth
   recommendation.
5. Re-close the gate.
