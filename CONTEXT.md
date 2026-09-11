# Local Search Intelligence Platform

The domain glossary for this platform. It defines terms only — no implementation detail. When a term here has competing words, this file picks one; the others are listed under `_Avoid_`.

## Universe & panel

**Industry**:
A local-service vertical under study (e.g. Plumbing, Locksmith), carrying its own locked query set. A dimension of the research universe.
_Avoid_: vertical, niche, category

**Market**:
A city/metro under study, anchored by one frozen civic-center coordinate.
_Avoid_: city (informal), region, locale; and specifically **not** LeadOff's city×category "market"

**Query condition**:
One locked, versioned query or prompt executed against a surface (e.g. `[service] near me`). The controlled experimental treatment.
_Avoid_: keyword, search term, prompt (except for ChatGPT), variant

**Query family**:
A set of query conditions sharing industry/market/intent that differ only in geographic wording, grouped for matched-family analysis.
_Avoid_: query group, cluster

**Panel**:
The versioned set of universe members (industries × markets × conditions × geometry) a surface collects.

**Full Panel**:
The complete monthly collection of a surface's entire eligible panel.

**Sentinel**:
The fixed weekly monitoring subset (5 industries × 10 markets). Not a statistically complete weekly copy of the Full Panel.
_Avoid_: weekly panel, sample

**Methodology version**:
An immutable label freezing industries, markets, conditions, geometry, provider settings, and result depth. Any material change mints a new one.
_Avoid_: config version, revision

## Geometry & eligibility

**Coordinate**:
A fixed, versioned lat/lng search location where a surface is observed. Reused across runs; never drifts.
_Avoid_: pin, cell, point (informal), location

**Grid point**:
A coordinate's registry entry (index, bearing, distance-from-center, membership flags). The addressable record behind a coordinate.

**Civic-center anchor**:
The frozen official civic-government coordinate that originates a market's geometry.
_Avoid_: centroid, market center (Census-place centroids are provenance only, not the anchor)

**Structural missingness**:
A coordinate deliberately not collected for a structural reason. Never encoded as rank zero, no-visibility, or a failed observation. States: `structural_water_exclusion` (over ocean/lake/river), `outside_country_exclusion` (outside the US boundary), `configuration_failure` (a center anchor that is itself excluded), `provider_not_observable` (a field the provider/vendor does not expose).
_Avoid_: null result, missing, error, zero

## Entities

**Business**:
Any local business observed on any surface — identified canonically, preferentially by Google place_id. A shared, cross-surface, cross-market entity.
_Avoid_: client, prospect, account, listing

**Client**:
A Client-Mode subject — an Amazing Rankings customer being diagnosed against research findings. A distinct concept from Business; belongs to the deferred Client Mode.
_Avoid_: using "business" for this

**Canonical entity graph**:
The shared registry of businesses, GBP locations, domains, URLs, and their time-aware relationships, referenced by every surface.

## Observation

**Provider task**:
One request issued to an external provider, with its parameters and identifiers, tracked for idempotency and cost.

**Raw observation**:
The complete, immutable provider response for a provider task, preserved verbatim in content-addressed storage. Never overwritten; the audit/reprocessing layer.
_Avoid_: response record, payload (when it implies mutability)

**Surface observation**:
A normalized, per-surface record parsed from a raw observation (e.g. `maps_observation`, `organic_observation`, `aio_observation`). Rebuildable from raw; raw is not rebuildable.
_Avoid_: parsed result

**Local result set**:
The complete ordered list of local businesses returned at one coordinate for one query — not just the tracked business.
_Avoid_: SERP, results (bare)

**Wave**:
One versioned collection cohort of a panel (a Full Panel wave or a Sentinel wave), with a frozen methodology configuration.
_Avoid_: batch, cycle

## Outcomes

These are deliberately distinct and must never be collapsed into a single score.

**Rank / Coverage / Reach / Excess performance / Persistence / Transition** (Maps):
Rank = position at one coordinate. Coverage = share of eligible coordinates meeting a threshold. Reach = how far strong visibility persists (ranking radius). Excess performance = performance beyond what proximity alone predicts. Persistence = durability over time. Transition = a gain/loss/expansion/contraction/swap event.

**Source / Entity / Destination visibility** (AIO):
Source = a site is used as evidence. Entity = a business is named/recommended. Destination = a business gets a direct clickable link. Independent; a business can have any combination.

**Five outcome families** (ChatGPT):
Entity visibility, recommendation visibility (inclusion + strength + polarity + order), mention-link visibility, destination visibility, evidence/source visibility.

**Replicate**:
One of the fixed independent fresh-context executions of a ChatGPT prompt condition. Replicates yield recommendation *frequency/stability*, never a deterministic rank.

## Research & strategy (deferred concepts)

**Research Mode / Client Mode**:
Research Mode runs standardized panels to produce findings. Client Mode diagnoses a specific Client against findings, cohorts, and intervention history.

**Research finding**:
A versioned, evidence-classified result about what predicts a visibility outcome. A hypothesis is not a finding; correlation is not causation.

**Signal / Enrichment**:
A time-versioned enriched fact about an entity (review count, DR, referring domains, category, etc.), stored in the shared signal warehouse. Enrichment is the act of collecting a signal. Out of pilot scope.

**Intervention**:
A deliberately implemented, research-informed change to a Client's signals, recorded with its outcome so the platform learns from observation → finding → intervention → measured outcome.
