# Unified efficient 13-point geo-grid (`GEOGRID13E_V1`) — design v0.1

Status: **DESIGN for sign-off** (pairs with ADR-0009). Offline; no migration
applied, no universe change committed, no paid calls. Eligibility gate is now
**COMPLETE** (authoritative TIGER water + country gate run — §5).

> Revises an earlier v0.1 draft that specified a 21-point grid (diagonals @ 2/4).
> Measured Full-Panel saturation (§4) showed the 1-mile ring is the least efficient
> sample, so the design is refined to an efficient 13-point grid: drop the 1-mile
> ring, add a single 4-mile diagonal ring. Same footprint as today, more businesses
> per point.

## 1. What changes

One shared 13-point geometry replaces the two current grids going forward:

```
Frozen today                          Proposed GEOGRID13E_V1 (shared)
  MAPORG13_V1 (Maps/Organic)            center                      (0 mi)
    center                              N/E/S/W          @ 3 mi      (cardinal, reused)
    N/E/S/W @ 1, 3, 5 mi   = 13         NE/SE/SW/NW      @ 4 mi      (diagonal, NEW)
  AIO9_V1 (AIO)                         N/E/S/W          @ 5 mi      (cardinal, reused)
    center                            ------------------------------------------------
    N/E/S/W @ 2.5, 5 mi    = 9          = 13 points, used by BOTH surfaces
```

vs `MAPORG13_V1`: **drop** the 1-mile cardinal ring, **add** a 4-mile diagonal
ring. Same 13-point footprint. AIO stops using the 2.5/5 `AIO9_V1` layout and rides
the shared grid, so every AIO observation is co-located with a Maps/Organic
observation at the identical lat/lon.

### 1.1 Full point set

| # | point_id | bearing° | dist (mi) | kind | source |
|---|---|---|---|---|---|
| 1 | C | – | 0.0 | cardinal | frozen (reused) |
| 2–5 | N3 E3 S3 W3 | 0/90/180/270 | 3.0 | cardinal | frozen (reused) |
| 6–9 | **NE4 SE4 SW4 NW4** | 45/135/225/315 | 4.0 | **diagonal** | **new** |
| 10–13 | N5 E5 S5 W5 | 0/90/180/270 | 5.0 | cardinal | frozen (reused) |

Distance samples: **0 / 3 / 4 / 5 mi** (three non-zero radii for distance-decay).
The 1-mile cardinals (N1/E1/S1/W1) are retired from the active grid but retained in
`MAPORG13_V1` history.

## 2. Why this shape (efficiency, measured)

Adjacent-spoke chord on a ring is `radius × √2`: 4.24 mi at the 3-mi ring, 7.07 mi
at the 5-mi ring — wide arcs where different neighborhoods surface different
businesses. The 4-mile diagonals sit in that productive band and halve the gap,
while the near-center 1-mile ring (1.41 mi chord) mostly re-samples the center's
own pack. §4 quantifies both effects from real data.

A 4-mile *diagonal* ring (rather than a 4-mile cardinal ring) is chosen so the new
points fall in the angular gaps the 3/5 cardinals leave open, maximizing new-
business discovery per point.

## 3. Coordinate generation (done, exact)

`scripts/gen_diagonal_coords.py` emits the 200 new points (50 markets × 4 diagonals
× 1 ring) with the **same method the frozen manifest used**:

- Anchor: each market's `CIVIC_CENTER_ANCHOR_V1` civic center (read from
  `manifest/SED_Coordinates_GeoEligible_v1_0.csv`).
- Projection: `WGS84_GEODESIC_DIRECT` (geographiclib `Geodesic.WGS84.Direct`),
  7-decimal output — byte-for-byte the manifest's method.
- International mile (1609.344 m).

Output artifact (provisional, committed):
`docs/design/data/geogrid13e_new_diagonal_coords_provisional.csv` — 200 rows,
`water_eligibility = PENDING_TIGER_GATE`, plus a `provisional_risk` column. The
center + 3/5 cardinals are reused from the manifest and not re-emitted.

## 4. Measured saturation evidence (first Full Panel, Maps, 10 markets)

Avg unique businesses per cell (market × industry × query) as rings accumulate,
pooled over 10 markets (100 cells each):

| Subset | Businesses/cell | Marginal / point |
|---|---|---|
| center | 9.7 | 9.7 |
| center + 1-mi ring | 18.1 | 2.1 |
| center + 3-mi ring | 32.4 | 5.7 |
| center + 5-mi ring | 36.6 | 6.7 |
| center + 3 + 5 (9 pt) | 49.3 | — |
| full 13-pt (1/3/5) | 53.6 | — |

