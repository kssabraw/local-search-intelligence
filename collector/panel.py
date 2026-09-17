"""Manifest-driven Full Panel / Sentinel wave generator + dry-run accounting.

Step 10 (ADR-0007, docs/design/full-panel-sentinel-scheduler-v0_1.md). The
bounded Stage-1 pilot proved the per-job path end to end; this module scales
collection to the frozen 25x50 universe **for Maps + Organic only**, without
methodology drift, by reading the universe from the manifest instead of the
pilot's hardcoded cells.

Two wave kinds, both a *selection over the frozen universe* (not new science):

  * ``full_panel``  -- all industries x all markets (monthly).
  * ``sentinel``    -- the fixed ``SENTINEL_V1`` panel subset
                       (5 industries x 10 markets), weekly, EXCEPT the week a
                       Full Panel runs (the Full Panel is a strict superset of the
                       Sentinel cells and doubles as that week's Sentinel).

The spec expansion reuses the validated pilot expansion verbatim
(``pilot.expand_matrix`` -- the job-generator v0.7 order
industry -> market -> surface -> treatment -> point). The only new logic here is
loading the scope from the manifest and a **set-based** dry-run accounting that
does not loop per job (the Full Panel is ~130,000 rows; a per-spec water gate
round-trip is neither how you plan nor how you'd execute at that scale).

This module contains **no paid path**: it plans only. Live panel collection lands
with the Standard decoupled DataForSEO adapter (design doc step 2) behind the
``RUN_PAID_PANEL`` gate; nothing here calls a provider or writes to the DB.
"""
from __future__ import annotations

import argparse
import json
from typing import Any, Optional

from . import pilot
from .pilot import PilotJobSpec

# Frozen Stage-1-in-scope surfaces / treatment set (Maps + Organic). The geometry
# is NOT hardcoded: it is resolved at run time from manifest.surface_config (the
# grid the maps/organic surfaces are currently configured on — GEOGRID13E_V1 per
# ADR-0009 / migration 026), so a repoint is followed with no code change and a
# per-surface divergence is refused rather than mixing grids.
SURFACES = ["maps", "organic"]
TREATMENT_SET = "GOOGLE_QUERY_V1"
SENTINEL_SUBSET_CODE = "SENTINEL_V1"

FULL_PANEL = "full_panel"
SENTINEL = "sentinel"
WAVE_KINDS = (FULL_PANEL, SENTINEL)

STRATUM_MIN_EXECUTABLE = pilot.STRATUM_MIN_EXECUTABLE  # 20 (QA per-stratum floor)


# ---------------------------------------------------------------------------
# Scope loading (from the manifest, never hardcoded)
# ---------------------------------------------------------------------------
def _methodology_version_id(conn, methodology_code: str) -> str:
    row = conn.execute(
        "select methodology_version_id from manifest.methodology_version where methodology_code=%s",
        (methodology_code,),
    ).fetchone()
    if row is None:
        raise LookupError(f"unknown methodology_code {methodology_code}")
    return row[0]


def load_scope(conn, *, kind: str, methodology_code: str) -> tuple[list[str], list[str]]:
    """(industry_codes, market_codes) for the wave kind, in code order.

    Full Panel = every industry x every market. Sentinel = the fixed
    ``SENTINEL_V1`` panel-subset membership. Codes are zero-padded (IND001..,
    MKT001..), so lexical order is the job-generator v0.7 order.
    """
    if kind not in WAVE_KINDS:
        raise ValueError(f"unknown wave kind {kind!r}; expected one of {WAVE_KINDS}")
    if kind == FULL_PANEL:
        industries = [r[0] for r in conn.execute(
            "select industry_code from manifest.industry order by industry_code")]
        markets = [r[0] for r in conn.execute(
            "select market_code from manifest.market order by market_code")]
        return industries, markets

    mv_id = _methodology_version_id(conn, methodology_code)
    industries = [r[0] for r in conn.execute(
        "select i.industry_code from manifest.panel_subset ps "
        "join manifest.panel_subset_industry psi on psi.panel_subset_id=ps.panel_subset_id "
        "join manifest.industry i on i.industry_id=psi.industry_id "
        "where ps.methodology_version_id=%s and ps.subset_code=%s order by i.industry_code",
        (mv_id, SENTINEL_SUBSET_CODE))]
    markets = [r[0] for r in conn.execute(
        "select mk.market_code from manifest.panel_subset ps "
        "join manifest.panel_subset_market psm on psm.panel_subset_id=ps.panel_subset_id "
        "join manifest.market mk on mk.market_id=psm.market_id "
        "where ps.methodology_version_id=%s and ps.subset_code=%s order by mk.market_code",
        (mv_id, SENTINEL_SUBSET_CODE))]
    if not industries or not markets:
        raise LookupError(f"panel subset {SENTINEL_SUBSET_CODE} not seeded for {methodology_code}")
    return industries, markets


