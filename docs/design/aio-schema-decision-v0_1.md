# AIO Schema Decision v0.1 — from the executed capture probe (ADR-0005)

Status: **probe EXECUTED + verified on production; this records the resulting
column-by-column decision for owner sign-off.** No `aio.*` normalizer or schema
migration is committed yet — that is the next step and needs the sign-off below.

Companion: `aio-capture-probe-v0_1.md` (the probe design). This doc is the ADR-0005
"build columns only for what the provider proves it returns" ruling, grounded in
the real payloads the probe captured.

## What ran

Wave **`AIOPROBE-AIOPROBE_V0-20260916`** (2026-09-16), DataForSEO **AI Mode**
(`DFS_AIO_V1`, `/v3/serp/google/ai_mode`), frozen 3×5 pilot cells × center point ×
2 conditions (`AIO_C01` near-me + `AIO_C04` explicit-city):

- **30/30 probed, 30/30 triggered** — trigger rate **1.0**. (AI Mode always returns
  an answer; unlike the conditional AI-Overview block in organic SERPs.)
- **Cost $0.072** = 30 × **2,400 µUSD/task** (the measured AI-Mode price; seeded as
  `DFS_AIO_AIMODE_TASK_V1` in migration `024`).
- Guardrails held: 30 immutable observations, 30 attributed cost events, **0 `aio.*`
  normalization rows**, structural water never submitted, gate re-closed after.

Observed item types across the 30 responses (from the stored capability inventory):

| item type | responses | total occurrences |
|---|---|---|
| `ai_overview` | 30 | 30 |
| `ai_overview_element` | 30 | 207 |
| `ai_overview_reference` | 29 | 547 |
| `images_element` | 29 | 120 |
| `link_element` | 14 | 37 |

**No `local_pack` / `map` / `knowledge_graph` types appeared at all.** Notably the
AI-Mode endpoint returns AI-Overview-shaped content (`ai_overview*`), so `DFS_AIO_V1`
does capture the citation/element model the AIO PRD needs.

## Field-by-field decision

Rule (ADR-0005): **CAPTURABLE** → build the column; **NOT_OBSERVABLE** → mark
`provider_not_observable`, no empty column.

| AIO-PRD field | present / 30 | decision | column plan |
|---|---|---|---|
| answer text (§15/17) | 30 | CAPTURABLE | `aio.observation.response_text_raw` / `response_markdown_raw` |
| element-level structure (§17) | 30 | CAPTURABLE | `aio.presentation_unit` (from `ai_overview_element`) |
| **element rectangles** (§17/32) | 30 | CAPTURABLE | rectangle x/y/w/h — **needs new columns** (see below); `calculate_rectangles` is honored |
| source citations (§16/18) | 29 | CAPTURABLE | `aio.source_occurrence` + `aio.citation` (from `ai_overview_reference`) |
| reference-vs-inline-link (§18) | 13 | CAPTURABLE | `aio.citation.marker_raw` + a reference/link flag; refs (`ai_overview_reference`) are structurally separate from inline `link_element`s |
| business position/order (§32/69) | 30 | CAPTURABLE | `aio.business_appearance.appearance_sequence` / rank |
| destination = SearchViewer/Maps (§69) | 29 | CAPTURABLE | `aio.destination.destination_type` (see recipe) |
| embedded GBP (§69) | 29 | CAPTURABLE | `aio.business_appearance` via SearchViewer/Maps destination |
| **local-business-card module** (§69) | **0** | **NOT_OBSERVABLE** | mark `provider_not_observable`; **do not** build a card-module table for AI Mode |

Two schema deltas the existing `010_aio.sql` tables do not yet carry:

1. **Element rectangles.** `aio.presentation_unit` has no geometry columns. Add
   `rectangle_x/y/width/height` (or a `rectangle jsonb`) — the provider proves it
   returns them when `calculate_rectangles=true`.
2. **KG MID external identifier.** Add `google_kg_mid` as a `core.external_identifier`
   type so an AIO business appearance resolves to a canonical entity and can later be
   joined to the Maps `place_id` graph (MID↔place_id mapping is future enrichment).

## How a GBP is detected + resolved in AI Mode

AI Mode has **no local-card module**; a business/GBP is an `ai_overview_reference`
whose destination is a Google **SearchViewer** deep link:

```
https://www.google.com/searchviewer/10?svid=CAwSHBIaCgNwdnESE0Nnd3ZaeTh4Y1RZeVp6RmtPWEUYCg
```

