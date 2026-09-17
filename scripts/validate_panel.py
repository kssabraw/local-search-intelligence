#!/usr/bin/env python3
"""OFFLINE validation of the Full Panel / Sentinel wave generator (step 10).

Applies migrations 001-NNN to an ephemeral pgvector Postgres (the full frozen
Manifest v1.0 universe: 25 industries x 50 markets), then exercises the
manifest-driven generator + set-based dry-run accounting in `collector.panel`.
NO paid call, NO network, NO writes to any real database.

Asserts, for Maps + Organic:
  * generate_wave_specs lengths: Full Panel 130,000 pre-water; Sentinel 5,200;
  * job-generator v0.7 generation order (industry -> market -> surface ->
    treatment -> point);
  * set-based plan_wave water accounting on the active GEOGRID13E_V1 grid (ADR-0009
    / migration 026) -- Full Panel planned 130,000 -> executable 119,000 /
    structurally excluded 11,000 (per surface 59,500 each); Sentinel planned 5,200
    -> executable 4,480 / excluded 720 (2,240 each);
    planned == executable + structurally_excluded for both;
  * the set-based plan equals the per-spec water gate the runner applies
    (cross-checked at Sentinel scale via pilot.plan_dry_run over 5,200 specs);
  * Sentinel is a strict SUBSET of the Full Panel spec set (the Full Panel
    doubles as that week's Sentinel -- no separate collection, no drift);
  * cost estimate from the versioned price (migration 023, 600 uUSD/task):
    Full Panel ~= $71.40, Sentinel ~= $2.688.
"""
from __future__ import annotations
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

# Expected counts on the active GEOGRID13E_V1 grid (ADR-0009 / migration 026;
# see docs/design/full-panel-sentinel-scheduler-v0_1.md). Eligible-coordinate
# totals are from manifest.market_coordinate at eligibility='eligible_land':
# 595 eligible of 650 full-panel coords; 112 eligible of 130 Sentinel coords.
FP_PLANNED = 25 * 50 * 2 * 4 * 13     # 130,000 pre-water
FP_EXECUTABLE = 595 * 25 * 4 * 2      # eligible coords x 25 ind x 4 q x 2 surf = 119,000
FP_EXCLUDED = FP_PLANNED - FP_EXECUTABLE  # 11,000
SENT_PLANNED = 5 * 10 * 2 * 4 * 13    # 5,200 pre-water
SENT_EXECUTABLE = 112 * 5 * 4 * 2     # eligible coords x 5 ind x 4 q x 2 surf = 4,480
SENT_EXCLUDED = SENT_PLANNED - SENT_EXECUTABLE  # 720
UNIT_MICROUSD = 600


