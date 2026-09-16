#!/usr/bin/env python3
"""Generate the proposed GEOGRID13E_V1 diagonal coordinates (PROPOSAL — ADR-0009).

The current frozen grid `MAPORG13_V1` samples the cardinal spokes (N/E/S/W) at
three rings (1/3/5 mi) plus center = 13 points. Measured saturation on the first
Full Panel (see docs/design/unified-geo-grid-v0_1.md) showed the 1-mile ring is
the least efficient sample: once the 3- and 5-mile rings are present it adds only
~4 net new businesses across its four points, because near-center packs overlap
the center. New businesses live in the 3-5 mi band.

This proposal reallocates to an *efficient* 13-point grid, `GEOGRID13E_V1`, used
as the shared geometry for BOTH Maps/Organic and AIO:

    center (0 mi)
    N / E / S / W        @ 3 mi   (cardinals, reused from MAPORG13_V1)
    NE / SE / SW / NW    @ 4 mi   (diagonals, NEW — this script)
    N / E / S / W        @ 5 mi   (cardinals, reused from MAPORG13_V1)

vs MAPORG13_V1 it DROPS the low-yield 1-mile cardinal ring and adds a 4-mile
diagonal ring. Same 13-point footprint (same collection cost) but ~14% more
unique businesses per cell, and it keeps three non-zero-distance samples on the
diagonals/cardinals combined (radii 0/3/4/5) for distance-decay analysis.

Only the 4-mile diagonals are NEW coordinates (4 diagonals x 50 markets = 200).
The center + 3/5-mile cardinals already exist in the manifest (already gated:
410 eligible of 450), so they are reused, not re-emitted here.

IMPORTANT — eligibility is PROVISIONAL. The authoritative water/country gate
(`SED_GEO_ELIGIBILITY_CENSUS_2025_V1`) requires the TIGER 2025 AREAWATER +
international-boundary shapefiles from www2.census.gov, which is not reachable
from the current execution environment (egress policy). This script emits the 200
new points generated exactly (offline, WGS84 geodesic direct, 7-decimal), with a
*provisional* per-point risk tier scored against the EXISTING exclusion geography
in the frozen classification CSV (a 4-mile diagonal is at risk when its flanking
cardinals are excluded at the adjacent 3- and 5-mile rings). `water_eligibility`
is left `PENDING_TIGER_GATE`; no coordinate is promotable until the real gate runs
and the owner signs off.

Offline, deterministic, no network, no paid calls. Requires `geographiclib`.

Usage:  python scripts/gen_diagonal_coords.py
"""
from __future__ import annotations
import csv
import pathlib

from geographiclib.geodesic import Geodesic

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "manifest" / "SED_Coordinates_GeoEligible_v1_0.csv"
OUT = ROOT / "docs" / "design" / "data" / "geogrid13e_new_diagonal_coords_provisional.csv"

# Proposed additions: the four intercardinal diagonals at a single 4-mile ring,
# interleaved between the frozen 3- and 5-mile cardinal rings.
DIAGONALS = {"NE": 45.0, "SE": 135.0, "SW": 225.0, "NW": 315.0}
RING_MILES = 4.0
MI_TO_M = 1609.344  # international mile
DECIMALS = 7  # match manifest `precision_decimal_places`

# A 4-mile diagonal flanks two cardinals; risk is judged against the cardinal
# exclusions at the rings adjacent to the 4-mile diagonal (3 mi and 5 mi).
FLANK = {"NE": ("N", "E"), "SE": ("S", "E"), "SW": ("S", "W"), "NW": ("N", "W")}
ADJACENT_RINGS = (3, 5)
TIER = {0: "LOW", 1: "MED", 2: "HIGH"}  # count of flanking cardinals excluded nearby


def load_centers_and_exclusions():
    """Return {market_id: center_row} and {market_id: set(excluded MAPORG point_ids)}."""
    rows = list(csv.DictReader(SRC.open()))
    maporg = [r for r in rows if r["surface_group"] == "maps_organic"]
    centers = {r["market_id"]: r for r in maporg if r["point_id"] == "C"}
    excluded: dict[str, set[str]] = {mid: set() for mid in centers}
    for r in maporg:
        if r["collection_eligibility"] != "ELIGIBLE":
            excluded[r["market_id"]].add(r["point_id"])
    if len(centers) != 50:
        raise SystemExit(f"expected 50 civic-center anchors, found {len(centers)}")
    return centers, excluded


def provisional_risk(excluded_pts: set[str], diagonal: str) -> str:
    c1, c2 = FLANK[diagonal]
    n = sum(any(f"{c}{r}" in excluded_pts for r in ADJACENT_RINGS) for c in (c1, c2))
    return TIER[n]


def main() -> int:
    centers, excluded = load_centers_and_exclusions()
    geod = Geodesic.WGS84
    out_rows = []
    for mid, c in sorted(centers.items()):
        lat0, lon0 = float(c["latitude"]), float(c["longitude"])
        for diag, bearing in DIAGONALS.items():
            g = geod.Direct(lat0, lon0, bearing, RING_MILES * MI_TO_M)
            point_id = f"{diag}4"
            out_rows.append({
                "coordinate_id": f"{mid}_MAPORG_{point_id}",
                "market_id": mid,
                "city": c["city"],
                "state": c["state"],
                "geometry_id": "GEOGRID13E_V1",
                "point_id": point_id,
                "label": f"{diag} 4 mi",
                "bearing_deg": bearing,
                "distance_miles": RING_MILES,
                "latitude": round(g["lat2"], DECIMALS),
                "longitude": round(g["lon2"], DECIMALS),
                "center_method_version": c["center_method_version"],
                "coordinate_method": "WGS84_GEODESIC_DIRECT",
                "precision_decimal_places": DECIMALS,
                "water_eligibility": "PENDING_TIGER_GATE",
                "provisional_risk": provisional_risk(excluded[mid], diag),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    tiers = {"LOW": 0, "MED": 0, "HIGH": 0}
    for r in out_rows:
        tiers[r["provisional_risk"]] += 1
    n = len(out_rows)
    print(f"wrote {n} provisional 4-mile diagonal coordinates -> {OUT.relative_to(ROOT)}")
    print(f"  risk tiers: LOW={tiers['LOW']}  MED={tiers['MED']}  HIGH={tiers['HIGH']}")
    print(f"  provisional eligible estimate (MED at 50/50): "
          f"{tiers['LOW'] + 0.5 * tiers['MED']:.0f} / {n} "
          f"({(tiers['LOW'] + 0.5 * tiers['MED']) / n * 100:.1f}%)  "
          f"[band {tiers['LOW']}-{tiers['LOW'] + tiers['MED']}]")
    print("  water_eligibility is PENDING_TIGER_GATE — not promotable until the "
          "real gate runs + owner sign-off.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
