# 0011 — `AIO_QUERY_V2`: conversational AIO conditions (treatment-set version bump)

Status: **ACCEPTED — owner wording signed off 2026-09-19; migration `029` authored +
offline-validated.** Applies to production on the next `main` deploy (the Railway
entrypoint re-runs the `02[0-9]_*` migrations idempotently, exactly as `025`–`028`
were promoted). Verified against the production schema first: the prod baseline is
600 treatments / 700 surface_treatment / 250 `AIO_QUERY_V1` / 0 `AIO_QUERY_V2` /
aio max sequence 250 — so the additive insert lands cleanly (→ 850 / 950).
`AIO_QUERY_V1` is retained as history (it reproduces the graduated `AIO-20260918`
wave). The full AIO panel runs `AIO_QUERY_V2`.

## Context

The AIO surface (ADR-0008: the AI Overview in the organic SERP, `DFS_AIO_V2`) was
seeded with the `AIO_QUERY_V1` treatment set (migration `019`) — 10 conditions per
industry. Four of them (C05–C08) were **short keyword variants** carried over from the
original candidate manifest:

| Code | `AIO_QUERY_V1` (kept) | Role |
|---|---|---|
| C05 | `recommended [SERVICE] in [CITY]` | `recommended_city` |
| C06 | `top rated [SERVICE] in [CITY]` | `top_rated_city` |
| C07 | `[SERVICE] reviews [CITY]` | `reviews_city` |
| C08 | `local [SERVICE] in [CITY]` | `local_city` |

AI Overviews are triggered and shaped by **conversational, natural-language** intent far
more than by terse keyword strings; the platform's research question is how Google's AIO
allocates local visibility across *how people actually ask*. Short keyword variants under-
sample that intent space and blur into C01–C04/C09 (all "[best] [SERVICE] [near me | in
CITY]"). The owner asked for genuinely conversational conditions in their place.

## Decision

Introduce a **new versioned treatment set `AIO_QUERY_V2`** on the same 25×50 universe,
same `GEOGRID13E_V1` geometry, same `DFS_AIO_V2` provider, same 10-condition count. Only
the **treatment wording** changes, so this is a treatment-set version bump — **not** a
change to research population, geometry, estimand, cadence, result depth, or missingness
semantics. `AIO_QUERY_V1` is retained unchanged as history.

- **C01, C02, C03, C04, C09, C10 — kept VERBATIM from `AIO_QUERY_V1`** (byte-identical
  templates, families, city-slot flags): core near-me, best near-me, service-variant
  near-me, explicit-city, best explicit-city, high-need explicit-city.
- **C05–C08 — replaced with conversational intents** (per-industry, `[CITY]`-slotted):
  - **C05 problem-led** — a described, non-urgent problem ("My kitchen faucet has been
    dripping… Who should I call in [CITY]?").
  - **C06 duress / immediate-need** — per-industry urgency. True emergencies for
    plumbing/electrical/locksmith/urgent-care/vet/water-damage; for discretionary
    services and food (no genuine emergency) an **adapted "immediate / last-minute"**
    framing (e.g. Chinese Restaurant: "I want Chinese food delivered as soon as possible
    tonight…"). **[Owner-confirmed 2026-09-19.]**
  - **C07 price / value** — one normalized template across all 25 industries:
    `Who offers reasonably priced [SERVICE] in [CITY]?`. **[Owner-confirmed 2026-09-19.]**
  - **C08 criteria / decision-support** — one normalized template:
    `What should I look for when choosing a [ENTITY] in [CITY], and which local [ENTITY]
    meet those criteria?`. **[Owner-confirmed 2026-09-19.]**

### Two judgment calls, owner-confirmed 2026-09-19

1. **C07/C08 normalized to one template per family across all industries** (vs bespoke
   per-industry phrasing) — chosen for cross-industry research consistency, since C07 and
   C08 are each a single condition family.
2. **C06 "immediate / last-minute" framing kept for the no-true-emergency industries**
   (house cleaning, landscaping, med spa, handyman, and Chinese Restaurant) — preserves
   C06's urgency intent without inventing implausible emergencies.

The frozen wording review surface is
`docs/design/aio-query-v2-conversational-conditions-v0_1.md` (all 25 industries × the new
C05–C08).

## Consequences

- The full AIO panel scope is unchanged: 25 industries × 10 conditions × 595 eligible
  `GEOGRID13E_V1` points = **148,750 executable** (162,500 planned − structural
  exclusions). Cost/economics unchanged (still `DFS_AIO_V2`, ~1,280 µUSD/task measured).
- The V2 conversational answers are richer text — the downstream **AIO content-analysis
  enrichment** stage (ADR-0010) analyzes this corpus; V2 is the wording that stage sees.
- `AIO_QUERY_V1` remains queryable (the `AIO-20260918` graduated wave is reproducible).
  The single-coordinate `spike` CLI and the ADR-0005 `aio_probe` keep their historical
  `AIO_QUERY_V1` binding; only the panel/graduated collection path (`aio_run`) advances
  to V2.
- No silent methodology drift: the change is a new *versioned* treatment set behind an
  explicit owner amendment, per the CLAUDE.md hard methodology boundary.

## Implementation

Deterministic, generated end to end (no hand-transcription):

1. **Frozen library** `manifest/aio_query_v2_conditions.json` — the source of truth,
   built by `scripts/gen_aio_query_v2_json.py` from the two authoritative sources (V1's
   kept conditions parsed from migration `019`; the conversational C05–C08 parsed from the
   signed-off design doc).
2. **Migration** `supabase/migrations/029_aio_query_v2.sql` — generated by
   `scripts/gen_migration_029_aio_query_v2.py` from the JSON: 250 `AIO_QUERY_V2`
   treatments + 250 `aio` → V2 `surface_treatment` links (sequences 251..500, above V1's
   1..250 block, satisfying `unique(methodology_version_id, surface_id, sequence)`). Both
   inserts are `ON CONFLICT DO NOTHING`, so the file re-runs cleanly on every Railway
   deploy (it matches the `02[0-9]_*` re-apply glob).
3. **Collector switch** `aio_run.AIO_TREATMENT_SET = "AIO_QUERY_V2"` — the single source of
   truth the decoupled `AioPanelRunner` reads.
4. **Validation** `scripts/validate_aio_query_v2.py` (ephemeral pgvector, 16/16): V2 seeded
   + wired, V1 retained, kept templates byte-identical to V1, `[CITY]` renders per market
   through the real context loader, full-panel scope still 148,750, migration idempotent.
   `validate_migrations` (001–029: 850 treatments / 950 surface_treatment), `validate_aio_run`,
   and the full `pytest` (129) all pass with V2 active. (The generators require `psycopg`
   + a local PostgreSQL 16 with `pgvector` for the ephemeral-pg validators.)

## Related

- **ADR-0008** — AIO surface of record = the AI Overview in the organic SERP.
- **ADR-0009** — the shared `GEOGRID13E_V1` geometry the AIO panel rides.
- **ADR-0010** — AIO content-analysis enrichment (the first LLM stage) analyzes the V2
  answer corpus after collection.