Key facts driving the design:
- The **1-mile ring adds only +4.3 businesses** (1.1/point) once 3 & 5 are present.
- The **outer rings add ~4–7 new businesses per point** — new businesses live in
  the 3–5 mi band.
- The grid is **not saturated** (the 3-mile grid captures only ~59–82% of what the
  13-point finds), so outer angular sampling keeps discovering businesses.

Estimated capture for `GEOGRID13E_V1`: **~61 businesses/cell** (center + 3/5
cardinals = 49.3 measured, + ~12 from the 4-mile diagonals filling the productive
band) — **~14% more than the current 13-point (53.6) at the same footprint**. The
4-mile-diagonal contribution is modeled from the cardinal data (never collected),
so it is an estimate pending a real run.

## 5. Eligibility gate — COMPLETE (authoritative)

The classifier `SED_GEO_ELIGIBILITY_CENSUS_2025_V1` was run on the 200 diagonals via
`scripts/run_water_gate.py` plus a country-gate step:

- **Water gate:** point-in-polygon against the TIGER 2025 AREAWATER GeoPackage
  (national `Areal Hydrography`, 2,254,757 features), excluding structural-water
  MTFCCs `H2030, H2040, H2041, H2051, H2053, H3010`, using the GeoPackage R-tree for
  candidate lookup.
- **Country gate:** point-in-polygon against TIGER 2025 US state polygons
  (`tl_2025_us_state`; SHA256 matches the pinned source manifest). A point in no US
  state polygon = `outside_country`. Validated by reproducing the manifest's Detroit
  (MKT024) classification exactly — 13/13, including all 5 known outside-country
  cardinals.

### 5.1 Result

| Outcome | Points |
|---|---|
| eligible_land | **185** |
| structural_water_exclusion | 14 |
| outside_country_exclusion | 1 (Detroit `SE4`) |

**185 / 200 diagonals eligible (92.5%)** — a touch above the ~171 estimate. The
provisional risk model held (LOW 149/151 eligible; HIGH caught 5/9). Combined with
the already-gated skeleton (410 / 450), the full grid is **595 eligible of 650**.
Authoritative per-point output:
`docs/design/data/geogrid13e_diagonal_water_classification.csv`.

## 6. Cost model

Per **eligible** coordinate, per full sweep:

| Surface | Obs/coord | Rate | $/coord |
|---|---|---|---|
| Maps/Organic | 25 ind × 4 queries × 2 surfaces = 200 | 600 µUSD | $0.120 |
| AIO | 25 ind × 10 conditions = 250 | 600 µUSD | $0.150 (+async) |
| **Combined** | | | **$0.270** |

At 595 eligible coords: **~$161/sweep**, **~$179/recurring month** collection
(month = 1 Full Panel + ~3 weekly Sentinels, ×1.112). Enrichment (core scope, ~100k
unique businesses, deduplicated) ~$500–1,000 first pass → ~$350–700 recurring as
freshness/TTL reuse kicks in (parent §10–13); prices unlocked pending a pricing
probe (parent §27). All-in ≈ **~$700–1,200 first month → ~$530–880 recurring**.

## 7. Acceptance checklist (on owner sign-off)

1. ~~Run the authoritative TIGER gate on the 200 diagonals~~ **DONE** — see
   `docs/design/data/geogrid13e_diagonal_water_classification.csv` (185 eligible).
2. ~~Author the migration~~ **DONE** — `supabase/migrations/026_geogrid13e_efficient_grid.sql`
   (generated by `scripts/gen_migration_026.py`): seeds `GEOGRID13E_V1` (13 points),
   copies the C+3/5 cardinals from `MAPORG13_V1`, adds the 200 gated 4-mile diagonals,
   repoints maps/organic/aio `surface_config` to `GEOGRID13E_V1` (retires the 1-mile
   ring; retains `MAPORG13_V1` + `AIO9_V1` as history). Idempotent, mirrors `022`/`025`.
3. ~~Update `scripts/validate_migrations.py`~~ **DONE** — counts updated
   (geometry_version 3, geometry_point 35, coords 1750 / eligible 1595 / water 141 /
   outside 14, maps/organic/aio → `GEOGRID13E_V1`). Passes on `001`–`026`; 128 tests green.
4. **PENDING (owner apply):** apply `026` to the production Supabase project, then
   update `CLAUDE.md` + `HANDOFF.md` (grid, universe counts, cost) to the new
   production state. Until applied, `MAPORG13_V1`/`AIO9_V1` stay in effect.
5. Full Panel / Sentinel executable counts re-derive from the manifest (Full Panel
   Maps+Organic 595 × 200 = 119,000 executable). No paid call until the relevant gate
   is opened + owner confirmation.