def main() -> int:
    import psycopg
    from collector import panel, pilot

    pg = LocalPG()
    checks: list[tuple[str, str, str]] = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")

        with psycopg.connect(pg.dsn()) as conn:
            # ---- scope loading ----
            fp_ind, fp_mkt = panel.load_scope(conn, kind="full_panel", methodology_code="MANIFEST_V1_0")
            se_ind, se_mkt = panel.load_scope(conn, kind="sentinel", methodology_code="MANIFEST_V1_0")
            check("full panel industries", len(fp_ind), 25)
            check("full panel markets", len(fp_mkt), 50)
            check("sentinel industries", len(se_ind), 5)
            check("sentinel markets", len(se_mkt), 10)
            check("sentinel industries subset of full", set(se_ind) <= set(fp_ind), True)
            check("sentinel markets subset of full", set(se_mkt) <= set(fp_mkt), True)
            check("treatments uniform Q1-Q4",
                  panel.load_treatments(conn, methodology_code="MANIFEST_V1_0"),
                  ["Q1", "Q2", "Q3", "Q4"])
            # Geometry is surface_config-resolved (GEOGRID13E_V1 per ADR-0009 /
            # migration 026), never hardcoded — the active-grid point set.
            active_points = panel.load_points(conn)
            check("active-grid points (GEOGRID13E_V1)", len(active_points), 13)
            check("active-grid point codes", active_points,
                  ["C", "N3", "E3", "S3", "W3", "NE4", "SE4", "SW4", "NW4", "N5", "E5", "S5", "W5"])
            check("Maps/Organic geometry resolved from surface_config",
                  pilot.resolve_active_geometry(conn, surfaces=panel.SURFACES), "GEOGRID13E_V1")

            # ---- generator lengths + order ----
            fp_specs = panel.generate_wave_specs(conn, kind="full_panel")
            se_specs = panel.generate_wave_specs(conn, kind="sentinel")
            check("full panel spec count (pre-water)", len(fp_specs), FP_PLANNED)
            check("sentinel spec count (pre-water)", len(se_specs), SENT_PLANNED)

            # v0.7 order: industry -> market -> surface -> treatment -> point.
            # First 13 specs = IND001 x MKT001 x maps x Q1 x (13 points).
            first = fp_specs[:13]
            check("order: first block same industry", {s.industry for s in first}, {"IND001"})
            check("order: first block same market", {s.market for s in first}, {"MKT001"})
            check("order: first block same surface", {s.surface for s in first}, {"maps"})
            check("order: first block same treatment", {s.treatment for s in first}, {"Q1"})
            check("order: first block 13 distinct points", len({s.point for s in first}), 13)
            # spec #14 advances the treatment (still maps, still MKT001).
            check("order: point is innermost (14th advances treatment)",
                  (fp_specs[13].surface, fp_specs[13].treatment), ("maps", "Q2"))

            # Sentinel is a strict subset of the Full Panel spec set (superset
            # property -> the Full Panel doubles as that week's Sentinel).
            fp_set = {s.label for s in fp_specs}
            check("sentinel specs subset of full panel specs",
                  {s.label for s in se_specs} <= fp_set, True)

            # ---- set-based dry-run accounting ----
            fp_plan = panel.plan_wave(conn, kind="full_panel")
            se_plan = panel.plan_wave(conn, kind="sentinel")
            check("FP planned", fp_plan["planned"], FP_PLANNED)
            check("FP executable", fp_plan["executable"], FP_EXECUTABLE)
            check("FP structurally_excluded", fp_plan["structurally_excluded"], FP_EXCLUDED)
            check("FP planned == exec + excluded",
                  fp_plan["executable"] + fp_plan["structurally_excluded"], fp_plan["planned"])
            check("FP maps executable", fp_plan["per_surface"]["maps"]["executable"], 59_500)
            check("FP organic executable", fp_plan["per_surface"]["organic"]["executable"], 59_500)
            check("FP spec count == planned", len(fp_specs), fp_plan["planned"])

            check("SENT planned", se_plan["planned"], SENT_PLANNED)
            check("SENT executable", se_plan["executable"], SENT_EXECUTABLE)
            check("SENT structurally_excluded", se_plan["structurally_excluded"], SENT_EXCLUDED)
            check("SENT planned == exec + excluded",
                  se_plan["executable"] + se_plan["structurally_excluded"], se_plan["planned"])
            check("SENT maps executable", se_plan["per_surface"]["maps"]["executable"], 2_240)
            check("SENT organic executable", se_plan["per_surface"]["organic"]["executable"], 2_240)
            check("SENT spec count == planned", len(se_specs), se_plan["planned"])

            # ---- set-based plan == per-spec water gate (cross-check at Sentinel scale) ----
            # pilot.plan_dry_run loads manifest context per spec and applies the
            # SAME eligibility gate the runner applies; its totals must equal the
            # set-based plan, proving the SQL is faithful to per-spec execution.
            se_perspec = pilot.plan_dry_run(conn, se_specs)
            check("SENT set-based executable == per-spec executable",
                  se_plan["executable"], se_perspec["executable"])
            check("SENT set-based excluded == per-spec excluded",
                  se_plan["structurally_excluded"], se_perspec["structurally_excluded"])
            check("SENT per-spec no conformity failures", len(se_perspec["conformity_failures"]), 0)
            check("SENT per-spec wrote nothing (no jobs)",
                  conn.execute("select count(*) from ops.collection_job").fetchone()[0], 0)

            # ---- cost estimate from the versioned price ----
            check("FP expected unit price (uUSD)", fp_plan["cost_estimate"]["expected_unit_microusd"], UNIT_MICROUSD)
            check("FP estimated cost USD", fp_plan["cost_estimate"]["estimated_cost_usd"],
                  round(FP_EXECUTABLE * UNIT_MICROUSD / 1_000_000, 6))
            check("SENT estimated cost USD", se_plan["cost_estimate"]["estimated_cost_usd"],
                  round(SENT_EXECUTABLE * UNIT_MICROUSD / 1_000_000, 6))

            # every stratum clears the QA >=20-executable floor at panel scale.
            check("FP no stratum under 20 executable", len(fp_plan["strata_under_20"]), 0)
            check("SENT no stratum under 20 executable", len(se_plan["strata_under_20"]), 0)

        print(f"\n{'check':<52} {'result':<30} status")
        print("-" * 96)
        failed = 0
        for label, r, status in checks:
            failed += status == "FAIL"
            print(f"{label:<52} {r:<30} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
