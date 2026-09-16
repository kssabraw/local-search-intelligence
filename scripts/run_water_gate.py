#!/usr/bin/env python3
"""Structural-water gate for proposed coordinates, against a TIGER AREAWATER GeoPackage.

Classifies each input coordinate as `structural_water_exclusion` or `eligible_land`
by testing it against the TIGER 2025 AREAWATER polygons of the structural-water
MTFCCs (the classifier `SED_GEO_ELIGIBILITY_CENSUS_2025_V1` uses:
H2030, H2040, H2041, H2051, H2053, H3010).

Reads the GeoPackage directly with the Python stdlib `sqlite3` + `shapely` — no
GDAL / fiona / geopandas. A GeoPackage is a SQLite DB; this script:
  1. finds the feature table + geometry column from `gpkg_geometry_columns`,
  2. finds the MTFCC attribute column (case-insensitive),
  3. uses the GeoPackage R-tree index (`rtree_<table>_<geom>`) to fetch only the
     features whose bounding box contains each point,
  4. parses each candidate's GeoPackage geometry BLOB header -> WKB -> shapely, and
     runs a precise point-in-polygon test on the excluded-MTFCC features only.

NOTE — this runs ONLY the structural-water gate. The country-boundary gate needs
`tl_2025_us_internationalboundary.zip` (not this file); for border markets (e.g.
Detroit / MKT024) the water gate catches river/lake points, but a point on dry land
across the international border needs the boundary file. Such points are left
`country_boundary_status = not_evaluated_no_boundary_file` and flagged in output.

Coordinate ref systems: AREAWATER is NAD83 (EPSG:4269) lon/lat degrees; the input
points are WGS84 (EPSG:4326) lon/lat. The datum difference is < ~1 m at these
latitudes — negligible for a structural-water polygon test. (Documented, not
corrected.)

Offline, deterministic, no network, no paid calls. Requires `shapely`.

Usage:
  python scripts/run_water_gate.py \
      --gpkg /path/to/tlgpkg_db_2025_a_us_areawater.gpkg \
      --coords docs/design/data/geogrid13e_new_diagonal_coords_provisional.csv \
      --out    docs/design/data/geogrid13e_diagonal_water_classification.csv
"""
from __future__ import annotations
import argparse
import csv
import sqlite3
import struct
import sys

from shapely import wkb as shapely_wkb
from shapely.geometry import Point

EXCLUDE_MTFCC = {"H2030", "H2040", "H2041", "H2051", "H2053", "H3010"}
CLASSIFIER = "SED_GEO_ELIGIBILITY_CENSUS_2025_V1"


