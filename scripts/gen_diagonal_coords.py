#!/usr/bin/env python3
"""Generate the proposed GEOGRID21_V1 diagonal coordinates (PROPOSAL — ADR-0009).

The current frozen grid `MAPORG13_V1` samples the cardinal spokes (N/E/S/W) at
three rings (1/3/5 mi) plus center = 13 points. This proposal extends it to a
21-point grid by adding the four intercardinal diagonals (NE/SE/SW/NW) at two
*interleaved* rings (2 mi and 4 mi), so every point occupies a unique
(bearing, distance) and the widest angular gap on any ring roughly halves. The
same 21-point grid is proposed as the shared geometry for BOTH Maps/Organic and
AIO (superseding the AIO-only `AIO9_V1`), giving co-located cross-surface
observations at identical lat/lons.

This script produces ONLY the +8 new diagonal points per market (4 diagonals x 2
rings x 50 markets = 400 points), generated with the exact same method the frozen
manifest used — `WGS84_GEODESIC_DIRECT`, 7-decimal output — anchored to each
market's existing civic-center anchor (`CIVIC_CENTER_ANCHOR_V1`). The existing 13
cardinal points are unchanged and are NOT re-emitted.

IMPORTANT — eligibility is PROVISIONAL. The authoritative water/country gate
(`SED_GEO_ELIGIBILITY_CENSUS_2025_V1`) requires the TIGER 2025 AREAWATER +
international-boundary shapefiles from www2.census.gov, which is not reachable
from the current execution environment (egress policy). This script therefore
emits a *provisional* per-point risk tier scored against the EXISTING exclusion
geography already in the frozen classification CSV (a diagonal is at risk when its
flanking cardinals are excluded at the adjacent rings). The `water_eligibility`
column is left `PENDING_TIGER_GATE`; `provisional_risk` is the estimate only. No
coordinate here is promotable until the real gate runs and the owner signs off.

Offline, deterministic, no network, no paid calls. Requires `geographiclib`.

Usage:  python scripts/gen_diagonal_coords.py
"""
from __future__ import annotations
import csv
import pathlib

from geographiclib.geodesic import Geodesic

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "manifest" / "SED_Coordinates_GeoEligible_v1_0.csv"
OUT = ROOT / "docs" / "design" / "data" / "geogrid21_new_diagonal_coords_provisional.csv"

# Proposed additions: 4 intercardinal diagonals at 2 rings interleaved with the
# frozen 1/3/5 cardinal rings.
DIAGONALS = {"NE": 45.0, "SE": 135.0, "SW": 225.0, "NW": 315.0}
RINGS_MILES = (2.0, 4.0)
MI_TO_M = 1609.344  # international mile
DECIMALS = 7  # match manifest `precision_decimal_places`

# A proposed diagonal flanks two cardinals; risk is judged against the cardinal
# exclusions at the two rings adjacent to the diagonal's ring.
FLANK = {"NE": ("N", "E"), "SE": ("S", "E"), "SW": ("S", "W"), "NW": ("N", "W")}
ADJACENT_RINGS = {2: (1, 3), 4: (3, 5)}
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


def provisional_risk(excluded_pts: set[str], diagonal: str, ring: int) -> str:
    c1, c2 = FLANK[diagonal]
    rings = ADJACENT_RINGS[ring]
    n = sum(any(f"{c}{r}" in excluded_pts for r in rings) for c in (c1, c2))
    return TIER[n]


def main() -> int:
    centers, excluded = load_centers_and_exclusions()
    geod = Geodesic.WGS84
    out_rows = []
    for mid, c in sorted(centers.items()):
        lat0, lon0 = float(c["latitude"]), float(c["longitude"])
        for ring in (2, 4):
            for diag, bearing in DIAGONALS.items():
                g = geod.Direct(lat0, lon0, bearing, ring * MI_TO_M)
                point_id = f"{diag}{ring}"
                out_rows.append({
                    "coordinate_id": f"{mid}_MAPORG_{point_id}",
                    "market_id": mid,
                    "city": c["city"],
                    "state": c["state"],
                    "geometry_id": "GEOGRID21_V1",
                    "point_id": point_id,
                    "label": f"{diag} {ring} mi",
                    "bearing_deg": bearing,
                    "distance_miles": ring,
                    "latitude": round(g["lat2"], DECIMALS),
                    "longitude": round(g["lon2"], DECIMALS),
                    "center_method_version": c["center_method_version"],
                    "coordinate_method": "WGS84_GEODESIC_DIRECT",
                    "precision_decimal_places": DECIMALS,
                    "water_eligibility": "PENDING_TIGER_GATE",
                    "provisional_risk": provisional_risk(excluded[mid], diag, ring),
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
    print(f"wrote {n} provisional diagonal coordinates -> {OUT.relative_to(ROOT)}")
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