The `svid` is base64url(protobuf) wrapping a base64url of a **Knowledge Graph MID**:

```
…Y1RZeVp6RmtPWEUYCg  →  /g/1q62g1d9q
…TVdjd2FESXlhRjlyGAo  →  /g/11g0h22h_k
```

The deterministic mechanics are shipped + unit-tested in **`collector/aio_destination.py`**
(no LLM, no network):

- `classify_destination(url)` → AIO PRD §69 `destination_type`
  (`google_searchviewer`, `google_maps`, `other_google`, `other_web`, `call`,
  `directions`, `none`, `unknown`). It never emits `website` from a URL alone —
  distinguishing the business's own site from any external site requires matching the
  resolved business domain, which is the normalizer/enrichment's job.
- `decode_searchviewer_svid(url_or_token)` → the KG MID (`/g/…`), or `None`.

So the AIO normalizer detects GBPs by **classifying reference destinations** and
resolves identity by the **KG MID from the svid** — recorded as a `google_kg_mid`
external identifier — rather than expecting a local-pack module.

## The AI-Mode-vs-AI-Overview finding — BOTH surfaces probed

Both surfaces have now been probed on production (2026-09-16):

- **AI Mode** (`AIOPROBE-AIOPROBE_V0-20260916`, 30 tasks, trigger 1.0): citation-rich
  answer with element rectangles, references, and SearchViewer/Maps GBP destinations —
  but **no** structured local-business-card *module*.
- **AI Overview in the organic SERP** (`AIOPROBE-ORG-AIOPROBE_V0-20260916`, 15 tasks,
  $0.018): a standalone AI Overview **rarely appears** for near-me local-commercial
  intent — only 1/15 had a top-level `ai_overview`, and it came back as an **async
  stub** (`asynchronous_ai_overview: true`, body not loaded); 10/15 carried AI-Overview
  content only *inside* People Also Ask (`people_also_ask_ai_overview_expanded_element`).
  Google shows the **Local Pack** for these queries, not a classic AI Overview.

**Correction to the first pass:** the initial organic roll-up appeared to show
`local_business_cards` CAPTURABLE, but that was the schema-agnostic inspector walking
the *whole* SERP and counting the ever-present `local_pack` as a "local card." The
inspector now runs `scope="ai_overview"` for the organic mode (detection restricted to
the `ai_overview`/`*_ai_overview_*` element subtree), which removes the conflation: the
Local Pack is the Maps/Local surface already measured in Stage 1, **not** an
AI-Overview-embedded card. Scoped, no distinct AI-Overview local-card module was
observed on either surface for this query intent.

### Decision (recommended): AI Mode is the AIO surface of record

For local-intent queries, **AI Mode** reliably returns the AIO citation/entity model;
the organic AI Overview mostly does not trigger (and when it does, it needs async
loading). Recommendation: adopt AI Mode, mark the local-business-card-**module** fields
`provider_not_observable`, and note a methodology option to revisit standalone AI
Overview under different intents (explicit-city / informational forms may trigger it
more than "near me"). Businesses are still captured on AI Mode via SearchViewer/KG-MID
destinations. This is an owner methodology call (which surface is of record), not a
silent switch.

### Follow-ups shipped from the organic probe (offline, no cost)

- **Scoped inspector** — `inspect_aio_capture(get_json, scope="ai_overview")` restricts
  capability detection to the AI-Overview element subtree so the SERP `local_pack` is
  no longer conflated with an AIO card (`collector/inspect_aio.py`; the organic probe
  mode uses it).
- **Async AI-Overview expansion** — `--load-async-aio` / `AIO_PROBE_LOAD_ASYNC=1` adds
  DataForSEO's request-level `load_async_ai_overview=true` so the async AI-Overview body
  (markdown + references) is fetched and included. It carries an **additional provider
  charge**, so it is opt-in and gated (`RUN_AIO_PROBE`); a live organic re-run with it
  would be the way to capture standalone AI-Overview text/citations if the surface is
  pursued. (Confirmed mechanism: a request flag, not a page-token follow-up — the
  captured stubs carried no page_token.)

## Deferred until sign-off

The `aio.*` schema reconciliation (add rectangle columns + `google_kg_mid`), the AIO
parser/normalizer/entity path (writing `aio.presentation_unit` / `source_occurrence`
/ `citation` / `business_appearance` / `destination` from `ai_overview*` items using
the helpers above), and the 9-point × 10-condition production matrix — each on owner
sign-off. AIO stays behind its ADR-0005 gate until then.
