# AIO Dual-Surface — schema reconciliation & normalizer design v0.1

Status: **DESIGN for sign-off** (pairs with ADR-0008). Offline; no migration applied,
no normalizer committed, no paid collection until the owner signs off + says "go".

Grounds every column in what the ADR-0005 probes proved the provider returns
(`AIOPROBE-AIOPROBE_V0-20260916` AI Mode; `AIOPROBE-ORG-AIOPROBE_V0-20260916`
organic). Build columns for CAPTURABLE fields; mark the rest `provider_not_observable`.

## What the existing schema already has (migration `010_aio.sql`)

The `aio.*` tables already model the source/entity/destination trio and are mostly
sufficient:

- `aio.observation` (`aio_triggered`, `response_text_raw`, `response_markdown_raw`,
  `provider_model`, `response_metadata`)
- `aio.presentation_unit` (`unit_type`, `presentation_zone`, `heading_raw`,
  `text_raw`, `provider_fields`)
- `aio.source_occurrence` (`observed_object_id`, `source_url_raw`, `source_title_raw`,
  `publisher_raw`, `retrieval_position`, `provider_fields`) — the **sidebar source cards**
- `aio.citation` (`source_occurrence_id`, `presentation_unit_id`, `marker_raw`,
  `cited_span_raw`, `provider_fields`) — **citation events**
- `aio.business_appearance` (`local_business_card`, `embedded_gbp`, `selected`, …)
- `aio.destination` (`destination_url_raw`, `destination_type`,
  `direct_business_link`, `third_party_business_link`)
- `aio.evidence_link` (citation ↔ business_appearance relationship)

## Field mapping (screenshot sidebar card → provider field → column)

