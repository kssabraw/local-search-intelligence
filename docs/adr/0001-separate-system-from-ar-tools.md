# 0001 — Separate system from the AR Tools operational suite

The Local Search Intelligence Platform is built as its own repo, Supabase project, and Railway project — deliberately **not** inside the existing AR Tools agency suite — even though it mirrors that suite's stack. AR Tools is an operational, per-client delivery system; this is a longitudinal research platform with different data (whole result sets, cross-business, cross-market), stricter discipline (immutability, versioning), and its own cost profile. Keeping it separate avoids entangling research-grade guarantees with operational code and keeps its large collection volume off the suite's database.

## Consequences

- Suite infrastructure (DataForSEO wrappers, geocoding, the job worker, cost meters, grid geometry) can be **ported** as patterns but not imported; some re-implementation is expected and accepted.
- The parent PRD's eventual **Client Mode ↔ AR Tools** link becomes a later *cross-system* integration (data sync / API), not shared tables. Out of current scope.
- This platform is still **one system across its four surfaces** (Maps/Organic/AIO/ChatGPT) — separateness is from AR Tools, not among surfaces.
