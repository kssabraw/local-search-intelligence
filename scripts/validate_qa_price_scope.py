#!/usr/bin/env python3
"""OFFLINE validation that the QA financial reconciliation scopes the expected unit
price to a wave's OWN provider profiles (fixes the AI-Mode price shadowing the
Maps/Organic 600 µUSD baseline). Applies migrations 001-025 to ephemeral pgvector,
mints tiny waves whose jobs use different provider profiles, and asserts each wave's
`expected_unit_microusd`. NO paid call, NO network.

  * Maps wave (DFS_MAPS_V2, /maps endpoint)               -> 600 (SERP standard)
  * Organic wave (DFS_ORGANIC_V1, /organic endpoint)      -> 600 (SERP standard)
  * AIO-organic wave (DFS_AIO_V2, /organic ai_overview)   -> 600 (organic base, NOT 2400)
  * AI-Mode wave (DFS_AIO_V1, /ai_mode endpoint; history) -> 2400 (AI-Mode rate)

Before the fix every wave read 2400 (migration 024's later-dated AI-Mode price).
"""
from __future__ import annotations
import dataclasses
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402


def main() -> int:
    import psycopg
    from collector.pilot import _financial_reconciliation
    from collector.repository import Repo, utcnow
    from collector.spike import build_request

    pg = LocalPG()
    checks = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")

        with psycopg.connect(pg.dsn()) as conn:
            repo = Repo(conn)
            now = utcnow()

            def profile_id(profile_code):
                return conn.execute(
                    "select provider_profile_id from manifest.provider_profile where profile_code=%s",
                    (profile_code,)).fetchone()[0]

            def mint_wave(wave_code, *, surface, treatment_set, treatment,
                          profile_override=None):
                ctx = repo.load_manifest_context(
                    methodology_code="MANIFEST_V1_0", surface_code=surface,
                    industry_code="IND010", market_code="MKT008", point_code="C",
                    treatment_set_code=treatment_set, treatment_code=treatment)
                if profile_override:
                    ctx = dataclasses.replace(ctx, provider_profile_id=profile_id(profile_override))
                wave_id = repo.get_or_create_wave(
                    methodology_version_id=ctx.methodology_version_id, wave_code=wave_code,
                    wave_kind="validation", scheduled_for=now)
                req = build_request(ctx)
                repo.plan_job(ctx=ctx, wave_id=wave_id, replicate_no=1,
                              rendered_input_text=req["keyword"], rendered_request=req,
                              generated_by=None)
                conn.commit()
                return _financial_reconciliation(conn, wave_id)

            fin_maps = mint_wave("PRICE-MAPS", surface="maps",
                                 treatment_set="GOOGLE_QUERY_V1", treatment="Q1")
            check("maps wave expected_unit == 600", fin_maps["expected_unit_microusd"], 600)

            fin_org = mint_wave("PRICE-ORG", surface="organic",
                                treatment_set="GOOGLE_QUERY_V1", treatment="Q1")
            check("organic wave expected_unit == 600", fin_org["expected_unit_microusd"], 600)

            fin_aio = mint_wave("PRICE-AIO", surface="aio",
                                treatment_set="AIO_QUERY_V1", treatment="AIO_C01")
            check("AIO-organic wave (DFS_AIO_V2) expected_unit == 600 (NOT 2400)",
                  fin_aio["expected_unit_microusd"], 600)

            fin_aimode = mint_wave("PRICE-AIMODE", surface="aio",
                                   treatment_set="AIO_QUERY_V1", treatment="AIO_C01",
                                   profile_override="DFS_AIO_V1")
            check("AI-Mode wave (DFS_AIO_V1, history) expected_unit == 2400",
                  fin_aimode["expected_unit_microusd"], 2400)

            # both prices are seeded + active; the fix is the SCOPING, not retiring one
            check("both DataForSEO prices active", conn.execute(
                "select count(*) from ops.provider_price_version pv join ops.provider p "
                "on p.provider_id=pv.provider_id where p.provider_code='dataforseo' "
                "and (pv.effective_to is null or pv.effective_to > now())").fetchone()[0], 2)

        print(f"\n{'check':<56} {'result':<24} status")
        print("-" * 90)
        failed = 0
        for label, resl, status in checks:
            failed += status == "FAIL"
            print(f"{label:<56} {resl:<24} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
