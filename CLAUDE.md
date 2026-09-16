# Local Search Intelligence Platform

Context for Claude Code working in this repo. **Read this first.**

> ⚠️ **PUBLIC REPOSITORY — NEVER COMMIT SECRETS.** DataForSEO credentials, the Supabase service-role key, OpenAI/vendor API keys, Railway tokens, and any other secret live only in Railway/Supabase secret management and a git-ignored local `.env`. Never in code, migrations, config, tests, fixtures, or committed docs. Log lines must never print keys or tokens.

## What this is

Amazing Rankings' (AR) **Local Search Intelligence Platform** — a longitudinal **research** platform that measures how Google and AI assistants allocate *local* business visibility across geographic space and time, across four observation surfaces: **Google Maps / Local Pack**, **Google Organic**, **Google AI Overviews (AIO / AI Mode)**, and **ChatGPT local recommendations**.

It is **not** a client-facing SaaS, a rank tracker, or a heatmap product. It produces versioned, defensible *research findings* about what predicts local visibility. A later **Client Mode** diagnoses a specific client against those findings.

**This is a separate system from the AR Tools operational agency suite** (a different repo/Supabase/Railway). AR Tools is a sibling; the eventual Client Mode ↔ AR Tools link is a later cross-system integration, out of current scope. ("SED Society" appears in older PRD text — it is a dead agency name; this is Amazing Rankings.)

## Status

**Stage 1 (Maps + Organic) is COMPLETE and production-promotable; Step 10 (Full Panel / Sentinel operation) is COMPLETE — the first monthly Full Panel ran on production and evaluated COMPLETE.** `HANDOFF.md` is the authoritative current-state doc; this is the summary.

- **Foundation + schema live.** Migrations `001`–`023` are applied and reconciled on the **production** Supabase project (1,100 coordinates → 1,000 eligible / 91 structural-water / 9 outside-country). One owner-approved reconciliation: `manifest.coordinate_eligibility` gains `outside_country_exclusion` (see `supabase/migrations/README.md`). Amendments: `022` Maps zoom `17z→14z` (ADR-0006), `023` versioned DataForSEO price, `024` measured AI-Mode (AIO) task price (applies idempotently on next deploy). The Railway service is live with all three paid gates (`RUN_PAID_SPIKE` / `RUN_PAID_PILOT` / `RUN_PAID_PANEL`) **closed** (`0`).
- **Collector built + validated** (`collector/`): the single-coordinate spike and the 3×5 pilot harness (water gate, deterministic idempotency + resume, concurrency, provider-error resilience, QA/Wave-Acceptance evaluator). Providers mocked in tests.
- **Stage-1 pilot ran on production and evaluated COMPLETE** under QA/Wave-Acceptance v0.1 (wave `PILOT-3x5-20260914`: 1,368/1,368 executable returned, all 30 strata pass, 0 identifier splits, ~$0.8142).
- **First panel-scale Sentinel wave ran on production and evaluated COMPLETE** under QA/Wave-Acceptance v0.1 (wave `SENTINEL-2026W38`, Standard **decoupled** method: 5,200 planned → 4,400/4,400 executable returned (100%) / 800 structurally excluded, all 100 strata pass, every gate 1.0, 0 failed / 0 quarantined / 0 identifier splits, **$2.6304**).
- **First monthly Full Panel ran on production and evaluated COMPLETE** under QA/Wave-Acceptance v0.1 (wave `FULLPANEL-202609`, 2026-09-16): 130,000 planned → **117,994 / 118,000 executable returned (99.995%)** / 12,000 structurally excluded; entity graph clean (**0 duplicate domains / URLs**); 0 real provider failures; 6 tasks accounted `collect_timeout` (paid at submit, uncollected — within the COMPLETE tolerance); **$70.29** realized. All three paid gates re-closed (`0`).