def load_treatments(conn, *, methodology_code: str) -> list[str]:
    """The GOOGLE_QUERY_V1 treatment codes in sequence order.

    Verifies the treatment set is uniform across industries (Manifest v1.0: every
    industry carries the same 4 codes); a non-uniform set would mean the flat
    expansion is wrong and is refused rather than silently truncated.
    """
    mv_id = _methodology_version_id(conn, methodology_code)
    rows = conn.execute(
        "select treatment_code, count(distinct industry_id) as inds, min(sequence) as seq "
        "from manifest.treatment "
        "where methodology_version_id=%s and treatment_set_code=%s "
        "group by treatment_code order by min(sequence)",
        (mv_id, TREATMENT_SET),
    ).fetchall()
    if not rows:
        raise LookupError(f"treatment set {TREATMENT_SET} not seeded for {methodology_code}")
    n_industries = conn.execute("select count(*) from manifest.industry").fetchone()[0]
    non_uniform = [code for code, inds, _ in rows if inds != n_industries]
    if non_uniform:
        raise ValueError(
            f"treatment set {TREATMENT_SET} is not uniform across all {n_industries} industries "
            f"(codes not present for every industry: {non_uniform}); the flat panel expansion "
            f"assumes a uniform set -- resolve in the manifest before generating a wave")
    return [code for code, _, _ in rows]


def load_points(conn, *, methodology_code: str = "MANIFEST_V1_0") -> list[str]:
    """The active Maps/Organic geometry's point codes in ordinal order.

    The geometry is resolved from manifest.surface_config (the grid the
    maps/organic surfaces are currently on — GEOGRID13E_V1), never hardcoded, so
    it tracks a repoint automatically and refuses a per-surface divergence.
    """
    return pilot.load_active_points(conn, methodology_code=methodology_code, surfaces=SURFACES)


def generate_wave_specs(conn, *, kind: str, methodology_code: str = "MANIFEST_V1_0") -> list[PilotJobSpec]:
    """The full pre-water spec list for a wave, in job-generator v0.7 order.

    Reuses the validated ``pilot.expand_matrix`` expansion verbatim -- only the
    scope (industries / markets / treatments / points) is loaded from the
    manifest rather than hardcoded. The water gate, idempotency, and
    ``blocked_structural`` accounting are applied downstream by the existing
    runner exactly as in the pilot.
    """
    industries, markets = load_scope(conn, kind=kind, methodology_code=methodology_code)
    treatments = load_treatments(conn, methodology_code=methodology_code)
    points = load_points(conn, methodology_code=methodology_code)
    return pilot.expand_matrix(industries=industries, markets=markets, surfaces=SURFACES,
                               treatments=treatments, points=points)


