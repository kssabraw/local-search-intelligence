# AIO (organic AI Overview) — schema reconciliation & normalizer design v0.1

Status: **DESIGN for sign-off** (pairs with ADR-0008). Offline; no migration applied,
no normalizer committed, no paid collection until sign-off + "go".

Single surface: the **AI Overview embedded in the organic Google SERP**
(`DFS_AIO_V2` = organic advanced endpoint + `load_async_ai_overview` +
`calculate_rectangles`). AI Mode is deferred (ADR-0008). Every column is grounded in
what the ADR-0005 probes proved the provider returns.

## What the existing schema already has (migration `010_aio.sql`)

The `aio.*` tables already model source/entity/destination and are mostly sufficient:
`aio.observation`, `aio.presentation_unit`, `aio.source_occurrence` (the sidebar
cards), `aio.citation`, `aio.business_appearance`, `aio.destination`,
`aio.evidence_link`.

## Field mapping (sidebar source card → provider field → column)

The AI-Overview sources-sidebar card (the screenshot: publisher + favicon + title +
snippet + date + thumbnail + order) decomposes to captured fields:

| Card element | Provider field | Column |
|---|---|---|
| Publisher name | `source` | `aio.source_occurrence.publisher_raw` |
| Favicon / thumbnail | `image_url` / `images` | **add** `source_image_url` |
| Title | `title` | `source_title_raw` |
| Snippet | `text` | **add** `source_snippet_raw` |
| Date | `datetime` | **add** `source_datetime_raw` |
| Order in "Show all" list | `rank_absolute` / `rank_group` / `position` | `retrieval_position` (+ **add** `rank_group`) |
| Link / site | `url` / `domain` | `source_url_raw` (+ **add** `source_domain_raw`) |
| Placement on page | `rectangle` | **add** `rectangle_{x,y,width,height}` |

Inline citations (answer-text chips) are `links[]` — a **different event** than the
sidebar reference card (§18).

## Migration `025_aio_organic_overview.sql` (planned — apply on sign-off)

Additive only (no drop/rewrite):

- **`aio.observation`** — add:
  - `aio_triggered boolean` — already exists; the **prevalence** signal (`false` = valid negative).
  - `aio_presentation_form text` (`standalone` | `async_stub` | `absent`).
  - `async_ai_overview_loaded boolean` — was `load_async_ai_overview` used + a body returned.
  - **SERP placement ("where on the page")**: `serp_rank_absolute integer` (1 = top of
    page; larger = further down / middle), `serp_rank_group integer`,
    `serp_position text` (`left`|`right`), `serp_rectangle_x/y/width/height integer`,
    `serp_preceding_block_count integer` (`0` = top), `serp_preceding_block_types jsonb`
    (ordered item-types before the AIO block, e.g. `["local_pack","organic","organic"]`).
- **`aio.presentation_unit`** — add `rectangle_x/y/width/height integer`.
- **`aio.source_occurrence`** — add `source_domain_raw text`, `source_snippet_raw text`,
  `source_image_url text`, `source_datetime_raw text`, `rank_group integer`,
  `rectangle_x/y/width/height integer`.
- **`aio.citation`** — add `citation_kind text` (`inline_link` | `reference_card`),
  `is_reference boolean` (the §18 distinction), `rectangle_x/y/width/height integer`.
- **`aio.destination`** — document the `destination_type` enum
  (`google_searchviewer`|`google_maps`|`google_business_profile`|`website`|`other_google`|`other_web`|`none`|`unknown`).
- **`core.external_identifier`** — allow `identifier_type='google_kg_mid'` (SearchViewer
  `svid` → `/g/…`), joinable to the Maps `place_id` graph later.
- **provider profile** — seed **`DFS_AIO_V2`** (organic `ai_overview` capture:
  `/v3/serp/google/organic/task_post` + advanced get, `{lat},{lon},…`,
  `load_async_ai_overview=true`, `calculate_rectangles=true`) and point the `aio`
  `surface_config` at it; retain `DFS_AIO_V1` (ai_mode) as history (ADR-0008 §6).
- **provider_not_observable** (no column built): the local-business-card *module*.

## Normalizer design (`collector/parse_aio.py` + `Repo.write_aio*`)

Deterministic, no LLM. Reuses the shipped, tested helpers (`collector/inspect_aio.py`
`scope='ai_overview'`, `collector/aio_destination.py` classify + `svid`→MID) and mirrors
the Maps/Organic normalizer on the shared foundation. One organic SERP response is
parsed on **two tracks**:

1. **Organic context (reuse existing `parse_organic` / `write_organic`).** The same
   response carries the organic results + Local Pack; normalize them as usual so
   organic-position-predicts-AIO-citation (H3) is a within-observation join. No extra
   call, no double-pay.
2. **The AI Overview (`parse_aio`, scoped to the `ai_overview` subtree, PAA excluded):**
   - Always write `aio.observation`. No standalone AIO → `aio_triggered=false`,
     `aio_presentation_form='absent'` (the prevalence negative). Async stub, not loaded
     → `async_stub`. Loaded body → `standalone`, `async_ai_overview_loaded=true`.
   - Record the AIO block's **SERP placement**: its `rank_absolute`/`rank_group`/
     `position` + `rectangle`, and derive `serp_preceding_block_count` /
     `serp_preceding_block_types` by walking the SERP `items[]` preceding the AIO block.
   - Body (when present): each `ai_overview_element` → `aio.presentation_unit` (+
     rectangle); each `references[]` card → `aio.source_occurrence`
     (publisher/domain/url/title/snippet/image/datetime/rank/rectangle), resolved
     URL-first → domain to `core.web_url`/`core.web_domain`; inline `links[]` + reference
     cards → `aio.citation` (`citation_kind`/`is_reference`); business destinations →
     `aio.business_appearance` + `aio.destination` (`destination_type` via
     `classify_destination`), entity resolved by KG-MID (`decode_searchviewer_svid` →
     `google_kg_mid`).
   - Local-business-card module → not written (provider_not_observable).

Entity resolution ties AIO sources/businesses into the one canonical graph
(URL-first for sources; KG-MID for businesses), so AIO source/entity/destination
visibility is comparable with Maps + Organic.

## Validation plan (offline, before any paid run)

`scripts/validate_aio_normalize.py`: apply migrations `001`–`025` on ephemeral
pgvector; run the two-track parse over the organic fixtures (loaded AIO + local_pack;
async stub + local_pack; no-AIO) and assert: the sidebar cards, inline-vs-reference
citations, rectangles, KG-MID destinations, SERP placement (top vs middle), and the
`aio_triggered=false` valid-negative all land; the organic context co-normalizes; the
entity graph is clean. `pytest` mocks all providers; no paid call.

## Cost & cadence (for the eventual paid run — separate "go")

Per observation: one organic-endpoint task (~600 µUSD) + `load_async_ai_overview`
add-on (~600 µUSD, only when a standalone AIO loads). The same call returns the AIO,
the organic rankings, and the Local Pack. Universe (**`GEOGRID13E_V1` 13-point
geometry** × 10 conditions — ADR-0009/migration `026` unified AIO onto the shared grid,
was 9-point `AIO9_V1`; ~148,750 executable observations across the 595 eligible
GEOGRID13E_V1 coordinates), cadence, and any Full-Panel AIO run are unchanged by this
design and remain future scope with their own go/no-go.