**Step 10 — Full Panel / Sentinel operation for Maps + Organic (COMPLETE; no methodology drift).** Governed by **ADR-0007** + `docs/design/full-panel-sentinel-scheduler-v0_1.md`. In-scope executable counts: **Full Panel 118,000** Maps+Organic jobs/month (~$70.80), **weekly Sentinel 4,400** (~$2.64); Sentinel is a fixed *selection* over the frozen universe (the monthly wave doubles as that week's Sentinel). Built + offline-validated: the manifest-driven wave generator + set-based dry-run (`collector/panel.py`), the Standard **decoupled** DataForSEO adapter + two-phase panel runner (`collector/dataforseo.py` batch methods, `collector/panel_run.py`), and the **cadence driver + `RUN_PAID_PANEL` gate + Railway wiring** (`collector/panel_driver.py`, `scripts/railway_run.sh`; PR #22). Two throughput/robustness improvements shipped while running the first Full Panel: **parallel collect phase** (cell-affinity worker pool + sharded, order-safe web-entity create locks; PR #24) and **direct `task_get`-by-stored-id collection** (roster-independent resume, since DataForSEO's `tasks_ready` ages tasks off within hours; PR #25) — both offline-validated (pytest + validators), no methodology change, zero re-pay on resume. **Executed:** the graduated first paid Sentinel wave (`SENTINEL-2026W38`) → **COMPLETE** (~$2.64) and the first monthly Full Panel (`FULLPANEL-202609`) → **COMPLETE** (~$70.29); gates re-closed after each.

**Stage 2 (AIO) — capture-feasibility probe EXECUTED (2026-09-16; ADR-0005 gate-1).** The AIO probe harness was built (PR #27: `collector/inspect_aio.py` schema-agnostic capability inspector + `collector/aio_probe.py` 3×5 sweep + `RUN_AIO_PROBE` gate, riding the seeded `aio`/`DFS_AIO_V1` AI-Mode manifest) and ran on production: wave `AIOPROBE-AIOPROBE_V0-20260916`, 30/30 AI-Mode tasks triggered (rate 1.0), **$0.072** (2,400 µUSD/task; seeded `DFS_AIO_AIMODE_TASK_V1`, migration `024`), gate re-closed. **8/9 AIO-PRD capture fields CAPTURABLE** (incl. element rectangles — `calculate_rectangles` honored, citations, SearchViewer/Maps GBP destinations); only the structured **local-business-card module is NOT_OBSERVABLE** on AI Mode (it is an AI-Overview-in-organic surface — open owner decision). GBP detection/resolution grounded + shipped in `collector/aio_destination.py` (SearchViewer `destination_type` classifier + `svid`→Knowledge-Graph-MID decoder). The `aio.*` schema reconciliation + normalizer are deferred pending owner sign-off (`docs/design/aio-schema-decision-v0_1.md`). ChatGPT (Stage 3) stays behind its own ADR-0005 capture probe.

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

## Domain model & ADRs (shipped)

- `CONTEXT.md` (glossary): *business* (observed entity, place_id-keyed) ≠ *client*; *market* = city/metro; canonical *coordinate/point*; *Full Panel* / *Sentinel*; the missingness states; AIO *source/entity/destination visibility*; ChatGPT *five outcome families* + *replicate/frequency*.
- `docs/adr/`: **0001** separate system from AR Tools · **0002** immutable raw → content-addressed storage · **0003** canonical business registry keyed on place_id · **0004** one shared foundation, surfaces added sequentially · **0005** per-surface capture-feasibility gate before committing schema · **0006** Maps coordinate zoom locked `14z` (Stage-1 pilot amendment) · **0007** Full Panel / Sentinel operation for Maps + Organic (Step 10).

## Infra state

- **GitHub:** this repo. Migrations + Manifest v1.0 seed + QA v0.1 seed + the collector are on `main`.
- **Supabase:** project `local-search-intelligence` (ref `wbqcvqxmhqyspgqsdpsm`, org `rzgbmlgbileospunrxaf`, region `us-west-1`, **Postgres 17.6**). Migrations `001`–`023` are **applied and reconciled** here (1,100→1,000/91/9). Resolve the ref by name at use time (`list_projects`); never hardcode it.
- **Railway:** project `local-search-intelligence` (`production` environment) has a **live service** running `scripts/railway_run.sh` (migrate + reconcile + dry-run on deploy). It makes paid calls **only** when a paid gate is opened (`RUN_PAID_SPIKE` / `RUN_PAID_PILOT` / `RUN_PAID_PANEL`); **all default `0` / closed** (each was opened for its run, then re-closed). `SUPABASE_DB_URL` points at the production **session pooler** (Railway egress is IPv4-only; the direct host is IPv6-only; the pooler username is ref-qualified `postgres.<ref>`). Resolve the ref by name at use time (`list-projects`).
- **Secrets — set (Stage-1).** `DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`, `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL` are configured on the Railway service (DB password + service-role key rotated 2026-09-14). The Gemini and ChatGPT-vendor keys are **not** set (not needed until enrichment / ChatGPT, both out of scope). Secrets live only in Railway/Supabase secret management (an **owner action**) — never in this public repo, code, migrations, tests, committed docs, or chat. Any paid DataForSEO call stays gated on explicit owner confirmation **and** the corresponding open gate.
