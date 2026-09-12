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
- SQL migration: `SED_Physical_Supabase_Postgres_Schema_v0_1.sql`
- Google Drive ID: `1whsoY_XVYBjgmQrzlpl-6dcq10z5kASG`
- Governing design: schemas `manifest`, `ops`, `core`, `maps`, `organic`, `aio`, `chatgpt`, `enrichment`, `research`, `client`; immutable raw evidence; versioned entity resolution; temporal enrichment; append-only costs; reproducible derived research.

### Operational QA / Wave Acceptance v0.1

- Human-readable contract: `SED_Operational_QA_Wave_Acceptance_Contract_v0_1.md`
- Google Drive ID: `1XSSm3UpjEsil6wAUEYXZRxVlhMUxQSRZ`
- Machine-readable rules are mirrored in this repo at `docs/contracts/qa-rules-v0_1.json`.
- SQL seed is mirrored in this repo at `supabase/seeds/qa_rules_v0_1.sql`.
- COMPLETE/PARTIAL/FAILED/QUARANTINED semantics are authoritative. PARTIAL thresholds are >=99.5% overall terminal coverage, >=99.0% per surface, and >=95% per industry × market × surface stratum where >=20 executable jobs, with no critical integrity failure.

### Manifest v1.0

- Machine-readable Manifest v1.0 Google Drive ID: `1xl5sGm9fCdz-aLFEKX2v8ETpodgxfLsh`.
- Status: frozen executable.
- Final geography classification: 1,000 eligible coordinates, 91 structural-water exclusions, 9 outside-country exclusions, 0 manual-review cases, 0 configuration failures.
- Executable counts: Full Panel 258,000/month; Sentinel 9,800/week; bounded 3-industry × 5-market pilot 3,048 jobs across all four surfaces.

### Governing PRDs

- Unified parent PRD: `1Y5CmSWDpSKryfkmcbPh25UG_yfyyvwZV2hdkh1hh3Sc`
- Maps/Organic PRD: `1pP1dKD341vtzBEA5w4H0-YidX3N2CRVr41cyDV8kD_A`
- AIO PRD: `1oDYH3_oYOvjD3g8jtt13QchxM0C8lgT1B_mq68V-5JI`
- ChatGPT PRD: `1YfWjb9gHzMr8uNriEwdQePhygFp-mjuN0C0c1dyvn54`
- Authoritative research handoff: `1GrlD5M1WcAmmdaf8PCYCpj6P4V87Ezm1`

## Conflict rule

The authoritative research artifacts above predate the repo scaffold. If a repo draft says, for example, that Manifest v1.0 still needs water reconciliation, that AIO/ChatGPT literals are still to be authored, or that the physical schema is only a small Maps/Organic subset, treat that repo statement as stale and reconcile it to the authoritative artifact rather than reopening methodology.

The methodology phase is complete. Engineering may stop for an amendment only if implementation would change the population, treatment, estimand, cadence, geometry, result depth, replicate behavior, missingness, or enrichment eligibility. Ordinary implementation choices are engineering tickets, not methodology redesign.
