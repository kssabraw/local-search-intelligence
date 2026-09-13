# 0006 — Maps coordinate zoom locked to 14z (Stage-1 pilot amendment)

Collection Manifest v1.0 shipped the DataForSEO Maps `location_coordinate` as
`{lat},{lon},17z`, with `provider_endpoint_status: PENDING_EXACT_ENDPOINT_LOCK` —
i.e. the provider settings were explicitly **not** locked; the Stage-1 pilot is
where they get locked empirically. The first live vertical-slice spike exposed
that `17z` is unusable: DataForSEO returned status `40102 "No Search Results"`
for a dense query at a market center.

DataForSEO's Google Maps `location_coordinate` is `lat,lon,zoom`; the lat/lon is
the proximity anchor and the **zoom sets the map viewport** Google searches. A
single-coordinate zoom sweep (MKT008 Vancouver WA center, "locksmith near me",
result depth 10) showed:

| zoom | ~viewport radius | results |
|---|---|---|
| 17z | ~0.2 mi | **0** (too tight → 40102) |
| 15z | ~0.7–1 mi | 6 (under-fills Top-10) |
| **14z** | ~1.3–2 mi | **10** |
| 12z | ~5–8 mi | 10 (viewport wider than the whole grid) |

A **center vs 5-mile-north** comparison at `14z` returned substantially different
local businesses (only national chains/kiosks recurred; the 5-mile point surfaced
"Battle Ground Lock and Key", in the town north of Vancouver), confirming that at
`14z` the **coordinate drives the local pack** — the per-coordinate proximity
signal the Maps/Organic PRD's science depends on (proximity → rank, ranking
radius, excess-performance, same-business-across-coordinates). `12z` would return
a near-identical metro-wide list at every point (spatially degenerate); `17z`
returns nothing.

## Decision

Lock the Maps coordinate zoom to **`14z`** (owner-approved 2026-09-13). It is the
value that both fills the full Top-10 at dense points and demonstrably preserves
per-coordinate differentiation.

## Scope & mechanics

- The **research universe is unchanged**: industries, markets, 13-point geometry,
  coordinates, treatments, cadence, result depth (10), and missingness semantics
  all stay as in Manifest v1.0. Only the DataForSEO **Maps provider profile** is
  versioned.
- Implemented in migration `022_amend_maps_zoom_14z.sql`: a new provider profile
  `DFS_MAPS_V2` (`{lat},{lon},14z`) is added and the Maps `surface_config` is
  repointed to it. The original `DFS_MAPS_V1` (`17z`) row is **retained** as the
  historical record; migration `019` still seeds the manifest exactly as frozen.
- Organic uses a different `location_coordinate` form (`{lat},{lon},200`) and was
  not implicated; it is left unchanged pending its own validation.

## Consequences

- No silent drift: the change is a versioned, auditable provider-profile revision
  with the empirical evidence recorded here and in `HANDOFF.md`.
- If a future probe shows `14z` under/over-captures in other markets or
  industries, revisit with the same evidence-first method before Full Panel.