The AI-Overview sources sidebar card decomposes to captured fields (all present in the
AI Mode wave's `key_universe`):

| Card element | Provider field | Column |
|---|---|---|
| Publisher name | `source` | `aio.source_occurrence.publisher_raw` |
| Favicon / thumbnail | `image_url` / `images` | **add** `source_image_url` |
| Title | `title` | `source_title_raw` |
| Snippet | `text` | **add** `source_snippet_raw` |
| Date ("Feb 13, 2026") | `datetime` | **add** `source_datetime_raw` |
| Order in "Show all" list | `rank_absolute` / `rank_group` / `position` | `retrieval_position` (+ **add** `rank_group`) |
| Link / site | `url` / `domain` | `source_url_raw` (+ **add** `source_domain_raw`) |
| Placement on page | `rectangle` | **add** `rectangle_{x,y,width,height}` |

Inline citations (answer-text chips) are `links[]` — a **different event** than the
sidebar reference card (AIO PRD §18).

## Migration `025_aio_dual_surface.sql` (planned DDL — apply on sign-off)

Additive only (no drop/rewrite; existing columns unchanged):

- **`aio.observation`** — add:
  - `aio_surface text` (`ai_mode` | `organic_serp`) — the capture surface (dual-surface discriminator)
  - `aio_presentation_form text` (`standalone` | `async_stub` | `absent`) — organic only; `null` for AI Mode
  - `async_ai_overview_loaded boolean` — was `load_async_ai_overview` used + a body returned
  - (`aio_triggered` already exists — the prevalence signal; **`false` is a valid negative**)
  - **SERP placement of the AIO block (organic surface only — "where on the page")**:
    - `serp_rank_absolute integer` — the AIO block's position among ALL SERP items (1 = top of page; larger = further down / middle)
    - `serp_rank_group integer`, `serp_position text` (`left` | `right`)
    - `serp_rectangle_x/y/width/height integer` — the AIO block's own page geometry (the `y` offset = how far down; above-the-fold derived later, never hard-labeled here — §32)
    - `serp_preceding_block_count integer` — how many result blocks appear before the AIO block (`0` = top)
    - `serp_preceding_block_types jsonb` — the ordered item-types before it (e.g. `["local_pack","organic","organic"]`), the semantic top-vs-middle context
    (all `null` for AI Mode, which is a tab with no SERP position)
- **`aio.presentation_unit`** — add `rectangle_x/y/width/height integer` (rectangles proven present, `calculate_rectangles`).
- **`aio.source_occurrence`** — add `source_domain_raw text`, `source_snippet_raw text`,
  `source_image_url text`, `source_datetime_raw text`, `rank_group integer`,
  `rectangle_x/y/width/height integer`.
- **`aio.citation`** — add `citation_kind text` (`inline_link` | `reference_card`) and
  `is_reference boolean` (the §18 distinction), plus `rectangle_x/y/width/height integer`.
- **`aio.destination`** — `destination_type` already free text; document the enum used
  (`google_searchviewer` | `google_maps` | `google_business_profile` | `website` |
  `other_google` | `other_web` | `none` | `unknown`) via a CHECK or a lookup seed.
- **`core.external_identifier`** — allow `identifier_type='google_kg_mid'` (the
  SearchViewer `svid` → `/g/…` MID), so an AIO business appearance resolves to a
  canonical entity joinable to the Maps `place_id` graph later.
- **`provider_not_observable`** (no column built): the structured local-business-card
  *module* — record the state, never an empty card table for the probed intent.

## Normalizer design (`collector/parse_aio.py` + `Repo.write_aio*`)

Deterministic, no LLM (parent PRD rule). Reuses the shipped, tested helpers
(`collector/inspect_aio.py` scoping, `collector/aio_destination.py` classify +
`svid`→MID) and mirrors the Maps/Organic normalizer pattern on the shared foundation.

**AI Mode (`parse_aio`)** — from the `ai_mode`/`ai_overview` response:
1. `aio.observation` (`aio_surface='ai_mode'`, `aio_triggered=true`, answer text/markdown).
2. Each `ai_overview_element` → `aio.presentation_unit` (+ rectangle).
3. Each `references[]` card → `aio.source_occurrence` (publisher/domain/url/title/
   snippet/image/datetime/rank/rectangle); resolve **URL-first → domain** to
   `core.web_url`/`core.web_domain` (like Organic).
4. Inline `links[]` and reference cards → `aio.citation` rows with
   `citation_kind`/`is_reference` (the inline-vs-sidebar distinction).
5. Business destinations (SearchViewer/Maps) → `aio.business_appearance` +
   `aio.destination` (`destination_type` via `classify_destination`), entity resolved
   by KG-MID (`decode_searchviewer_svid` → `google_kg_mid`).
6. `local_business_card` module → not written (provider_not_observable).

**Organic (`parse_aio_organic`)** — from the organic SERP with `load_async_ai_overview`:
1. Always write `aio.observation` (`aio_surface='organic_serp'`) — even when no AIO:
   `aio_triggered=false`, `aio_presentation_form='absent'` (the prevalence denominator).
2. Standalone `ai_overview` element only (PAA-AIO excluded): if a loaded body →
   `aio_presentation_form='standalone'`, `async_ai_overview_loaded=true`, and run the
   same source/citation/rectangle/destination normalization as AI Mode over the
   **scoped** `ai_overview` subtree (`inspect`/parse `scope='ai_overview'`,
   PAA excluded). **Record the AIO block's SERP placement** ("where on the page"): its
   `rank_absolute`/`rank_group`/`position` + `rectangle` from the item, and derive
   `serp_preceding_block_count` / `serp_preceding_block_types` by walking the SERP
   `items[]` that precede the AIO block (top = 0 preceding; middle = preceded by
   organic/local_pack blocks).
3. Async stub with no loaded body → `aio_presentation_form='async_stub'`,
   `aio_triggered=true`, body fields `provider_not_observable`.

**Entity resolution** ties both surfaces to one graph: source cards → web entities
(URL-first); business destinations → business entity by KG-MID; so AIO
source/entity/destination visibility is comparable across AI Mode and organic and
joinable to Maps.

## Validation plan (offline, before any paid run)

- Extend `scripts/validate_aio_probe.py` / a new `scripts/validate_aio_normalize.py`:
  apply migrations `001`–`025` on ephemeral pgvector; run `parse_aio` over the AI-Mode
  fixtures and `parse_aio_organic` over the organic fixtures; assert the sidebar cards,
  inline-vs-reference citations, rectangles, KG-MID destinations, and the organic
  presence/absence rows land correctly; `aio_triggered=false` writes a valid negative;
  entity graph clean. `pytest` mocks all providers.

## Cost & cadence (for the eventual paid run — separate "go")

Per observation: AI Mode 2,400 µUSD + organic 600 µUSD + async add-on (~600 µUSD, only
when a standalone AIO loads). Universe/geometry/conditions/cadence unchanged by this
design; an AIO Full-Panel run is separate future scope with its own go/no-go.
