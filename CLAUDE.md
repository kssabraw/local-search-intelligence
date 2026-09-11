# Local Search Intelligence Platform

Context for Claude Code working in this repo. **Read this first.**

> ⚠️ **PUBLIC REPOSITORY — NEVER COMMIT SECRETS.** DataForSEO credentials, the Supabase service-role key, OpenAI/vendor API keys, Railway tokens, and any other secret live only in Railway/Supabase secret management and a git-ignored local `.env`. Never in code, migrations, config, tests, fixtures, or committed docs. Log lines must never print keys or tokens.

## What this is

Amazing Rankings' (AR) **Local Search Intelligence Platform** — a longitudinal **research** platform that measures how Google and AI assistants allocate *local* business visibility across geographic space and time, across four observation surfaces: **Google Maps / Local Pack**, **Google Organic**, **Google AI Overviews (AIO / AI Mode)**, and **ChatGPT local recommendations**.

It is **not** a client-facing SaaS, a rank tracker, or a heatmap product. It produces versioned, defensible *research findings* about what predicts local visibility. A later **Client Mode** diagnoses a specific client against those findings.

**This is a separate system from the AR Tools operational agency suite** (a different repo/Supabase/Railway). AR Tools is a sibling; the eventual Client Mode ↔ AR Tools link is a later cross-system integration, out of current scope. ("SED Society" appears in older PRD text — it is a dead agency name; this is Amazing Rankings.)

## Status

**Greenfield. Nothing is built yet.** This file records the agreed plan of record. The first code deliverables are the two shared contracts (see *Artifacts*), authored for owner sign-off **before** any collector code.

## Authoritative documents (the PRD hierarchy)

Governance runs parent → child. The parent controls shared mechanics; each child controls its own surface science. On conflict, the parent wins for shared infrastructure; the child wins for its surface's measurement semantics.

1. **Parent — Unified Research Architecture & Cost Optimization PRD** (Google Doc `1Y5CmSWDpSKryfkmcbPh25UG_yfyyvwZV2hdkh1hh3Sc`). Owns: canonical entities, immutable raw observations, provider/economic-unit deduplication, shared signal warehouse, content-addressed assets/embeddings, Python/SQL-before-LLM gating, queue/scheduler, cost ledger, missingness states, finding + intervention infrastructure.
2. **Maps/Organic child — Geo-Grid Ranking Research PRD** (`1pP1dKD341vtzBEA5w4H0-YidX3N2CRVr41cyDV8kD_A`). Maps Top-10 semantics, distance/proximity, DAVS/Effective Ranking Radius, 13-point geometry, coverage vs rank vs reach.
3. **AIO child — Local AI Overview Research & Citation Intelligence PRD** (`1oDYH3_oYOvjD3g8jtt13QchxM0C8lgT1B_mq68V-5JI`). Three visibility forms (source/entity/destination), local-business-card + embedded-GBP surfaces, placement/above-the-fold, 9-point geometry.
4. **ChatGPT child — ChatGPT Local Search & Recommendation Intelligence PRD** (`1YfWjb9gHzMr8uNriEwdQePhygFp-mjuN0C0c1dyvn54`). Five outcome families, replicate/frequency-based measures, no geo grid, fanout capture.
5. **Collection Manifest v1.0** (`FROZEN_EXECUTABLE`; Google Drive file `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`). The frozen 25×50 universe + Maps/Organic 13-point geometry + civic anchors. See reconciliation flags under *Artifacts*.

## Architecture

One **shared foundation**; each surface is a module that rides on it. **No parallel per-surface stacks.**

Shared foundation (Phase 1): canonical research universe (industries / markets / queries / coordinates / panels) · `provider_task` + immutable `raw_observation` · canonical business/domain/URL entity graph · `api_usage` cost ledger · methodology versioning · one unified scheduler + job-queue contract.

**Hard architectural rules** (from the parent + children):
- **Immutable raw observations.** Never overwrite a provider response. Raw JSON → content-addressed object storage, **fail-on-exists**, gzipped. Derived/normalized tables are rebuildable from raw; raw is never rebuilt.
- **Canonical entity resolution**, place_id-first (then domain/phone/address/coords), storing confidence + provenance. Never silently merge ambiguous entities.
- **Missing ≠ zero.** Distinct missingness states: `structural_water_exclusion`, `outside_country_exclusion`, `configuration_failure`, `provider_not_observable`. An excluded coordinate is never rank 0 / no-visibility.
- **No composite visibility score**, within or across surfaces. Preserve raw outcomes (rank / coverage / reach / excess-performance / persistence / transition; the AIO source/entity/destination trio; the ChatGPT five families) separately.
- **Python/SQL/provider-parsing/vector-math before LLM.** An LLM never re-extracts structured provider fields, never manufactures measurements/effect-sizes/findings, and is gated behind deterministic + cache + embedding stages.
- **No silent methodology drift.** Any change to industries, markets, queries, geometry, radius, coordinate algorithm, provider settings, or result depth requires a new versioned methodology / experiment version.
- **Cost savings come from dedup / caching / progressive enrichment / change-detection / batching** — never from degrading a permanent panel.

## Stack (locked)

Python 3.11+ · FastAPI · Supabase/Postgres as source of truth · `async_jobs` table + asyncio worker (no Redis/Celery) · Railway execution · `pgvector` · Gemini embeddings. Raw payloads → Supabase Storage (content-addressed, fail-on-exists, gzipped); revisit S3/R2 only if measured production cost demands. No frontend in current scope (collectors + QA + SQL/notebook analysis).

## Build stages & scope

