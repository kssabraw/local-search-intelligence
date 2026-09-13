# HANDOFF

Current-state handoff for the Local Search Intelligence Platform. Pairs with `CLAUDE.md` (durable project context + rules) and `docs/AUTHORITATIVE-ARTIFACTS.md` (recovered source-of-truth artifact registry).

_Last updated: 2026-09-13 — methodology/design complete; Manifest v1.0 frozen executable; authoritative v0.1 contracts + Manifest + PRDs on `main` (PR #1). Physical schema split into ordered migrations `001`–`021` + Manifest v1.0/QA seeds, validated on local pgvector (1,100 → 1,000/91/9), merged (PR #3). Stage-1 vertical-slice Maps collector built + validated (PR #4). Migrations applied to a persistent Supabase dev branch (`lsi-dev`); the single-coordinate spike ran end-to-end live (raw → parse → normalize → place_id resolution → cost ledger). Pilot finding: Maps zoom `17z` returned no results; locked to `14z` by owner-approved amendment (ADR-0006, migration `022`)._

## Stage-1 pilot findings

- **Maps coordinate zoom locked `17z → 14z`** (owner-approved, ADR-0006, migration `022_amend_maps_zoom_14z.sql`). Manifest v1.0 tagged provider settings `PENDING_EXACT_ENDPOINT_LOCK`; the pilot locked them. Evidence (MKT008 center, "locksmith near me", depth 10): 17z→0, 15z→6, **14z→10**, 12z→10; center-vs-5mi-north at 14z returned different local businesses, confirming per-coordinate proximity signal. Universe unchanged; only the Maps provider profile is versioned (`DFS_MAPS_V1` 17z retained as history; `DFS_MAPS_V2` 14z is live).
- **`40102 "No Search Results"` is now classified as a valid empty observation** (`returned`, 0 results), not `provider_failure` (missing ≠ zero). See `collector/parse_maps.py`.
- **Spike mechanics validated end-to-end** on `lsi-dev`: at 14z the center coordinate returned a full Top-10 with 10/10 businesses resolved to canonical entities by place_id; cost ledger recorded (~$0.0006/call). Total pilot-probe spend ≈ $0.0024.
- **Organic capture gate PASSED (no amendment needed).** A `--probe-only` capture probe (ADR-0005) at the same coordinate confirmed the shipped Organic `location_coordinate` form `{lat},{lon},200` returns a full SERP: DataForSEO `20000 Ok`, 14 result blocks (`local_pack`, `organic`, `people_also_ask`, `related_searches`), coordinate applied (decoded `uule` = MKT008 center). The `17z` problem was Maps-specific; Organic needs no coordinate change. Remaining Organic work is engineering only — build the `organic.*` parser/normalizer — not methodology.
- **Capture-feasibility probe tool:** `collector/spike.py --probe-only` (surface-agnostic; wave `PROBE-<surface>-*`) records provider status + result-item count + `check_url` into `ops.observation.parser_metadata` without surface-specific normalization. Reusable for the AIO and ChatGPT ADR-0005 gates.

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

- **Supabase** project `local-search-intelligence` (ref `wbqcvqxmhqyspgqsdpsm`, org `rzgbmlgbileospunrxaf`, `us-west-1`, **PG 17.6**) is provisioned but **empty** — migrations `001`–`021` are NOT yet applied to it. A throwaway preview branch confirmed pgvector 0.8.2 / storage bucket / schema privacy on PG17, then was deleted. Resolve refs by name at use time (`list_projects`); never hardcode.
- **Railway** project `local-search-intelligence` (`production` env) is provisioned but has **no service and no variables/secrets** yet.
- **Secrets are NOT set yet.** DataForSEO login/password, Supabase service-role key, Gemini key, ChatGPT-vendor key belong only in Railway/Supabase secret management — never in this public repo or in chat. Setting them is an owner action and is a hard prerequisite for the first paid call.

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

- Steps 1–5 **done**: repo reconciled to authoritative artifacts; schema split into ordered migrations; research schemas private + content-addressed raw Storage bucket authored; Manifest v1.0 + QA rules seeded; DB keys/counts reconciled to Manifest v1.0 (1,100 → 1,000/91/9) — all validated on a local pgvector Postgres and merged to `main` (PR #3).
- Steps 6–10 **remaining**.

## Immediate next action

The vertical-slice spike (step 7) is **blocked on infra/secrets**, in this order:

1. **Apply migrations to a persistent Supabase environment.** `001`–`021` are on `main` but not applied to any persistent DB. Apply them (production project `wbqcvqxmhqyspgqsdpsm`, or a persistent dev branch) and re-confirm the 1,100 → 1,000/91/9 reconciliation there. This is a decision for the owner (production vs a persistent branch; the latter is ~$10/mo while it exists).
2. **Set secrets (owner action).** Add DataForSEO login/password (and the Supabase service-role key for DB/Storage writes) to Railway/Supabase secret management — never in this repo or in chat. Nothing is set yet.
3. **Build the Stage-1 vertical-slice collector** (step 6, no paid call): DataForSEO Maps `task_post`/`task_get` adapter, immutable content-addressed raw retention, parser → normalizer → place_id-first entity resolution → cost ledger, with deterministic idempotency keys and provider mocked in tests.
4. **Run the single-coordinate spike** (step 7): one Maps `task_post` for one eligible pilot coordinate → immutable raw → parse → normalize → resolve entity → cost ledger. This is the **first paid DataForSEO call** and stays gated on explicit owner confirmation **and** verified secrets.

Do not re-derive or re-sign the research architecture.