# ---------------------------------------------------------------------------
# Set-based dry-run accounting (NO writes, NO provider call, O(1) queries)
# ---------------------------------------------------------------------------
def plan_wave(conn, *, kind: str, methodology_code: str = "MANIFEST_V1_0") -> dict[str, Any]:
    """Water-gated accounting for the wave, computed set-based in the DB.

    Returns the same shape as the pilot's per-spec ``plan_dry_run``
    (planned / executable / structurally_excluded / per_surface / strata) but
    without looping per job -- the join to ``market_coordinate`` applies the same
    eligibility gate the runner applies per spec (proven equal at Sentinel scale
    in scripts/validate_panel.py). ``planned = executable + structurally_excluded``
    holds by construction.
    """
    if kind not in WAVE_KINDS:
        raise ValueError(f"unknown wave kind {kind!r}; expected one of {WAVE_KINDS}")
    industries, markets = load_scope(conn, kind=kind, methodology_code=methodology_code)
    treatments = load_treatments(conn, methodology_code=methodology_code)
    geometry_code = pilot.resolve_active_geometry(
        conn, methodology_code=methodology_code, surfaces=SURFACES)
    points = pilot.load_geometry_points(conn, geometry_code)

    # One grouped query over industry x (per-industry treatments) x market x
    # (surface via surface_treatment) x the active-grid points, joined to the
    # coordinate eligibility. Each row is one (industry, market, surface) stratum.
    rows = conn.execute(
        """
        select i.industry_code, mk.market_code, s.surface_code,
               count(*) as planned,
               count(*) filter (where mc.eligibility = 'eligible_land') as executable,
               count(*) filter (where mc.eligibility is distinct from 'eligible_land') as excluded
        from manifest.methodology_version mv
        join manifest.industry i on i.industry_code = any(%(industries)s)
        join manifest.treatment t
          on t.methodology_version_id = mv.methodology_version_id
         and t.industry_id = i.industry_id and t.treatment_set_code = %(tset)s
        join manifest.market mk on mk.market_code = any(%(markets)s)
        join manifest.surface s on s.surface_code = any(%(surfaces)s)
        join manifest.surface_treatment st
          on st.methodology_version_id = mv.methodology_version_id
         and st.surface_id = s.surface_id and st.treatment_id = t.treatment_id
        join manifest.geometry_version gv on gv.geometry_code = %(geom)s
        join manifest.geometry_point gp on gp.geometry_version_id = gv.geometry_version_id
        join manifest.market_coordinate mc
          on mc.methodology_version_id = mv.methodology_version_id
         and mc.market_id = mk.market_id and mc.geometry_point_id = gp.geometry_point_id
        where mv.methodology_code = %(mcode)s
        group by i.industry_code, mk.market_code, s.surface_code
        """,
        dict(industries=industries, markets=markets, surfaces=SURFACES,
             tset=TREATMENT_SET, geom=geometry_code, mcode=methodology_code),
    ).fetchall()

    planned = executable = excluded = 0
    per_surface: dict[str, dict[str, int]] = {}
    strata_under_20: dict[str, int] = {}
    n_strata = 0
    for ind, mkt, surf, p, ex, exc in rows:
        planned += p
        executable += ex
        excluded += exc
        ps = per_surface.setdefault(surf, {"planned": 0, "executable": 0, "excluded": 0})
        ps["planned"] += p
        ps["executable"] += ex
        ps["excluded"] += exc
        n_strata += 1
        if ex < STRATUM_MIN_EXECUTABLE:
            strata_under_20[f"{ind}:{mkt}:{surf}"] = ex

    price = _expected_unit_microusd(conn)
    est = {
        "expected_unit_microusd": price,
        "executable_jobs": executable,
        "estimated_cost_microusd": (price * executable) if price is not None else None,
        "estimated_cost_usd": round(price * executable / 1_000_000, 6) if price is not None else None,
    }
    return {
        "kind": kind,
        "methodology_code": methodology_code,
        "scope": {"industries": len(industries), "markets": len(markets),
                  "surfaces": len(SURFACES), "treatments_per_industry": len(treatments),
                  "points": len(points)},
        "planned": planned,
        "executable": executable,
        "structurally_excluded": excluded,
        "per_surface": per_surface,
        "strata": n_strata,
        "strata_under_20": strata_under_20,
        "cost_estimate": est,
    }


def _expected_unit_microusd(conn) -> Optional[int]:
    """Active versioned DataForSEO unit price for a Maps/Organic task (migration 023).

    Scoped to the Maps/Organic SERP economic unit, NOT the single globally-latest
    DataForSEO price: migration 024 seeded the (now-historical, AI-Mode-deferred
    per ADR-0008) AI-Mode price with a later effective_from, so an unscoped
    `order by effective_from desc` would estimate this Maps+Organic panel against
    the AI-Mode rate (2,400 vs 600 uUSD, ~4x). Excluding the ai_mode
    endpoint_or_product family selects the maps+organic price, mirroring the
    wave-scoped selection in pilot._financial_reconciliation. The amount still
    comes from the versioned price registry (never hard-coded).
    """
    row = conn.execute(
        "select pv.unit_amount_microusd from ops.provider_price_version pv "
        "join ops.provider p on p.provider_id=pv.provider_id "
        "where p.provider_code='dataforseo' and pv.effective_from <= now() "
        "and (pv.effective_to is null or pv.effective_to > now()) "
        "and pv.endpoint_or_product not ilike '%ai_mode%' "
        "order by pv.effective_from desc limit 1").fetchone()
    return int(row[0]) if row else None


# ---------------------------------------------------------------------------
# CLI -- dry-run only (no paid path lives here yet)
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Full Panel / Sentinel wave generator + dry-run accounting (Maps + Organic). "
                    "Planning only -- no provider call, no writes.")
    p.add_argument("--kind", required=True, choices=list(WAVE_KINDS))
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--dry-run", action="store_true",
                   help="print the water-gated accounting + cost estimate (default; the only mode)")
    p.add_argument("--execute", action="store_true",
                   help="NOT AVAILABLE yet: live panel collection lands with the Standard decoupled "
                        "DataForSEO adapter (design doc step 2) behind RUN_PAID_PANEL. Refused here.")
    args = p.parse_args(argv)

    if args.execute:
        print(json.dumps({
            "refused": True,
            "reason": "panel execution is not implemented in this module yet; it arrives with the "
                      "Standard decoupled adapter (RUN_PAID_PANEL-gated). This module plans only.",
        }, indent=2))
        return 2

    import psycopg
    from .config import Settings
    settings = Settings()
    with psycopg.connect(settings.db_url()) as conn:
        plan = plan_wave(conn, kind=args.kind, methodology_code=args.methodology)
        conn.rollback()  # planning only
        plan["mode"] = "dry_run"
        plan["note"] = ("planning only; live panel collection is RUN_PAID_PANEL-gated and lands with "
                        "the Standard decoupled adapter. No paid call is made from this module.")
        print(json.dumps(plan, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
