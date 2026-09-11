# 0002 — Immutable raw observations in content-addressed object storage

Every provider response is preserved verbatim and immutably in object storage (Supabase Storage for V1) at deterministic, content-addressed, **fail-on-exists** paths; normalized/derived tables point back to it and are rebuildable, while raw is never rebuilt or overwritten. Historical SERP/AIO/recommendation observations are time-sensitive and cannot be reconstructed later, so losing or mutating them destroys irreplaceable longitudinal history — and future parser/taxonomy improvements must be re-runnable against the original bytes.

## Considered options

- **Store only parsed fields in Postgres (the AR Tools suite's current pattern):** rejected — it discards fields not anticipated at V1 and cannot support reparsing.
- **S3/R2 from day one:** deferred — pilot volume is trivial; per the parent's "measure before optimizing," revisit only if production storage cost demands it.

## Consequences

- The existing suite's `upsert:true` storage convention is explicitly inverted here (fail-on-exists).
- A distinct `provider_not_observable` missingness state exists for fields the provider never returns — never blank columns implying absence.