Surfaces are built **sequentially on one shared foundation**, cheapest/most-settled first:

| Stage | Surface | Capture | Universe |
|---|---|---|---|
| 1 | **Maps + Organic** | DataForSEO SERP (settings locked in the Maps/Organic pilot protocol) | pilot: 15 cells × 4 queries × 13 points (nested-9 tagged) × 2 surfaces = 1,560 pre-water jobs |
| 2 | **AIO** | DataForSEO AI Overview / AI Mode — **capture-feasibility gate first** | 25×50 × 10 conditions × 9 points (center + N/S/E/W @2.5mi + @5mi) |
| 3 | **ChatGPT** | Vendor-based (must capture the real consumer product + fanout, not a wrapped API call) — **capture-feasibility gate first** | 25×50 × 10 prompts × 3 fresh-context replicates, **no geo grid** |

**Cadence (all surfaces):** monthly Full Panel + weekly fixed Research Sentinel (5 industries × 10 markets); the monthly wave doubles as that week's Sentinel.

**The Stage-1 pilot** (the immediate near-term work) validates cost / reliability / data quality and the **13-vs-9 geometry** question. Default decision: **RETAIN_13**; only PROPOSE_9_FOR_APPROVAL if the four 3-mile points' marginal cost is clearly disproportionate to their marginal entity/spatial/longitudinal/explanatory value. No geometry change without explicit owner approval.

**Per-surface capture gate (ADR-0005):** before committing a surface's schema, run a small live probe confirming the provider/vendor actually returns the fields that surface's model requires (AIO: element rectangles, citation reference-vs-link, local-business cards, embedded GBP, destination/SearchViewer types; ChatGPT: consumer-product answer + citations/links/destinations + observed fanout). Build columns for what the provider *proves* it returns; mark the rest `provider_not_observable`, never absent.

**Explicitly OUT of current scope:** enrichment / signal warehouse (GBP / reviews / backlinks / NAP), transition/event system, finding registry, Strategy Evidence Framework, Client Mode, full 25×50 production, any frontend. Pilots = collect + resolve entities + cost/QA telemetry only.

## Pilot cells (Stage 1)

3 industries × 5 markets = 15 cells: **Locksmith (IND010), Urgent Care (IND019), Chinese Restaurant (IND022)** × **Vancouver WA (MKT008), Phoenix AZ (MKT011), Chicago IL (MKT021), Birmingham AL (MKT040), New York City NY (MKT049)**. The AIO and ChatGPT pilots reuse these same 15 cells with their own conditions/geometry.

## Artifacts: exist vs. to author

- **Exists:** Collection Manifest v1.0 (25×50, civic anchors, Maps/Organic 13-point). **Reconcile before trusting it executable:** market entries are tagged `CIVIC_ANCHOR_FROZEN_PRE_WATER` / `candidate-v0.8` despite the top-level `FROZEN_EXECUTABLE` label; the coordinate layer looks partially materialized (~300 point rows, not ~650 for a full 50×13); `provider_endpoint_status: PENDING_EXACT_ENDPOINT_LOCK` (the pilot protocol's locked DataForSEO settings are authoritative over this tag).
- **To author (owner sign-off required before collector code):** **Physical Schema Contract v0.1** and **Operational QA / Wave Acceptance Contract v0.1**. Then per stage: manifest extensions for AIO (9-point geometry + eligibility + 10 conditions) and ChatGPT (10 prompts × 3 replicates, no coordinates), plus the **6 conversational AIO conditions** and the **10 ChatGPT prompt conditions** per industry. All prompts/conditions are prospectively locked in the versioned manifest — never LLM-generated at collection time.

## Coordinate eligibility (locked)

Every Maps/Organic coordinate: civic-center anchor (`CIVIC_CENTER_ANCHOR_V1`) → geodesic point generation → **US-country-boundary gate** → **2025 Census TIGER/Line AREAWATER** structural-water classifier → one of the missingness states above. Excluded points are never relocated, rotated, randomized, substituted, or imputed. Coverage denominators use eligible points, not an assumed count.

## Conventions

- `snake_case.py` files/functions; `PascalCase` classes; `UPPER_SNAKE_CASE` constants; Pydantic request/response models named by purpose.
- Schema changes via migrations. Every observation is append-only + traceable from scheduled intent → provider task → raw response → parser version → normalized records.
- Jobs idempotent with deterministic idempotency keys (`job_type + entity_id + observation/snapshot period + provider/version`); bounded retries; a technical retry must never duplicate a paid provider call, and a valid short/empty result is a scientific observation, never retried for a "better" one.
- Every paid call attributed in the cost ledger (module + research reason). Store versioned cost assumptions, not hard-coded prices.
- Tests mock all external providers (DataForSEO, vendors, OpenAI, Gemini) — never hit them in tests.
- Do not put any model/assistant identifier in commits, code, or committed docs.

## Coming next commits (domain model)

- `CONTEXT.md` (glossary): *business* (observed entity, place_id-keyed) ≠ *client*; *market* = city/metro; canonical *coordinate/point*; *Full Panel* / *Sentinel*; the missingness states; AIO *source/entity/destination visibility*; ChatGPT *five outcome families* + *replicate/frequency*.
- `docs/adr/`: **0001** separate system from AR Tools · **0002** immutable raw → content-addressed storage · **0003** canonical business registry keyed on place_id · **0004** one shared foundation, surfaces added sequentially · **0005** per-surface capture-feasibility gate before committing schema.

## Infra state

New GitHub repo (this one). **Supabase project and Railway project are not yet provisioned.** Provisioning them is an owner action; collector work begins after the two shared contracts are signed off and infra exists.
