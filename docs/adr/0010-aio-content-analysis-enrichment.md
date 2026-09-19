# 0010 — AIO content-analysis enrichment stage (sentiment / topics / claims)

Status: **PROPOSED — design authored, pending owner sign-off + a vendor key.** No
code, no migration, no paid call yet. This ADR is the scope expansion that admits
the platform's **first LLM/enrichment stage**; the detailed design of record is
`docs/design/aio-content-analysis-v0_1.md`.

## Context

AIO capture today is **structural / outcome-only** (ADR-0008): per observation we
record prevalence, SERP placement, element rectangles, citations (`inline_link` vs
`reference_card`), sidebar sources (domains), and embedded GBP businesses
(KG-MID/SearchViewer). The AI Overview's **answer prose itself is stored verbatim**
(`aio.observation.response_text_raw` / `response_markdown_raw`,
`aio.presentation_unit.text_raw` / `heading_raw`, `aio.citation.cited_span_raw`) but
is **not analyzed** — nothing reads what the answer *says*.

The owner wants to analyze that content: **per-business sentiment, overall answer
tone, repeated topics/themes, and structured claims** the AIO makes. This is
valuable research signal (what an AI Overview asserts about local providers, and how
that shifts over time), and it runs **entirely over already-stored text** — no
re-scrape, no DataForSEO re-pay.

But it crosses two lines the project has deliberately held:
- **Enrichment + a finding layer are "explicitly OUT of current scope"** (CLAUDE.md).
- It is the **first LLM stage**, and the parent PRD's hard rule is
  *"Python/SQL/provider-parsing/vector-math before LLM; an LLM never re-extracts
  structured provider fields, never manufactures measurements/effect-sizes/findings,
  and is gated behind deterministic + cache + embedding stages."*

So it needs an explicit, owner-approved scope expansion with firm boundaries — this
ADR — before any build.

## Decision

Introduce a **gated, versioned AIO content-analysis enrichment stage** that runs over
the **immutable stored AIO answer text** and produces **structured, source-span-
traceable** outputs (sentiment / topics / claims) into a new rebuildable enrichment
schema, surfaced through read-only analysis views alongside migrations 027/028.

Four constructs (all owner-selected):
1. **Per-business sentiment** — the stance the AIO expresses toward each *named or
   cited* business, tied to the resolved `business_location` entity + the exact
   supporting span. A measurement of *what the AIO said about the business*, never a
   ground-truth judgment of the business.
2. **Overall answer tone** — coarse sentiment/stance of the whole answer per
   observation (cheaper, always-available signal).
3. **Repeated topics / themes** — recurring themes across answers (e.g. "24/7
   emergency", "licensed & bonded", "pricing"), derived from **embeddings +
   clustering** (deterministic grouping), optionally LLM-*labeled* per cluster.
4. **Structured claims** — factual/marketing assertions the AIO makes (e.g.
   "same-day service", "highest rated"), each with its source span and any attached
   citation/business.

## Boundaries (the nevers — enforced by construction)

- **Deterministic → embedding → LLM, in that order.** A deterministic SQL/Python
  inventory and an embedding/clustering layer run first; the LLM is the last stage
  and only for what the first two cannot do (sentiment labeling, claim extraction,
  cluster naming).
- **The LLM only extracts/labels from the stored text**, always with a source span +
  model version + prompt version. It **never** invents a business, **never**
  re-extracts provider-structured fields (citations/sources/businesses come from
  `parse_aio`, not the LLM), and **never** emits a research finding, effect size, or
  cross-observation conclusion — those remain human/analyst work over the structured
  outputs.
- **No composite score**, within the stage or across surfaces. Each construct is a
  separate, raw output.
- **Missing ≠ zero.** An answer with no claims is a valid *zero-claim* observation;
  an untriggered/absent AIO simply has no text to analyze (not a null hole).
- **Measurement framing:** outputs describe *the AIO's characterization* ("the AIO
  speaks positively about business X"), never asserted truth about the business.
- **Immutable raw is the source.** Enrichment tables are fully rebuildable from the
  stored answer text; raw is never mutated. Re-running with a better model/prompt
  produces a **new versioned** enrichment pass, never an overwrite.
- **New paid dimension, gated + cached + ledgered.** LLM/embedding calls run only
  behind a new `RUN_*` gate (default closed), are **content-addressed cached** by
  (text hash, model version, prompt/taxonomy version) so re-runs never re-pay, and
  every call is attributed in the cost ledger with a versioned price. Tests mock all
  vendors (never hit them).
- **Versioned methodology.** The sentiment scheme, claim taxonomy, topic method,
  prompt text, and model id are all versioned; a change to any is a new analysis
  version, never silent drift.

## Consequences

- Requires a **vendor key** on Railway (Gemini is already in the locked stack for
  embeddings; an LLM key — Gemini recommended — is not set). Owner action.
- Best run **over the full-panel corpus** (today only ~5 triggered standalone AIOs
  exist); it is downstream of collection and does not block the panel — the panel
  produces its input.
- Adds a new enrichment schema + migration + a gated driver + read-only rollup views,
  all offline-validated with mocked vendors before any run.
- This ADR opens the door only for the **AIO surface's own answer content**; a general
  enrichment/signal warehouse and a finding registry remain out of scope.

## Alternatives considered

- **Pure-deterministic sentiment (lexicon/keyword).** Too weak for local-provider
  prose and prone to "manufacturing" a number that looks like sentiment; kept only as
  the deterministic *inventory* layer that gates the LLM, not as the sentiment itself.
- **Analyze at scrape time inside the collector.** Rejected: coupling a paid,
  model-versioned analysis to collection would force a re-scrape (re-pay) to re-run
  with a better model. A separate stage over stored raw is re-runnable for free
  (aside from the LLM cost, which is cached).
