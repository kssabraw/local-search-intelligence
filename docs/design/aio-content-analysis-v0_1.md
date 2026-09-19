# AIO content-analysis enrichment v0.1 — sentiment / topics / claims

Status: **DESIGN (pending owner sign-off + vendor key).** Design of record for
ADR-0010. No code, no migration, no paid call yet. Runs over the **immutable stored
AIO answer text** — no re-scrape, no DataForSEO re-pay.

## Inputs (already stored, no new capture)

Per triggered AIO observation, `parse_aio`/`write_aio` (migration 025) already
persist:
- `aio.observation.response_text_raw` / `response_markdown_raw` — the full answer.
- `aio.presentation_unit.text_raw` / `heading_raw` — per element/paragraph.
- `aio.citation.cited_span_raw` + `citation_kind` (`inline_link`/`reference_card`)
  + `is_reference`, and `aio.source_occurrence` (sidebar source domains).
- `aio.business_appearance` (+ `aio.destination`) — businesses the provider marked,
  resolved to `business_location` by KG-MID.

The enrichment stage **reads** these; it never re-derives them with an LLM.

## The three layers (deterministic → embedding → LLM)

### Layer 1 — deterministic inventory (SQL/Python, no vendor cost)
Over the stored text: token/n-gram frequency, sentence/claim-candidate segmentation,
which `business_location` / domains are named in the prose vs only in cards, and
co-occurrence of businesses with claim-candidate spans. This is a cheap corpus map
and the **gate** for what the LLM is asked to label (e.g. only spans flagged as
claim-candidates are sent for claim extraction). Deterministic and re-runnable.

### Layer 2 — embeddings + clustering (Gemini embeddings, pgvector)
Embed each answer and each presentation unit; store **content-addressed** vectors
(keyed by text hash + embedding-model version, per the parent PRD) so identical text
is embedded once. Cluster unit embeddings across the panel to surface **repeated
topics/themes** (HDBSCAN/k-means over pgvector). Clusters are deterministic groupings;
an optional Layer-3 call *labels* each cluster (a handful of calls, not per-row).

### Layer 3 — gated, cached LLM (last; sentiment + claims + cluster labels)
For each construct, a versioned prompt turns a stored span into **structured JSON**:
- **Per-business sentiment:** for each business named/cited in the answer →
  `{business_ref, polarity ∈ {positive,neutral,negative}, intensity, source_span}`.
- **Overall answer tone:** one row per observation → `{polarity, intensity, rationale_span}`.
- **Structured claims:** per claim-candidate span → `{claim_text, claim_type, subject
  (business/entity/none), source_span, attached_citation_id?}`.
- **Cluster labels:** a short human-readable label per topic cluster.

Every call is **cached content-addressed** by `(text_hash, model_id, prompt_version)`
→ a re-run over the same text with the same model/prompt re-pays nothing. Providers
are mocked in tests.

## Schema sketch (new `aio_enrichment` schema; migration `030` when approved — `029` is reserved for `AIO_QUERY_V2`)

Append-only, versioned, source-traceable, rebuildable from `aio.*`:
- `analysis_pass` — one row per (analysis_version, embedding_model, llm_model,
  prompt_version, taxonomy_version); everything below references it.
- `answer_embedding` — content-addressed vector per (text_hash, embedding_model);
  `aio_unit_embedding` links units → vectors.
- `topic_cluster` / `unit_topic` — cluster id + label + membership (per pass).
- `answer_tone` — one row per (observation, pass): polarity, intensity, span.
- `business_sentiment` — (observation, business_location, pass): polarity, intensity,
  source_span, provenance to the `aio.business_appearance` / `aio.citation` it came
  from.
- `answer_claim` — (observation, pass): claim_text, claim_type, subject ref,
  source_span, optional `aio.citation` link.

All keyed so a construct is a separate raw output (no composite score); an
observation with zero claims has zero `answer_claim` rows (a valid zero, not missing).

## Read-only rollups (extend the analysis layer, like 027/028)

`analysis.*` views over the enrichment tables, all outcome-only, missing≠zero:
- topic prevalence per (industry, market, query) and **over time** (reuses the 028
  cross-wave, cross-grid-safe delta pattern);
- per-business sentiment distribution + its relation to citation kind / GBP embedding;
- claim-type frequency and which businesses claims attach to.
No composite score; the LLM's structured outputs are aggregated by SQL, not by the LLM.

## Gating, cost, versioning

- **Gate:** a new `RUN_AIO_ANALYSIS` (default `0`/closed, independent of the collection
  gates), checked before any vendor call; a dry-run prints the plan (spans/embeddings
  to process, cache hits, estimated cost) with no calls.
- **Cost ledger:** every embedding/LLM call attributed with a **versioned vendor
  price** (seeded like the DataForSEO prices, never hard-coded). Cache hits cost 0.
- **Versioning:** `analysis_version` bundles embedding-model, llm-model, prompt-version,
  and the sentiment scheme + claim taxonomy + topic method. Any change = a new pass,
  never an overwrite (immutable raw text is re-analyzable forever).

## Validation plan (offline, no vendor call, no network)

- `scripts/validate_aio_enrichment.py` on ephemeral pgvector: seed a small AIO corpus
  through the real write path (`finalize_aio`), run the stage with a **fake embedding
  provider + fake LLM** returning fixture JSON, and assert: deterministic inventory
  counts; embeddings content-addressed (identical text embedded once); clusters +
  labels; per-business sentiment tied to the right `business_location` + span; tone
  per observation; claims with source spans; **idempotent re-run re-pays nothing**
  (cache hits); gate refuses when closed.
- `pytest` units (DB-free) for the prompt/JSON parsing + cache key; all vendors mocked.

## Dependencies & sequencing

- **Vendor key** (Gemini embeddings + LLM) on Railway — owner action; not needed to
  build/validate offline.
- Best run **over the full-panel corpus** — this stage is downstream of collection and
  does not block the AIO panel. Order: settle query changes → run the AIO panel →
  run this stage over the collected answers (re-runnable as models improve, cached).
