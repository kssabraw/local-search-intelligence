# 0003 — Canonical business registry keyed on Google place_id

Businesses are resolved into a single cross-surface, cross-market canonical registry, preferring the Google **place_id** as the strong identifier (then corroborated by normalized name, phone, address, coordinates, and domain). Every surface, enrichment, and Client-Mode record references the same canonical `business_id`. This is the primary mechanism for joining Maps/Organic/AIO/ChatGPT observations of the same business and for eliminating duplicate paid enrichment.

## Consequences

- Probabilistic matches store `resolution_method`, `confidence`, and evidence; **ambiguous matches are never silently merged** — they stay unresolved or enter a review queue rather than contaminate the dataset.
- Organic-only businesses (no place_id) resolve via domain with lower confidence; unresolved and likely-nonexistent entities are preserved, not discarded.
- This differs from the AR Tools suite, where identity is per-client (`client_competitors`) rather than a shared cross-client registry.
