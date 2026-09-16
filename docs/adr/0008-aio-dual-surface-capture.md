# 0008 — AIO dual-surface capture: AI Mode content-of-record + organic AI-Overview presence/body

Status: **PROPOSED — methodology amendment, pending owner sign-off.** This is a
versioned methodology change (it changes what the AIO surface measures), not an
engineering ticket. It does not take effect until signed off and a new methodology
version is minted. No paid collection runs until then and until explicit "go".

## Context

The Stage-2 ADR-0005 capture probes (2026-09-16) established, on production:

- **AI Mode** (`DFS_AIO_V1`, `/v3/serp/google/ai_mode`) returns a citation-rich AI
  answer **every time** (trigger rate 1.0) with the full source/citation model: the
  **sources sidebar** (`references[]` — publisher `source`, `domain`, `url`, `title`,
  snippet `text`, `image_url`, `datetime`, order `rank_*`/`position`), **inline
  citations** (`links[]`), element **rectangles**, and business/GBP destinations
  (Google **SearchViewer** links whose `svid` packs a Knowledge-Graph MID). Wave
  `AIOPROBE-AIOPROBE_V0-20260916`: 8/9 capture fields CAPTURABLE; references present
  29/30 (~18/response); the local-business-card **module** is NOT_OBSERVABLE.
- **AI Overview in the organic SERP** (`DFS_ORGANIC_V1`) is **conditional**: a
  standalone AI Overview appeared in only ~1/15 near-me queries (as an async stub),
  the Local Pack dominates, and most AIO-style content was embedded in People Also
  Ask. Wave `AIOPROBE-ORG-AIOPROBE_V0-20260916`.

Two facts drive the decision: (1) "how often does an AI Overview appear?" is only
measurable where it can be **absent** — the organic SERP, not the always-on AI Mode
tab; (2) the sidebar-sources + inline-citation body the research needs is richest on
**AI Mode**. Neither surface alone answers both the *prevalence* and the *content*
questions.

## Decision

AIO becomes a **dual-surface** measure:

1. **AI Mode (`DFS_AIO_V1`) is the content-of-record.** It captures the AIO answer
   body, the **sidebar source cards** (`references[]`), **inline citations**
   (`links[]`) — distinguished per AIO PRD §18 ("a reference/citation and an inline
   clickable link must never be treated as the same event") — element rectangles
   (§17/§32), business appearances, and GBP/SearchViewer destinations resolved by
   Knowledge-Graph MID.
2. **Organic (`DFS_ORGANIC_V1`, `load_async_ai_overview=true`) captures standalone
   AI-Overview PRESENCE, its rendered body, AND its position on the page.** Per
   observation it records whether a **standalone** AI Overview appeared (the
   trigger/prevalence signal, the primary longitudinal outcome); when present, its
   rendered body (sidebar sources + inline citations); and — uniquely to this surface
   — **where on the SERP the AIO block landed** (top vs middle): its rank among all
   SERP blocks, which blocks precede it, and its page-rectangle geometry (AIO PRD §32
   placement / above-the-fold). AI Mode, being a dedicated tab, has no SERP position,
   so placement is an organic-surface-only outcome. **People Also Ask AIO expansions
   are explicitly out of scope** (owner decision): only the standalone `ai_overview`
   element counts as "present".
3. **Absence on the organic surface is a valid negative, not missingness.** A returned
   organic SERP with no standalone AI Overview is `observation_state='returned'` with
   `aio_triggered=false` — it is the denominator of the prevalence rate, never
   `provider_not_observable` and never a fabricated zero (missing ≠ zero).
4. **The local-business-card *module* stays `provider_not_observable`** on both
   surfaces for the probed intent (no distinct AIO card module was observed; the SERP
   `local_pack` is the Maps/Local surface, already measured in Stage 1 — not an AIO
   card).

## Consequences

- **Cost** (measured/derived): AI Mode task 2,400 µUSD + organic task 600 µUSD =
  **3,000 µUSD/observation**, plus the `load_async_ai_overview` add-on (~600 µUSD)
  **only when a standalone async AIO is loaded** — rare for near-me intent, so a small
  amortized addition. Priced versions live in `ops.provider_price_version`
  (`DFS_AIO_AIMODE_TASK_V1` seeded; an async-add-on price row to be seeded from a
  measured value).
- **Methodology version bump.** A new AIO methodology version records the dual-surface
  estimand (content-of-record = AI Mode; presence = organic standalone AIO; PAA
  excluded). Geometry/conditions/universe are unchanged by this ADR.
- **Schema.** The `aio.*` tables (migration `010`) are reconciled to the proven fields
  (rectangles, sidebar-source card fields, KG-MID identifier, a surface discriminator
  + `aio_triggered` + presentation form). Design in
  `docs/design/aio-dual-surface-schema-v0_1.md`.
- **Still gated.** No `aio.*` normalizer is committed and no paid AIO collection runs
  until this ADR is signed off and the owner says "go".

## Not decided here

The AIO production universe (9-point geometry × 10 conditions), cadence, and any
Full-Panel AIO run remain future scope with their own sign-off. This ADR fixes only
*which surfaces measure what* for AIO.
