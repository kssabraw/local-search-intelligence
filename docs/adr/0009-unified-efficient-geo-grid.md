# 0009 — Unified efficient 13-point geo-grid (`GEOGRID13E_V1`), shared across Maps/Organic and AIO

Status: **PROPOSED — eligibility gate COMPLETE** (owner sign-off still required to
accept). The authoritative TIGER water + country gate has now been run on the 200
new diagonals (§Open item below). No migration applied, no universe change
committed, no paid calls. Supersedes nothing until accepted; `MAPORG13_V1` and
`AIO9_V1` remain the frozen, in-effect geometries.

> This revises an earlier draft of ADR-0009 that proposed a 21-point grid
> (cardinals 1/3/5 + diagonals 2/4). Measured saturation on the first Full Panel
> (below) showed the 1-mile ring is the least efficient sample, so the proposal is
> refined to an *efficient* 13-point grid that drops the 1-mile ring and adds a
> single 4-mile diagonal ring — same footprint as today, more businesses per point.

## Context

Two frozen geometries are in effect today:

| Geometry | Surface(s) | Rings | Points | Eligible / total |
|---|---|---|---|---|
| `MAPORG13_V1` | Maps + Organic | 1, 3, 5 mi (N/E/S/W) | 13 | 590 / 650 |
| `AIO9_V1` | AIO | 2.5, 5 mi (N/E/S/W) | 9 | 410 / 450 |

Two limitations, both now backed by measured data:

1. **The two surfaces sample different coordinates.** `MAPORG13_V1` (1/3/5) and
   `AIO9_V1` (2.5/5) share only the center, so an AIO observation and a Maps/Organic
   observation are almost never co-located. Aligning the grids makes the key
   cross-surface question — *at this exact point, does an AI Overview appear, is the
   business in the Local Pack, and what is its organic rank?* — a within-row
   comparison instead of a cross-grid interpolation.

2. **The 1-mile ring is inefficient; the outer band carries the capture.** Measured
   on the first Full Panel (Maps, 10 markets, 100 cells each — avg unique businesses
   per cell as rings accumulate):

   | Subset | Businesses/cell | Marginal / point |
   |---|---|---|
   | center | 9.7 | 9.7 |
   | + 1-mi ring | 18.1 | 2.1 |
   | + 3-mi ring | 32.4 (vs center) | 5.7 |
   | + 5-mi ring | 36.6 (vs center) | 6.7 |
   | center + 3 + 5 (9 pt) | 49.3 | — |
   | full 13-pt (1/3/5) | 53.6 | — |

   Once the 3- and 5-mile rings are present, the **1-mile ring adds only +4.3
   businesses across its four points** (1.1/point) — near-center packs overlap the
   center. The outer rings each add ~4–7 new businesses *per point*. The grid is far
   from saturated (the 3-mile grid captures only ~59–82% of what the 13-point finds),
   so more *outer* angular sampling keeps discovering businesses.

## Decision (proposed)

Adopt a single **efficient 13-point** geometry, `GEOGRID13E_V1`, used by **both**
Maps/Organic and AIO:

```
center                          (0 mi)
N / E / S / W        @ 3 mi      (cardinals — reused from MAPORG13_V1)
NE / SE / SW / NW    @ 4 mi      (diagonals — NEW)
N / E / S / W        @ 5 mi      (cardinals — reused from MAPORG13_V1)
```

Relative to `MAPORG13_V1` this **drops the low-yield 1-mile cardinal ring** and
**adds a 4-mile diagonal ring**. The 4-mile diagonals do two things at once:

- **Fill the widest angular gaps in the productive 3–5 mi band** (the 5-mile
  cardinal spokes are ~7 mi apart; a 4-mile diagonal sits ~2+ mi from any existing
  point — fresh territory).
- **Restore a distance sample the 9-point base gave up**, at a *valuable* radius:
  the grid samples radii 0/3/4/5, keeping ≥3 non-zero-distance points for the
  Maps/Organic distance-decay / Effective-Ranking-Radius science — but in the
  outer band instead of the wasteful 1-mile ring.

Result: **same 13-point footprint (same collection cost) as today, ~14% more
unique businesses per cell** (~61 vs 53.6, estimated). AIO moves from `AIO9_V1`
to this shared grid; both `AIO9_V1` and `MAPORG13_V1` are **retained as history**
(nothing already collected is disturbed; AIO has collected no paid data). Civic
anchor, coordinate method (`WGS84_GEODESIC_DIRECT`, 7-decimal), and the eligibility
classifier are all **unchanged** — only the point set is reallocated.

