# 0009 — Unified 21-point geo-grid (cardinal 1/3/5 + diagonal 2/4), shared across Maps/Organic and AIO

Status: **PROPOSED** (owner sign-off required; pending the authoritative TIGER
water/country gate). No migration applied, no universe change committed, no paid
calls. Supersedes nothing until accepted; `MAPORG13_V1` and `AIO9_V1` remain the
frozen, in-effect geometries.

## Context

Two frozen geometries are in effect today:

| Geometry | Surface(s) | Rings | Points | Eligible / total |
|---|---|---|---|---|
| `MAPORG13_V1` | Maps + Organic | 1, 3, 5 mi (N/E/S/W) | 13 | 590 / 650 |
| `AIO9_V1` | AIO | 2.5, 5 mi (N/E/S/W) | 9 | 410 / 450 |

Two limitations surfaced while costing Stage-2 (AIO) collection:

1. **The two surfaces sample different coordinates.** Because `MAPORG13_V1` (1/3/5)
   and `AIO9_V1` (2.5/5) share only the center, an AIO observation and a Maps/
   Organic observation are almost never taken at the same lat/lon. That blocks the
   most defensible cross-surface question the platform can ask: *at this exact
   point, does an AI Overview appear, is the business in the Local Pack, and what
   is its organic rank?* Aligning the grids makes that a within-row comparison
   instead of a cross-grid interpolation.

2. **The cardinal-only grid leaves wide angular gaps on the outer rings.** The
   chord between adjacent spokes on a ring is `radius x sqrt(2)`. Measured from the
   frozen coordinates (identical for every market — pure geometry):

   | Ring | Adjacent-spoke gap (N→E) |
   |---|---|
   | 1 mi | 1.41 mi |
   | 3 mi | 4.24 mi |
   | 5 mi | 7.07 mi |

   A 7-mile arc between the 5-mile spokes is entirely unsampled. Local-pack results
   are strongly proximity-driven within a few miles, so two spokes 7 mi apart very
   often return different businesses — and everything in the arc between them is
   invisible to the current grid. The Stage-1 pilot already showed center vs
   5-mile-N returned different local packs (ADR-0006); the between-spoke gap is
   wider still.

## Decision (proposed)

Adopt a single **21-point** geometry, `GEOGRID21_V1`, used by **both** Maps/Organic
and AIO:

- **Keep** the frozen cardinal spokes: N/E/S/W at **1, 3, 5 mi** + center (13 points,
  identical coordinates to `MAPORG13_V1`).
- **Add** the four intercardinal diagonals **NE/SE/SW/NW at 2 mi and 4 mi** (8 new
  points), interleaved between the cardinal rings.

Interleaving (diagonals at 2/4, cardinals at 1/3/5) is deliberate: every point then
occupies a unique (bearing, distance), the grid samples radii 1-2-3-4-5, and the
widest angular gap on any ring roughly halves (e.g. the outer gap drops from
~7.07 mi to ~3.83 mi between neighbors). A full compass rose on all three rings
(25 points) was rejected: the 1-mile diagonals would sit only ~0.77 mi from their
cardinal neighbors — largely redundant local packs at extra cost.

AIO moves from `AIO9_V1` to this shared grid; `AIO9_V1` and `MAPORG13_V1` are both
**retained as history** (nothing already collected is disturbed; AIO has collected
no paid data). The civic-center anchor (`CIVIC_CENTER_ANCHOR_V1`), coordinate
method (`WGS84_GEODESIC_DIRECT`, 7-decimal), and the water/country eligibility
classifier (`SED_GEO_ELIGIBILITY_CENSUS_2025_V1`) are all **unchanged** — only the
point set grows.

## Why this is not silent drift

Per the parent PRD, any geometry change requires a new versioned geometry. This ADR
+ `docs/design/unified-geo-grid-v0_1.md` are that versioned proposal. On acceptance
it lands as a new migration seeding `GEOGRID21_V1` and repointing the Maps/Organic
and AIO `surface_config` rows to it, exactly as `022`/`025` versioned the Maps and
AIO provider profiles. The frozen 13- and 9-point series remain intact and
auditable.

## Cost (proposed end-state)

Per new **eligible** coordinate per full sweep: Maps/Organic $0.12 (25 industries x
4 queries x 2 surfaces x 600 µUSD) + AIO $0.15 (25 x 10 conditions x 600 µUSD) =
**$0.27/coord/sweep** (plus the AIO async add-on, sparse for near-me intent).

Provisional eligibility of the 400 new diagonal points (see below): **~340 of 400
(85%)**, band 297–383. That puts the diagonals at **~+$92 per full sweep / ~+$102
per recurring month** across both surfaces. The AIO-unification step alone (9→13
before diagonals) adds ~+$27/sweep. Full stack:

| Configuration | Per sweep | Per recurring month |
|---|---|---|
| Today (13-pt M/O + 9-pt AIO) | ~$132 | ~$140 |
| Unify AIO to the shared grid (no diagonals) | ~$159 | ~$177 |
| **`GEOGRID21_V1` (this proposal), both surfaces** | **~$251** | **~$279** |

## Open item blocking acceptance — the authoritative eligibility gate

The eligibility numbers above are **provisional**. The frozen classifier
`SED_GEO_ELIGIBILITY_CENSUS_2025_V1` requires the TIGER 2025 AREAWATER county files
+ the international-boundary file from `www2.census.gov`, which is not reachable
from the current execution environment (egress policy denial). The 400 coordinates
were therefore generated exactly (offline, no network) but scored only
*provisionally*: each diagonal is tiered LOW/MED/HIGH by whether its flanking
cardinals are already excluded at the adjacent rings in the frozen classification
CSV.

- **297 LOW** (both flanks clear → expect eligible)
- **86 MED** (one flank water → needs the gate)
- **17 HIGH** (both flanks water → expect excluded)

Only the 103 MED+HIGH points are genuinely uncertain, concentrated in coastal /
riverfront / border markets (San Diego, SF, Seattle, Chicago, Miami, Detroit,
Boston, NYC…); 26 of 50 markets have no exclusions at all. Before acceptance, one
of: (a) allow `www2.census.gov` in the environment egress policy and run the real
gate, or (b) supply the SHA256-pinned TIGER zips. See the design doc for the exact
files.

## Consequences

- **On acceptance:** a new migration seeds `GEOGRID21_V1` (21 points) + the 400
  gated diagonal coordinates for all 50 markets, repoints Maps/Organic and AIO to
  it, and `CLAUDE.md` / `HANDOFF.md` are updated. Full Panel and Sentinel executable
  counts grow accordingly; the cadence, result depth, provider profiles, and
  missingness semantics are unchanged.
- **If rejected / deferred:** the two frozen grids stay in effect; this proposal and
  the generated coordinates remain on record for a later revisit. AIO can still be
  built on `AIO9_V1` independently of this decision.
- **Precedent:** evidence-first, versioned, retain-history — the same method as
  ADR-0006 (Maps zoom) and ADR-0008 (AIO surface/provider repoint).
