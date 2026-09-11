# HANDOFF

Current-state handoff for the Local Search Intelligence Platform. Pairs with `CLAUDE.md` (durable project context + rules) — this file is "where we are right now and what's next." Update it at the end of a working session.

_Last updated: 2026-09-11 — planning complete; repo scaffolded with docs; Supabase + Railway projects provisioned (empty); awaiting contract sign-off + first migrations._

## Where we are

The full plan was worked out in a grilling session and is captured in `CLAUDE.md`. This repo now holds the **plan of record + domain model + draft shared contracts**. **No application code, no infra yet.**

Committed so far:
- `CLAUDE.md` — project context, PRD hierarchy (with Google Doc IDs), architecture, hard rules, stack, build stages, scope boundaries.
- `CONTEXT.md` — domain glossary.
- `docs/adr/0001–0005` — the load-bearing decisions.
- `docs/contracts/physical-schema-contract-v0_1.md` — **DRAFT**, shared foundation + Maps/Organic DDL.
- `docs/contracts/qa-wave-acceptance-contract-v0_1.md` — **DRAFT**, wave QA + pilot go/no-go + 13-vs-9 telemetry.

## Blocked on the owner (do these to unblock the build)

1. **Sign off (or request changes to) the two v0.1 contracts** in `docs/contracts/`. No collector code is written before sign-off.

## Infra (provisioned 2026-09-11)

- **Supabase project `local-search-intelligence`** — org "Kyle Sabraw", region `us-west-1`, ACTIVE_HEALTHY, **$10/mo**. Empty: no schema applied, no Storage bucket, `pgvector` not yet enabled.
- **Railway project `local-search-intelligence`** — personal workspace, `production` environment. Empty: no service/code wired.
- Resolve exact project refs/ids at build time via `list_projects` / `list-projects` (match by name) — deliberately not hardcoded in this public repo.
- **Secrets** (DataForSEO, Supabase service-role key, vendor / OpenAI / Gemini keys) go in Railway/Supabase secret management — **never in git** (public repo).
- The Claude GitHub integration **cannot create repos** (403); this repo already exists and is attached to sessions via `add_repo`.

**Remaining infra wiring** (build-session tasks, after contract sign-off): apply schema-v0.1 migrations · enable `pgvector` · create the raw-payload Storage bucket (content-addressed, fail-on-exists) · wire a Railway service to this repo with secrets.

## Decisions already locked (see CLAUDE.md / ADRs for detail)

Separate system from AR Tools · mirror the AR Tools stack (FastAPI + Supabase + `async_jobs` worker + Railway; Supabase Storage for raw, content-addressed, fail-on-exists) · one shared foundation, surfaces built sequentially **Maps/Organic → AIO → ChatGPT** · production universe = **25×50** (confirmed after the pilot) · **public** repo · enrichment/AIO/ChatGPT/findings/Client-Mode/frontend all **out of current scope**.

## Stage-1 target (the near-term build, once unblocked)

The **15-cell Maps/Organic pilot**: IND010 Locksmith / IND019 Urgent Care / IND022 Chinese Restaurant × Vancouver WA / Phoenix AZ / Chicago IL / Birmingham AL / New York NY, × 4 queries × 13 points (nested-9 tagged) × 2 surfaces = **1,560 pre-water jobs** → COMPLETE-wave acceptance + go/no-go + **13-vs-9 telemetry (RETAIN_13 default)**.

## Next steps (in order, after unblock)

1. `qa_rules` machine-readable seed (each QA-contract §4 check → a versioned rule row). Doesn't need infra beyond the applied schema names.
2. First migrations implementing **schema v0.1**.
3. **Single-coordinate vertical-slice spike:** one DataForSEO Maps `task_post` → raw (fail-on-exists object storage) → parse → normalize → resolve business → cost-ledger row. Proves the shared-foundation contracts end-to-end.
4. Eligibility reconciliation against Manifest v1.0 (resolve the flags below), freeze the pilot's coordinate set.
5. Fan out to the full 1,560-job pilot; run QA; produce go/no-go + 13-vs-9 telemetry.

## Carry-forward flags & open items

- **Manifest v1.0 reconciliation (before treating it executable):** market entries tagged `CIVIC_ANCHOR_FROZEN_PRE_WATER` / `candidate-v0.8` despite the top-level `FROZEN_EXECUTABLE` label; coordinate layer looks partially materialized (~300 point rows, not ~650 for full 50×13); `provider_endpoint_status: PENDING` (the pilot protocol's locked DataForSEO settings win over this tag). Manifest is Google Drive file `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`.
- **Locked DataForSEO pilot settings** (from the Maps/Organic PRD, authoritative over the manifest's PENDING tag): Maps `/v3/serp/google/maps/task_post` + `task_get/advanced`, priority 1, English, desktop/Windows, `location_coordinate={lat},{lon},17z`, depth 10, `search_this_area=true`, `search_places=false`; Organic `/v3/serp/google/organic/task_post` + `task_get/advanced`, `location_coordinate={lat},{lon},200`, depth 10, `load_async_ai_overview=false`; ≤100 tasks/POST, no endpoint mixing.
- **Open engineering decisions** (schema contract §8): `public` vs a `research` schema; `collection_job` table vs `async_jobs`-style queue; object-storage path layout; entity-resolution confidence thresholds. Settle at provisioning; none changes the v0.1 tables.
- **Outstanding authoring for later stages** (owner-locked, never LLM-generated at collection time): the **6 conversational AIO conditions/industry** and the **10 ChatGPT prompt conditions/industry** — I draft candidates, owner locks.
- **Per-surface capture gate (ADR-0005):** AIO and ChatGPT each need a live provider/vendor probe before their schema is committed (AIO: rectangles/cards/embedded-GBP/SearchViewer; ChatGPT: real consumer product + observed fanout, not a wrapped API call).

## Reference docs (Google Docs)

Parent unified PRD `1Y5CmSWDpSKryfkmcbPh25UG_yfyyvwZV2hdkh1hh3Sc` · Maps/Organic `1pP1dKD341vtzBEA5w4H0-YidX3N2CRVr41cyDV8kD_A` · AIO `1oDYH3_oYOvjD3g8jtt13QchxM0C8lgT1B_mq68V-5JI` · ChatGPT `1YfWjb9gHzMr8uNriEwdQePhygFp-mjuN0C0c1dyvn54` · Collection Manifest v1.0 `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`.
