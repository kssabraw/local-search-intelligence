# 0008 — AIO surface of record: the AI Overview in the organic SERP (AI Mode deferred)

Status: **PROPOSED — methodology amendment, pending owner sign-off.** This is a
versioned methodology change (it fixes which surface/endpoint measures AIO), not an
engineering ticket. No migration is applied, no normalizer is committed, and no paid
collection runs until it is signed off and the owner says "go".

Supersedes the earlier dual-surface draft of this ADR (AI Mode is no longer the
content-of-record; see "AI Mode deferred" below).

## Context

The AIO PRD's research object is unambiguous — the **Google AI Overview** (the SERP
feature), not AI Mode (§1, §2):

- *"monitor how **Google AI Overviews** behave for local-intent searches"* (§1)
- *"For every search … record **whether an AIO appears**; the AIO content; every cited
  source; … **left/right placement where exposed; approximate above-the-fold
  visibility where measurable; organic rankings; local/Map Pack results** …"* (§55)
- Primary question: *"What characteristics predict visibility, mentions, direct links,
  and citations in **Google AI Overviews** for local-intent searches?"* (§79)

"AI Mode" appears only as a paired label ("AIO / AI Mode") in two operational lines,
never as a separately-modeled surface. The core PRD outcomes — **prevalence** ("whether
an AIO appears") and **placement** (left/right, above-the-fold, position vs organic
rankings / Local Pack) — are **SERP phenomena** that exist only in the organic results
page, not in the always-on AI Mode tab.

The ADR-0005 probes (2026-09-16) confirmed the mechanics: the organic SERP returns the
AI Overview (`AIOPROBE-ORG-...`), often as an async stub loadable with
`load_async_ai_overview`, alongside the organic results + Local Pack; AI Mode
(`AIOPROBE-AIOPROBE_V0-...`) returns a rich but always-on answer with **no** SERP
position — structurally unable to answer prevalence or placement.

## Decision

1. **The AIO surface of record is the AI Overview embedded in the organic Google
   SERP**, captured via DataForSEO's organic advanced endpoint with
   `load_async_ai_overview=true` + `calculate_rectangles=true`. One call yields the
   AIO **and** the organic rankings + Local Pack the PRD wants to correlate against
   (§55, H3), in the same response.
2. **Per observation, capture:**
   - **Prevalence** — whether a **standalone** AI Overview appeared (`aio_triggered`);
     absence is a valid negative (the denominator), never missingness.
   - **The AIO body** — sidebar source cards (`references[]`), inline citations
     (`links[]`) kept distinct from references (§18), element rectangles (§17/§32),
     businesses + GBP/SearchViewer destinations resolved by Knowledge-Graph MID.
   - **SERP placement** ("where on the page") — the AIO block's rank among SERP items,
     the blocks preceding it (top vs middle), and its page-rectangle geometry
     (above-the-fold derived later; raw geometry preserved, never hard-labeled — §32).
   - **Co-returned context** — the organic results + Local Pack from the same call,
     for organic-position-predicts-citation analysis (H3).
3. **People Also Ask AIO expansions are out of scope** (owner decision): only the
   standalone `ai_overview` element counts as "present".
4. **The local-business-card *module* stays `provider_not_observable`** for the probed
   intent (no distinct AIO card module observed; the SERP `local_pack` is the
   Maps/Local surface, already measured). Revisit only if a distinct card module is
   observed under other conditions.
5. **AI Mode is deferred, not adopted.** DataForSEO AI Mode is a *different* Google
   product — the conversational AI-search tab: always-on (no prevalence), no SERP
   position (no placement), a different generated answer with its own source set.
   Folding it into the AIO panel would conflate two surfaces (and using it to "fill
   in" an absent AI Overview would corrupt the prevalence/citation measures). Tracking
   who is cited/recommended in Google's conversational AI search is a legitimate but
   **separate** research question — a sibling to Stage-3 ChatGPT — and, if pursued,
   gets its own ADR-0005 capture gate + methodology. It is **not** part of Stage 2.
6. **Manifest reconciliation (provider-profile amendment).** The seeded `DFS_AIO_V1`
   profile points at the DataForSEO **`ai_mode`** endpoint — a mismatch with this
   decision. Introduce a new versioned profile **`DFS_AIO_V2`** = the organic
   `ai_overview` capture (organic `task_post`/`task_get` advanced, `{lat},{lon},…`,
   `load_async_ai_overview` + `calculate_rectangles`), make it the live AIO
   `surface_config`, and retain `DFS_AIO_V1` as history. No universe/geometry/condition
   change.

## Consequences

- **Cost** drops sharply vs the AI-Mode path: the AIO call is an organic-endpoint task
  (~600 µUSD) + the `load_async_ai_overview` add-on (~600 µUSD, only when a standalone
  AIO actually loads — rare for near-me intent). No separate 2,400 µUSD AI-Mode task.
  And the same call already returns the organic + Local Pack context (no extra call).
- **PRD-faithful:** prevalence + placement + citations-in-SERP-context + organic-rank
  correlation are all captured within one observation, exactly as §55 describes.
- **Simpler schema:** no surface discriminator / dual reconciliation. Design in
  `docs/design/aio-organic-overview-schema-v0_1.md`.
- **Versioned:** a new AIO methodology version + the `DFS_AIO_V2` provider-profile
  amendment. Geometry (9-point) and the 10 conditions are unchanged.
- **Still gated:** nothing is built or run until sign-off + "go".

## Not decided here

The AI Mode surface (its own future gate/PRD), and the AIO production universe /
cadence / Full-Panel run (own sign-off + go/no-go).
