# HANDOFF

Current-state handoff for the Local Search Intelligence Platform. Pairs with `CLAUDE.md` (durable project context + rules) and `docs/AUTHORITATIVE-ARTIFACTS.md` (recovered source-of-truth artifact registry).

_Last updated: 2026-09-12 — methodology/design complete; Manifest v1.0 frozen executable; build may proceed._

## Where we are

The research methodology is complete. Do **not** reconstruct the plan of record, domain model, physical schema, QA contract, or Manifest from scratch. The repo scaffold was created after those artifacts existed, so some early repo drafts contain stale pre-freeze language.

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

- Supabase project `local-search-intelligence` is provisioned; schema/storage still need to be applied/configured.
- Railway project `local-search-intelligence` is provisioned; service/code/secrets still need wiring.
- Secrets belong in Railway/Supabase secret management and never in this public repository.

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

## Immediate next action

Proceed with engineering. Do not ask the owner to reconstruct or re-sign the already-established research architecture merely because the repo scaffold originally contained shorter drafts.