## Why this is not silent drift

Per the parent PRD, any geometry change requires a new versioned geometry. This ADR
+ `docs/design/unified-geo-grid-v0_1.md` are that versioned, evidence-first proposal
(same method as ADR-0006). On acceptance it lands as a new migration seeding
`GEOGRID13E_V1` and repointing the Maps/Organic and AIO `surface_config` rows to it.
The frozen 13- and 9-point series remain intact and auditable.

## Cost (proposed end-state)

Per **eligible** coordinate per full sweep: Maps/Organic $0.12 (25 industries x 4
queries x 2 surfaces x 600 µUSD) + AIO $0.15 (25 x 10 conditions x 600 µUSD) =
**$0.27/coord/sweep** (plus the AIO async add-on, sparse for near-me intent).

Eligible coordinates = **410** (center + 3/5 cardinals, measured) **+ 185**
(4-mile diagonals, **gate-confirmed**) **= 595**.

| Line | Per sweep | Per month |
|---|---|---|
| Collection (Maps + Organic + AIO), 595 eligible × $0.27 | ~$161 | ~$179 |
| Enrichment (core scope, ~100k unique businesses, deduplicated) | — | ~$500–1,000 (first) → ~$350–700 (recurring) |
| **All-in** | | **~$700–1,200 (first) → ~$530–880 (recurring)** |

Collection is flat month to month (re-observing the panel *is* the time series);
recurring enrichment falls as freshness/TTL reuse kicks in on the ~80% stable
businesses (parent §10–13), while volatile signals (reviews, backlinks) still
refresh monthly by design. Enrichment prices are **not yet locked** — a pricing
probe is required before any enrichment figure is validated (parent §27).

Versus the earlier 21-point draft (~$255/sweep, ~73 biz/cell) this efficient
13-point captures ~61 biz/cell at ~$157/sweep — better cost-per-business and ~$100+
/month cheaper collection.

## Eligibility gate — COMPLETE (authoritative)

The classifier `SED_GEO_ELIGIBILITY_CENSUS_2025_V1` was run on the 200 new 4-mile
diagonals: the **structural-water gate** against the TIGER 2025 AREAWATER GeoPackage
(national `Areal Hydrography`, 2,254,757 features; excluded MTFCCs H2030/H2040/
H2041/H2051/H2053/H3010, point-in-polygon via the GeoPackage R-tree) and the
**country gate** against TIGER 2025 US state polygons (`tl_2025_us_state`, SHA256
matches the pinned source manifest; a point in no US state polygon = outside
country). The country method was validated by reproducing the manifest's Detroit
(MKT024) classification exactly (13/13, all 5 known outside-country points).

Result on the 200 diagonals:

- **185 eligible_land**
- **14 structural_water_exclusion** (coastal / riverfront markets: San Diego, SF,
  Seattle, Chicago ×2, Milwaukee ×2, Cincinnati, Memphis, Miami, Baltimore, NYC,
  Boston, Detroit)
- **1 outside_country_exclusion** (Detroit `SE4`, across the Windsor border)

→ **185 / 200 diagonals eligible (92.5%)**. The provisional risk model held: LOW
149/151 eligible, HIGH caught 5/9. Combined with the already-gated skeleton
(410/450), the full grid is **595 eligible of 650**. Authoritative per-point output:
`docs/design/data/geogrid13e_diagonal_water_classification.csv`.

Remaining to accept: this is the last blocker cleared — acceptance now needs only
owner sign-off and the migration (see Consequences).

## Consequences

- **On acceptance:** a migration seeds `GEOGRID13E_V1` (13 points) + the ~171 gated
  4-mile diagonal coordinates, repoints Maps/Organic and AIO to it, and retires the
  1-mile ring from the active grid (kept in history). `CLAUDE.md` / `HANDOFF.md` and
  `scripts/validate_migrations.py` counts updated. Full Panel / Sentinel executable
  counts re-derive from the manifest; cadence, result depth, provider profiles, and
  missingness semantics unchanged.
- **If rejected / deferred:** the two frozen grids stay in effect; this proposal and
  the generated coordinates remain on record.
- **Precedent:** evidence-first, versioned, retain-history — same method as ADR-0006
  (Maps zoom) and ADR-0008 (AIO surface/provider repoint).