def parse_gpkg_geometry(blob: bytes):
    """GeoPackage geometry BLOB -> shapely geometry (strips the GP header, keeps WKB)."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry blob (missing 'GP' magic)")
    flags = blob[3]
    envelope_code = (flags >> 1) & 0x07
    env_bytes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope_code)
    if env_bytes is None:
        raise ValueError(f"invalid envelope indicator {envelope_code}")
    header_len = 8 + env_bytes  # magic(2)+ver(1)+flags(1)+srs_id(4) + envelope
    return shapely_wkb.loads(blob[header_len:])


def introspect(con: sqlite3.Connection):
    """Return (feature_table, geom_col, mtfcc_col, rtree_table)."""
    row = con.execute(
        "select table_name, column_name from gpkg_geometry_columns limit 1"
    ).fetchone()
    if not row:
        raise SystemExit("no rows in gpkg_geometry_columns — is this a GeoPackage?")
    table, geom = row
    cols = [r[1] for r in con.execute(f'pragma table_info("{table}")').fetchall()]
    mtfcc = next((c for c in cols if c.lower() == "mtfcc"), None)
    if not mtfcc:
        raise SystemExit(f"no MTFCC column in feature table '{table}'; columns: {cols}")
    rtree = f"rtree_{table}_{geom}"
    has_rtree = con.execute(
        "select count(*) from sqlite_master where type='table' and name=?", (rtree,)
    ).fetchone()[0]
    if not has_rtree:
        raise SystemExit(f"expected R-tree index '{rtree}' not found; cannot spatially query")
    return table, geom, mtfcc, rtree


def classify_point(con, table, geom, mtfcc, rtree, lat, lon):
    """Return (status, feature_dict|None). status in {structural_water_exclusion, eligible_land}."""
    # R-tree: features whose bbox contains the point. Then precise test on excluded MTFCCs.
    rowids = [r[0] for r in con.execute(
        f'select id from "{rtree}" where minx<=? and maxx>=? and miny<=? and maxy>=?',
        (lon, lon, lat, lat),
    ).fetchall()]
    if not rowids:
        return "eligible_land", None
    pt = Point(lon, lat)
    qmarks = ",".join("?" * len(rowids))
    rows = con.execute(
        f'select rowid, "{mtfcc}", "{geom}" from "{table}" '
        f"where rowid in ({qmarks}) and \"{mtfcc}\" in ({','.join('?'*len(EXCLUDE_MTFCC))})",
        (*rowids, *sorted(EXCLUDE_MTFCC)),
    ).fetchall()
    for rowid, mt, blob in rows:
        try:
            g = parse_gpkg_geometry(blob)
        except Exception as e:  # noqa: BLE001 - a bad blob shouldn't abort the run
            sys.stderr.write(f"  warn: geom parse failed rowid={rowid}: {e}\n")
            continue
        if g.covers(pt):
            return "structural_water_exclusion", {"rowid": rowid, "mtfcc": mt}
    return "eligible_land", None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpkg", required=True, help="path to the extracted AREAWATER .gpkg")
    ap.add_argument("--coords", required=True, help="input coordinates CSV (needs coordinate_id, latitude, longitude)")
    ap.add_argument("--out", required=True, help="output classification CSV")
    ap.add_argument("--limit", type=int, default=0, help="classify only the first N (debug)")
    args = ap.parse_args()

    pts = list(csv.DictReader(open(args.coords)))
    if args.limit:
        pts = pts[: args.limit]

    con = sqlite3.connect(f"file:{args.gpkg}?mode=ro", uri=True)
    table, geom, mtfcc, rtree = introspect(con)
    sys.stderr.write(f"gpkg: table={table} geom={geom} mtfcc={mtfcc} rtree={rtree}\n")

    out_rows, water, land = [], 0, 0
    for i, p in enumerate(pts, 1):
        lat, lon = float(p["latitude"]), float(p["longitude"])
        status, feat = classify_point(con, table, geom, mtfcc, rtree, lat, lon)
        water += status == "structural_water_exclusion"
        land += status == "eligible_land"
        out_rows.append({
            "coordinate_id": p["coordinate_id"],
            "market_id": p.get("market_id", ""),
            "point_id": p.get("point_id", ""),
            "latitude": lat, "longitude": lon,
            "water_eligibility_status": status,
            "matched_mtfcc": feat["mtfcc"] if feat else "",
            "matched_feature_rowid": feat["rowid"] if feat else "",
            "country_boundary_status": "not_evaluated_no_boundary_file",
            "collection_eligibility": "STRUCTURAL_WATER" if status == "structural_water_exclusion" else "ELIGIBLE_PENDING_COUNTRY_GATE",
            "classifier_version": CLASSIFIER,
        })
        if i % 50 == 0:
            sys.stderr.write(f"  ...{i}/{len(pts)}\n")
    con.close()

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader(); w.writerows(out_rows)

    print(f"classified {len(out_rows)} points -> {args.out}")
    print(f"  structural_water_exclusion: {water}")
    print(f"  eligible_land (water gate):  {land}")
    print("  NOTE: country-boundary gate NOT run (needs tl_2025_us_internationalboundary);")
    print("        border-market land points remain country_boundary_status=not_evaluated_no_boundary_file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
