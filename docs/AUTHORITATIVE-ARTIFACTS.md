# Authoritative Local Search Intelligence artifacts

This repository was scaffolded after the research architecture had already been designed. Do **not** reconstruct the research methodology or silently replace the artifacts below with newly derived alternatives.

## Repository-native planning artifacts

- `CLAUDE.md` — implementation plan of record / durable project rules.
- `CONTEXT.md` — domain glossary and model context.
- `docs/adr/` — architecture decisions.

## Authoritative external research artifacts

The following artifacts were completed before this repository was scaffolded and are the governing source when a shorter repo draft conflicts with them.

### Physical Supabase/Postgres schema v0.1

- Human-readable contract: `SED_Physical_Supabase_Postgres_Schema_Contract_v0_1.md`
- Google Drive ID: `1QoAiU5Kqce666orez0TCzbBway460Zpg`
- Mirrored in this repo at `docs/contracts/physical-schema-contract-v0_1.md` (the full authoritative artifact — it supersedes the earlier short Maps/Organic-only draft that previously lived at that path).
- SQL migration: `SED_Physical_Supabase_Postgres_Schema_v0_1.sql`
- Google Drive ID: `1whsoY_XVYBjgmQrzlpl-6dcq10z5kASG`
- Mirrored in this repo at `supabase/schema/physical-schema-v0_1.sql` (the authoritative full-schema source; the Governing build sequence splits it into `supabase/migrations/`).
- Governing design: schemas `manifest`, `ops`, `core`, `maps`, `organic`, `aio`, `chatgpt`, `enrichment`, `research`, `client`; immutable raw evidence; versioned entity resolution; temporal enrichment; append-only costs; reproducible derived research.

### Operational QA / Wave Acceptance v0.1

- Human-readable contract: `SED_Operational_QA_Wave_Acceptance_Contract_v0_1.md`
- Google Drive ID: `1XSSm3UpjEsil6wAUEYXZRxVlhMUxQSRZ`
- Mirrored in this repo at `docs/contracts/qa-wave-acceptance-contract-v0_1.md` (the full authoritative artifact — it supersedes the earlier short draft that previously lived at that path).
- Machine-readable `qa_rules` seed (24 rules) is mirrored in this repo at `docs/contracts/qa-rules-v0_1.json`, with its SQL seed at `supabase/seeds/qa_rules_v0_1.sql`.
- Machine-readable wave-acceptance rules (58 rules across the PRE/COL/NOR/RES/ENR/CST/ANA stages) are mirrored in this repo at `docs/contracts/qa-wave-acceptance-rules-v0_1.json`.
- COMPLETE/PARTIAL/FAILED/QUARANTINED semantics are authoritative. PARTIAL thresholds are >=99.5% overall terminal coverage, >=99.0% per surface, and >=95% per industry × market × surface stratum where >=20 executable jobs, with no critical integrity failure.

### Collection-job generator contract v0.7

- Mirrored in this repo at `docs/contracts/job-generator-contract-v0_7.json` — the contract that expands the frozen Manifest into the executable job matrix.

### Manifest v1.0

- Machine-readable Manifest v1.0 Google Drive ID: `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`.
- Mirrored in this repo at `manifest/SED_Collection_Manifest_v1_0.json`, with its geography inputs alongside it: `manifest/SED_Coordinates_GeoEligible_v1_0.csv`, `manifest/SED_Geo_Eligibility_Classification_v1_0.csv`, `manifest/SED_Geo_Eligibility_Report_v1_0.json` (the eligibility summary + SHA-256 checksums), and `manifest/SED_Geo_Source_Manifest_v1_0.json` (the Census TIGER source manifest). The two geo CSVs are SHA-256-verifiable against the hashes recorded in the report.
- Status: frozen executable.
- Final geography classification: 1,000 eligible coordinates, 91 structural-water exclusions, 9 outside-country exclusions, 0 manual-review cases, 0 configuration failures.
- Executable counts: Full Panel 258,000/month; Sentinel 9,800/week; bounded 3-industry × 5-market pilot 3,048 jobs across all four surfaces.

### Governing PRDs

- Unified parent PRD: `1Y5CmSWDpSKryfkmcbPh25UG_yfyyvwZV2hdkh1hh3Sc` — mirrored at `docs/prd/SED-Local-Search-Intelligence-Platform-Unified-Research-Architecture-Cost-Optimization-PRD.md`.
- Maps/Organic PRD: `1pP1dKD341vtzBEA5w4H0-YidX3N2CRVr41cyDV8kD_A` — mirrored at `docs/prd/Local-Geo-Grid-Ranking-Research-Spatial-Intelligence-Platform-PRD.md`.
- AIO PRD: `1oDYH3_oYOvjD3g8jtt13QchxM0C8lgT1B_mq68V-5JI` — mirrored at `docs/prd/Local-AI-Overview-Research-Citation-Intelligence-Platform-PRD.md`.
- ChatGPT PRD: `1YfWjb9gHzMr8uNriEwdQePhygFp-mjuN0C0c1dyvn54` — mirrored at `docs/prd/SED-ChatGPT-Local-Search-Recommendation-Intelligence-PRD.md`.
- Authoritative research handoff: `1GrlD5M1WcAmmdaf8PCYCpj6P4V87Ezm1`

## Conflict rule

The authoritative research artifacts above predate the repo scaffold. If a repo draft says, for example, that Manifest v1.0 still needs water reconciliation, that AIO/ChatGPT literals are still to be authored, or that the physical schema is only a small Maps/Organic subset, treat that repo statement as stale and reconcile it to the authoritative artifact rather than reopening methodology.

The methodology phase is complete. Engineering may stop for an amendment only if implementation would change the population, treatment, estimand, cadence, geometry, result depth, replicate behavior, missingness, or enrichment eligibility. Ordinary implementation choices are engineering tickets, not methodology redesign.
