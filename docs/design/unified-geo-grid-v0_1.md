# Unified 21-point geo-grid (`GEOGRID21_V1`) — design v0.1

Status: **DESIGN for sign-off** (pairs with ADR-0009). Offline; no migration
applied, no universe change committed, no paid calls. Eligibility is
**PROVISIONAL** pending the authoritative TIGER gate.

## 1. What changes

One shared 21-point geometry replaces the two current grids going forward:

```
Frozen today                          Proposed GEOGRID21_V1 (shared)
  MAPORG13_V1 (Maps/Organic)            center
    center                              cardinals  N/E/S/W @ 1, 3, 5 mi   (unchanged)
    N/E/S/W @ 1, 3, 5 mi   = 13         diagonals  NE/SE/SW/NW @ 2, 4 mi  (NEW, +8)
  AIO9_V1 (AIO)                       ------------------------------------------
    center                              = 21 points, used by BOTH surfaces
    N/E/S/W @ 2.5, 5 mi    = 9
```

The 13 cardinal points keep their exact frozen coordinates. AIO stops using the
2.5/5 `AIO9_V1` layout and rides the shared grid, so every AIO observation is
co-located with a Maps/Organic observation at the identical lat/lon.

### 1.1 Full point set

| # | point_id | bearing° | dist (mi) | member | source |
|---|---|---|---|---|---|
| 1 | C | – | 0.0 | cardinal | frozen |
| 2–5 | N1 E1 S1 W1 | 0/90/180/270 | 1.0 | cardinal | frozen |
| 6–9 | **NE2 SE2 SW2 NW2** | 45/135/225/315 | 2.0 | **diagonal** | **new** |
| 10–13 | N3 E3 S3 W3 | 0/90/180/270 | 3.0 | cardinal | frozen |
| 14–17 | **NE4 SE4 SW4 NW4** | 45/135/225/315 | 4.0 | **diagonal** | **new** |
| 18–21 | N5 E5 S5 W5 | 0/90/180/270 | 5.0 | cardinal | frozen |

## 2. Why interleaved diagonals at 2/4 (not a full rose at 1/3/5)

Adjacent-spoke chord on a ring is `radius × √2` (measured, identical per market):

| Ring | Cardinal-only gap | With a diagonal added on that ring |
|---|---|---|
| 1 mi | 1.41 mi | 0.77 mi |
| 2 mi | – | diagonals live here |
| 3 mi | 4.24 mi | 2.30 mi |
| 4 mi | – | diagonals live here |
| 5 mi | 7.07 mi | 3.83 mi |

Placing the diagonals at their **own** rings (2, 4) rather than doubling up the
cardinal rings (1, 3, 5) gives: (a) unique (bearing, distance) for all 21 points;
(b) radial sampling at 1-2-3-4-5 mi instead of just 1-3-5; (c) the widest angular
gap on the outer arc roughly halved (~7.07 → ~3.83 mi between neighbors). A 25-point
full rose was rejected — 1-mile diagonals would sit ~0.77 mi from cardinal
neighbors (largely redundant packs) for extra cost.

## 3. Coordinate generation (done, exact)

`scripts/gen_diagonal_coords.py` emits the 400 new points (50 markets × 4 diagonals
× 2 rings) with the **same method the frozen manifest used**:

- Anchor: each market's `CIVIC_CENTER_ANCHOR_V1` civic center (read from
  `manifest/SED_Coordinates_GeoEligible_v1_0.csv`).
- Projection: `WGS84_GEODESIC_DIRECT` (geographiclib `Geodesic.WGS84.Direct`),
  7-decimal output — byte-for-byte the manifest's `coordinate_method` /
  `precision_decimal_places`.
- International mile (1609.344 m).

Output artifact (provisional, committed):
`docs/design/data/geogrid21_new_diagonal_coords_provisional.csv` — 400 rows,
`water_eligibility = PENDING_TIGER_GATE`, plus a `provisional_risk` column.

## 4. Eligibility — PROVISIONAL, and how to make it authoritative

The frozen gate `SED_GEO_ELIGIBILITY_CENSUS_2025_V1` classifies each point via:

1. **Country boundary gate** — geodesic ray from the verified U.S. center to the
   point vs `tl_2025_us_internationalboundary.zip`.
2. **Structural water gate** — point-in-polygon against the market county's
   `tl_2025_<GEOID>_areawater.zip`, excluding MTFCCs
   `H2030, H2040, H2041, H2051, H2053, H3010`.

These TIGER 2025 files (1 boundary + 1 county-routing + 78 county AREAWATER,
SHA256-pinned in `manifest/SED_Geo_Source_Manifest_v1_0.json`) live on
`www2.census.gov`, which is **not reachable** from the current environment (egress
policy denial). So the real gate has **not** run here.

### 4.1 Provisional estimate (from existing exclusion geography)

Each new diagonal is scored against the frozen classification CSV: count how many of
its two flanking cardinals are already excluded at the two adjacent rings
(NE↔{N,E}; ring 2 checks rings 1&3; ring 4 checks rings 3&5).

| Risk tier | Rule | Points | Expectation |
|---|---|---|---|
| LOW | both flanks clear | 297 | eligible |
| MED | one flank water | 86 | needs the gate |
| HIGH | both flanks water | 17 | excluded |

**Estimated eligible: ~340 / 400 (85%)**, band **297–383** (74–96%). 26 markets are
fully clean; the 103 MED+HIGH points concentrate in San Diego, San Francisco,
Seattle, Chicago, Milwaukee, Detroit, Miami, Boston, NYC, DC, and other coastal /
riverfront / border markets. This is an estimate for costing only — **not**
promotable geometry.

### 4.2 To finalize

Either **(a)** allow `www2.census.gov` in the environment egress policy, then run
the gate (download the SHA256-pinned zips, route each point to its county, run the
boundary + AREAWATER intersection, write the final classification), or **(b)** supply
the pinned TIGER zips by another route. Only the 103 MED+HIGH points can change; the
297 LOW are confidently eligible.

## 5. Cost model

Per **eligible** coordinate, per full sweep:

| Surface | Obs/coord | Rate | $/coord |
|---|---|---|---|
| Maps/Organic | 25 ind × 4 queries × 2 surfaces = 200 | 600 µUSD | $0.120 |
| AIO | 25 ind × 10 conditions = 250 | 600 µUSD | $0.150 (+async) |
| **Combined** | | | **$0.270** |

At ~340 new eligible coords: **+$92/sweep**, **+$102/recurring month** (month =
1 Full Panel + ~3 weekly Sentinels, ×1.112). Band across 297–383 eligible:
+$80…+$103 per sweep. End-state totals in ADR-0009 §Cost.

## 6. Acceptance checklist (on owner sign-off)

1. Run the authoritative TIGER gate on the 400 points → final eligibility CSV
   (replaces the provisional artifact).
2. Author the migration: seed `GEOGRID21_V1` (21 `geometry_point` rows) + the 400
   gated `market_coordinate` rows; repoint Maps/Organic and AIO `surface_config` to
   `GEOGRID21_V1`. Retain `MAPORG13_V1` + `AIO9_V1` as history. Idempotent, mirrors
   `022`/`025`.
3. Update `scripts/validate_migrations.py` expected counts (geometry_version,
   geometry_point, coordinate totals/eligibility, both surfaces → `GEOGRID21_V1`).
4. Update `CLAUDE.md` + `HANDOFF.md` (grid, universe counts, cost).
5. Full Panel / Sentinel executable counts re-derive automatically from the manifest
   (no scheduler change). No paid call until the relevant gate is opened + owner
   confirmation, as always.
