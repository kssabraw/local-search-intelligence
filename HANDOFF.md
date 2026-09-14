# HANDOFF

Current-state handoff for the Local Search Intelligence Platform. Pairs with `CLAUDE.md` (durable project context + rules) and `docs/AUTHORITATIVE-ARTIFACTS.md` (recovered source-of-truth artifact registry).

_Last updated: 2026-09-14 — methodology/design complete; Manifest v1.0 frozen executable; authoritative v0.1 contracts + Manifest + PRDs on `main` (PR #1). Physical schema split into ordered migrations `001`–`022` + Manifest v1.0/QA seeds, validated on local pgvector (1,100 → 1,000/91/9), merged. Stage-1 vertical-slice **Maps + Organic** collector built + validated offline (PR #10). Pilot finding: Maps zoom `17z` returned no results; locked to `14z` by owner-approved amendment (ADR-0006, migration `022`). Migrations `001`–`022` applied to the persistent PRODUCTION Supabase project (`wbqcvqxmhqyspgqsdpsm`), reconciling 1,100 → 1,000/91/9. **The first paid single-coordinate spike is now DONE and verified on PRODUCTION for BOTH surfaces (step 7 complete): Maps 10/10 businesses resolved by place_id, Organic 14 result rows → 9 web destinations resolved URL-first (0 business_locations), $0.0006 each. Next action: the bounded 3×5 Maps+Organic pilot (step 8), gated on explicit owner go.**_

## Stage-1 pilot findings

- **Maps coordinate zoom locked `17z → 14z`** (owner-approved, ADR-0006, migration `022_amend_maps_zoom_14z.sql`). Manifest v1.0 tagged provider settings `PENDING_EXACT_ENDPOINT_LOCK`; the pilot locked them. Evidence (MKT008 center, "locksmith near me", depth 10): 17z→0, 15z→6, **14z→10**, 12z→10; center-vs-5mi-north at 14z returned different local businesses, confirming per-coordinate proximity signal. Universe unchanged; only the Maps provider profile is versioned (`DFS_MAPS_V1` 17z retained as history; `DFS_MAPS_V2` 14z is live).
- **`40102 "No Search Results"` is now classified as a valid empty observation** (`returned`, 0 results), not `provider_failure` (missing ≠ zero). See `collector/parse_maps.py`.
- **Spike mechanics validated end-to-end** on `lsi-dev`: at 14z the center coordinate returned a full Top-10 with 10/10 businesses resolved to canonical entities by place_id; cost ledger recorded (~$0.0006/call). Total pilot-probe spend ≈ $0.0024.
- **Organic capture gate PASSED (no amendment needed).** A `--probe-only` capture probe (ADR-0005) at the same coordinate confirmed the shipped Organic `location_coordinate` form `{lat},{lon},200` returns a full SERP: DataForSEO `20000 Ok`, 14 result blocks (`local_pack`, `organic`, `people_also_ask`, `related_searches`), coordinate applied (decoded `uule` = MKT008 center). The `17z` problem was Maps-specific; Organic needs no coordinate change. Remaining Organic work is engineering only — build the `organic.*` parser/normalizer — not methodology.
- **Capture-feasibility probe tool:** `collector/spike.py --probe-only` (surface-agnostic; wave `PROBE-<surface>-*`) records provider status + result-item count + `check_url` into `ops.observation.parser_metadata` without surface-specific normalization. Reusable for the AIO and ChatGPT ADR-0005 gates.
- **Organic parser/normalizer built + offline-validated (engineering, no methodology change).** `collector/parse_organic.py` + `resolve_organic_item` + `Repo.write_organic`/`resolve_and_assert_organic` mirror the Maps path on the shared foundation; the spike dispatches on `surface_code`. Every SERP block (organic, local_pack, PAA, related_searches) is preserved as an `organic.result` row with its `result_type`/`rank_absolute`; only organic web destinations become `core.observed_object` and resolve **URL-first then domain** to `core.web_url`/`core.web_domain` (never `business_location`, per contract §14). `scripts/validate_spike.py` now runs the full Maps **and** Organic parse→normalize→resolve→cost path (+ idempotency) against synthetic fixtures on an ephemeral pgvector Postgres — all pass, no paid call. The live 3×5 Maps+Organic pilot remains gated on owner confirmation for the first paid call.
- **One-command migration apply added.** `scripts/apply_migrations.py --dsn "$SUPABASE_DB_URL"` applies `001`–`NNN` in order (each file its own transaction, stop-on-error), then prints the reconciliation + universe counts; `--check-only` re-verifies without writing, `--dry-run` lists files, `--force` re-applies over an existing schema. Uses `psycopg` (no external `psql`/CLI). Also corrected a stale expected count in `scripts/validate_migrations.py` (migration `022` added `DFS_MAPS_V2`, so `manifest.provider_profile` is 5, not 4). The Railway one-off `scripts/railway_run.sh` also applies migrations on deploy via `psql` against `$SUPABASE_DB_URL`.
- **Migrations applied to PRODUCTION + verified (2026-09-14).** `001`–`022` are applied to the persistent production Supabase project `wbqcvqxmhqyspgqsdpsm` (not a dev branch — the `lsi-dev` branch was torn down). Reconciliation confirmed on production: 1,000 eligible_land / 91 structural_water_exclusion / 9 outside_country_exclusion (1,100 total), 25 industries, 50 markets, 600 treatments, 5 provider profiles, 80 QA rules, 1 frozen methodology. Verified both via the Railway deploy log and an independent Supabase query.
- **First paid single-coordinate spike on PRODUCTION — DONE + verified (2026-09-14), step 7 complete.** Ran via the Railway service (`RUN_PAID_SPIKE=1`, then reset to `0`) at the default pilot coordinate `MKT008_MAPORG_C` (Vancouver WA center, `eligible_land`), IND010 "locksmith near me", depth 10. Total paid spend **$0.0012** (2 × $0.0006).
  - **Maps** (`SPIKE-20260914T054319`, obs `04a4155a-26dc-4dfe-afd1-026364d01f34`): `observation_state=returned`, full **Top-10 at 14z**, 10 `maps.result` rows, 10 `core.observed_object`, **10/10 resolved to distinct `core.business_location` by place_id**, 3 immutable `ops.raw_blob` (request+post+get), `ops.cost_event` 600 µUSD `maps_spike_task`. Verified by independent Supabase query (rank-1 "Locksmith Plus, Inc.").
  - **Organic** (`SPIKE-20260914T054830`, obs `b408c34a-d910-4cee-9c34-719ca2f0ce76`): `returned`, **14 `organic.result` rows preserving every block** (9 organic + 3 local_pack + 1 people_also_ask + 1 related_searches), **9 organic web destinations → 9 `core.observed_object` → 9/9 resolved to `core.web_url` (8 distinct `core.web_domain`), 0 `core.business_location`** (contract §14 held: Organic never mints a business), 3 raw blobs, cost 600 µUSD `organic_spike_task`. Coordinate form `{lat},{lon},200` (Organic, unchanged); endpoint `/v3/serp/google/organic/task_post`.
  - **Two PRODUCTION infra/config fixes were required first** (both surfaced *before* any paid call — $0 wasted, immutable-raw-first ordering + transaction rollback protected the run): (1) `SUPABASE_URL` on Railway held a malformed value (unresolvable host) → reset to canonical `https://wbqcvqxmhqyspgqsdpsm.supabase.co`; (2) `SUPABASE_SERVICE_ROLE_KEY` was a wrong/stale key (Storage reported `AccessDenied — signature verification failed`, `role: anon`, from the torn-down `lsi-dev` branch) → **replaced by owner with the production project's `service_role` key**. Collector hardened so this class of failure is self-diagnosing (PR #11: `StorageConfig` strips whitespace/trailing-slash on URL/key/bucket; `raw_store` surfaces the Storage response body instead of a bare `raise_for_status`).

## Where we are

The research methodology is complete. Do **not** reconstruct the plan of record, domain model, physical schema, QA contract, or Manifest from scratch. The repo scaffold was created after those artifacts existed, so some early repo drafts contain stale pre-freeze language.

**Repository state:** the authoritative artifacts below are now on `main`, byte-verified against Drive on import (the two geo CSVs additionally SHA-256-checked against `manifest/SED_Geo_Eligibility_Report_v1_0.json`). The import also reconciled two stale short drafts — `docs/contracts/physical-schema-contract-v0_1.md` (Maps/Organic-only → full 10-schema model) and `docs/contracts/qa-wave-acceptance-contract-v0_1.md` — to their full authoritative versions, per the `docs/AUTHORITATIVE-ARTIFACTS.md` conflict rule. No methodology change. (The same content was briefly staged in the AR-Tools monorepo under a `sed/` prefix; that PR was closed unmerged — this repo is the single home.)

Repository-native planning context:
- `CLAUDE.md` — implementation plan of record / durable project rules.
- `CONTEXT.md` — domain glossary/model context.
- `docs/adr/` — load-bearing architecture decisions.
- `docs/AUTHORITATIVE-ARTIFACTS.md` — registry of the authoritative pre-repo research artifacts and conflict rules.

Authoritative artifacts now mirrored in repo (byte-verified against Drive on import; see `docs/AUTHORITATIVE-ARTIFACTS.md` for the full registry):
- `docs/contracts/physical-schema-contract-v0_1.md` — full physical schema contract v0.1 (replaced the earlier short Maps/Organic-only draft).
- `supabase/schema/physical-schema-v0_1.sql` — physical schema SQL migration v0.1 (the authoritative full-schema source; split into `supabase/migrations/` per the build sequence).
- `docs/contracts/qa-wave-acceptance-contract-v0_1.md` — full Operational QA / Wave Acceptance contract v0.1 (replaced the earlier short draft).
- `docs/contracts/qa-rules-v0_1.json` + `supabase/seeds/qa_rules_v0_1.sql` — machine-readable `qa_rules` seed (24 rules) + SQL seed.
- `docs/contracts/qa-wave-acceptance-rules-v0_1.json` — machine-readable wave-acceptance rules (58 rules, PRE/COL/NOR/RES/ENR/CST/ANA stages).
- `docs/contracts/job-generator-contract-v0_7.json` — collection-job generator contract v0.7.
- `manifest/SED_Collection_Manifest_v1_0.json` + the four geography inputs (`SED_Coordinates_GeoEligible_v1_0.csv`, `SED_Geo_Eligibility_Classification_v1_0.csv`, `SED_Geo_Eligibility_Report_v1_0.json`, `SED_Geo_Source_Manifest_v1_0.json`) — the frozen Manifest v1.0 + SHA-256-verified geography.
- `docs/prd/` — the four governing PRDs (unified parent + Maps/Organic + AIO + ChatGPT).

Authoritative Drive artifacts (source-of-truth IDs; the ones above are now mirrored in-repo):
- Physical schema contract v0.1 — `1QoAiU5Kqce666orez0TCzbBway460Zpg`.
- Physical schema SQL migration v0.1 — `1whsoY_XVYBjgmQrzlpl-6dcq10z5kASG`.
- Operational QA / Wave Acceptance Contract v0.1 — `1XSSm3UpjEsil6wAUEYXZRxVlhMUxQSRZ`.
- Manifest v1.0 JSON — `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`.
- Authoritative research handoff — `1GrlD5M1WcAmmdaf8PCYCpj6P4V87Ezm1` (not yet mirrored in-repo).

## Build status

**There is no remaining methodology/sign-off blocker before engineering.**

Manifest v1.0 geography is resolved before first live scientific collection:
- 1,100 total spatial coordinates evaluated;
- 1,000 eligible land;
- 91 structural-water exclusions;
- 9 outside-country exclusions;
- 0 manual review;
- 0 configuration failures.

Executable workload after geography exclusions:
- Full Panel: **258,000 jobs/month**;
- weekly Sentinel: **9,800 jobs**;
- bounded 3-industry × 5-market pilot: **3,048 jobs across Maps, Organic, AIO, and ChatGPT**.

The old 280,000 / 11,200 counts are pre-geography planning counts, not the final executable counts.

## Infra

- **Supabase** project `local-search-intelligence` (ref `wbqcvqxmhqyspgqsdpsm`, org `rzgbmlgbileospunrxaf`, `us-west-1`, **PG 17.6**) — migrations `001`–`022` are **applied and reconciled** here (1,100 → 1,000/91/9). This persistent production project is the live DB; the earlier `lsi-dev` branch was torn down. Resolve refs by name at use time (`list_projects`); never hardcode.
- **Railway** project `local-search-intelligence` (`production` env) has a **live service** that runs the one-off `scripts/railway_run.sh` (Dockerfile) — it migrates + reconciles + dry-runs on deploy, and makes the single paid call only when `RUN_PAID_SPIKE=1`. `SUPABASE_DB_URL` points at the production **session pooler** (`postgresql://postgres.wbqcvqxmhqyspgqsdpsm:<pw>@aws-0-us-west-1.pooler.supabase.com:5432/postgres`). NOTE: the pooler is required because Railway egress is IPv4-only while Supabase's direct `db.<ref>.supabase.co` host is IPv6-only; and the pooler username must be ref-qualified (`postgres.<ref>`), or auth fails as `user "postgres"`.
- **Secrets set (Stage-1):** `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `SUPABASE_DB_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_URL` are configured on the Railway service. The Gemini and ChatGPT-vendor keys are **not** set (not needed until enrichment / ChatGPT, both out of current scope). Secrets live only in Railway/Supabase secret management — never in this public repo or in chat.

## Governing build sequence

1. Reconcile the repo implementation context to `docs/AUTHORITATIVE-ARTIFACTS.md`; do not re-derive methodology.
2. Apply/split the authoritative physical Supabase/Postgres schema v0.1 migration in an isolated development environment.
3. Keep research schemas private; configure immutable/content-addressed raw Storage.
4. Seed the frozen Manifest v1.0 and QA contract/rules.
5. Reconcile database keys/counts against Manifest v1.0 before provider collection.
6. Implement provider adapters, immutable raw retention, parsing/normalization, entity resolution, cost ledger, retries/quarantine, and QA evaluation.
7. Run a single-coordinate vertical-slice spike end-to-end.
8. Execute the bounded 3×5 pilot from the frozen v1.0 executable matrix (3,048 jobs across all four surfaces).
9. Evaluate COMPLETE/PARTIAL/FAILED/QUARANTINED under the QA contract. Production promotion requires COMPLETE.
10. After pilot validation, proceed to Full Panel/Sentinel operation without silently changing methodology.

## Hard methodology boundary

Implementation may not silently change research population, treatment, estimand, cadence, geometry, result depth, replicate behavior, missingness semantics, or enrichment eligibility. A genuine change to one of those requires an explicit methodology amendment. Ordinary implementation choices are engineering decisions/tickets.

Do not resurrect superseded designs such as 10×20 production, two-query Maps, 73-point production grids, AIO 13-point production, weekly Full Panel, one-anchor/four-family ChatGPT, retry-until-positive, destructive overwrite, or universal cross-surface visibility scores.

## Governing PRDs

- Unified parent PRD: `1Y5CmSWDpSKryfkmcbPh25UG_yfyyvwZV2hdkh1hh3Sc`
- Maps/Organic PRD: `1pP1dKD341vtzBEA5w4H0-YidX3N2CRVr41cyDV8kD_A`
- AIO PRD: `1oDYH3_oYOvjD3g8jtt13QchxM0C8lgT1B_mq68V-5JI`
- ChatGPT PRD: `1YfWjb9gHzMr8uNriEwdQePhygFp-mjuN0C0c1dyvn54`

## Build-sequence progress

- Steps 1–5 **done**: repo reconciled to authoritative artifacts; schema split into ordered migrations; research schemas private + content-addressed raw Storage bucket authored; Manifest v1.0 + QA rules seeded; DB keys/counts reconciled to Manifest v1.0 (1,100 → 1,000/91/9). Migrations `001`–`022` now **applied to the production Supabase project** and re-reconciled there.
- Step 6 **done (Maps + Organic)**: DataForSEO adapter, immutable content-addressed raw, parser → normalizer → entity resolution → cost ledger, deterministic idempotency, providers mocked in tests. Maps place_id-first; Organic URL-first→domain to `core.web_url`/`core.web_domain`. Both validated offline against the real schema (`scripts/validate_spike.py`).
- Step 7 **done on production (2026-09-14)**: the single-coordinate spike ran end-to-end live against the persistent production Supabase project for **both** Maps and Organic, verified by independent Supabase query (see *Stage-1 pilot findings* → "First paid single-coordinate spike on PRODUCTION"). Total paid spend $0.0012.
- Steps 8–10 **remaining** (step 8 = the bounded 3×5 Maps+Organic pilot, the immediate next action).

## Immediate next action

Infra + secrets are ready; the schema is live on production; the single-coordinate spike is **done and verified on production for both surfaces** (step 7). Remaining:

1. **Execute the bounded 3×5 pilot** (step 8) from the frozen v1.0 executable matrix — 15 cells (3 industries × 5 markets) × 4 queries × 13 points × 2 surfaces = 1,560 pre-water Maps+Organic jobs. This is a real collection run (many paid DataForSEO calls), so it is **gated on explicit owner go** and needs its own run harness (the current `collector/spike.py` is single-coordinate; the pilot needs batch iteration over the executable matrix with idempotency, bounded retries, and QA telemetry — not the throwaway spike loop). Then evaluate COMPLETE/PARTIAL/FAILED/QUARANTINED under the QA contract (step 9).
2. After pilot validation, proceed to Full Panel / Sentinel (step 10) without silent methodology drift.

**Outstanding owner cleanup (non-blocking):** delete the stray Railway service `zucchini-ambition`; rotate the production DB password AND the `service_role` key (both have been shared in chat historically) and re-update `SUPABASE_DB_URL` / `SUPABASE_SERVICE_ROLE_KEY` afterward.

Do not re-derive or re-sign the research architecture.
