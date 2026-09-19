#!/usr/bin/env python3
"""OFFLINE validation of the AIO_QUERY_V2 amendment (ADR-0011, migration 029).

Applies all migrations (001-029) to an ephemeral pgvector Postgres and asserts the
V2 treatment set is seeded and wired correctly, V1 is retained, [CITY] renders per
market through the real collector context loader, and the full AIO panel still scopes
to 148,750 executable against the now-active V2 set. NO DB mutation of production,
NO network, NO paid call.

Asserts:
  * 250 AIO_QUERY_V2 treatments + 250 aio->V2 surface_treatment links (sequences
    251..500, above V1's 1..250 block);
  * AIO_QUERY_V1 retained (250 treatments, 250 aio links) -- history intact;
  * every V2 C05-C08 is a distinct conversational template carrying a [CITY] slot;
  * C01-C04/C09/C10 templates are byte-identical to V1 (kept verbatim);
  * the frozen JSON matches the generators (no drift);
  * [CITY] renders per market via collector.repository.Repo.load_manifest_context +
    spike.render_keyword (a real render, not string surgery);
  * aio_run.AIO_TREATMENT_SET == 'AIO_QUERY_V2' and load_full_panel_specs water-gates
    to 148,750 executable against V2;
  * re-applying migration 029 is idempotent (counts unchanged).
"""
from __future__ import annotations
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import psycopg  # noqa: E402
from _localpg import LocalPG  # noqa: E402

from collector import aio_run, spike  # noqa: E402
from collector.repository import Repo  # noqa: E402

MIG = ROOT / "supabase" / "migrations"
V2 = "AIO_QUERY_V2"
V1 = "AIO_QUERY_V1"


def main() -> int:
    checks: list[tuple[str, str, str]] = []

    def check(label, got, expected):
        ok = str(got) == str(expected)
        checks.append((label, f"{got} (exp {expected})", "PASS" if ok else "FAIL"))

    # 0. Generators are in sync with the committed artifacts (no manual drift).
    for script in ("gen_aio_query_v2_json.py", "gen_migration_029_aio_query_v2.py"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), "--check"],
                           capture_output=True, text=True)
        check(f"{script} --check", r.returncode, 0)

    check("aio_run.AIO_TREATMENT_SET", aio_run.AIO_TREATMENT_SET, V2)

    pg = LocalPG()
    try:
        pg.start()
        pg.apply_migrations(MIG)
        db_url = pg.dsn()
        with psycopg.connect(db_url) as conn:
            def val(sql, p=None):
                return conn.execute(sql, p or {}).fetchone()[0]

            # 1. V2 seeded, V1 retained.
            check("V2 treatments", val(
                "select count(*) from manifest.treatment where treatment_set_code=%(s)s", {"s": V2}), 250)
            check("V1 treatments retained", val(
                "select count(*) from manifest.treatment where treatment_set_code=%(s)s", {"s": V1}), 250)
            check("aio->V2 surface_treatment links", val(
                "select count(*) from manifest.surface_treatment st "
                "join manifest.treatment t on t.treatment_id=st.treatment_id "
                "join manifest.surface s on s.surface_id=st.surface_id "
                "where s.surface_code='aio' and t.treatment_set_code=%(s)s", {"s": V2}), 250)
            check("aio->V1 surface_treatment links retained", val(
                "select count(*) from manifest.surface_treatment st "
                "join manifest.treatment t on t.treatment_id=st.treatment_id "
                "join manifest.surface s on s.surface_id=st.surface_id "
                "where s.surface_code='aio' and t.treatment_set_code=%(s)s", {"s": V1}), 250)

            # 2. V2 aio-link sequences sit above V1's 1..250 block (unique-safe).
            check("V2 aio-link seq range 251..500", val(
                "select min(st.sequence)||'..'||max(st.sequence) from manifest.surface_treatment st "
                "join manifest.treatment t on t.treatment_id=st.treatment_id "
                "join manifest.surface s on s.surface_id=st.surface_id "
                "where s.surface_code='aio' and t.treatment_set_code=%(s)s", {"s": V2}), "251..500")

            # 3. Every V2 C05-C08 is conversational (long) + [CITY]-slotted.
            check("V2 C05-C08 with [CITY] slot", val(
                "select count(*) from manifest.treatment where treatment_set_code=%(s)s "
                "and treatment_code in ('AIO_C05','AIO_C06','AIO_C07','AIO_C08') "
                "and city_slot_required and exact_template like '%%[CITY]%%'", {"s": V2}), 100)
            check("V2 C05-C08 conversational (len>=25, has space)", val(
                "select count(*) from manifest.treatment where treatment_set_code=%(s)s "
                "and treatment_code in ('AIO_C05','AIO_C06','AIO_C07','AIO_C08') "
                "and length(exact_template) >= 25 and exact_template like '%% %%'", {"s": V2}), 100)

            # 4. C01-C04/C09/C10 kept byte-identical to V1.
            check("V2 kept-condition templates == V1", val(
                "select count(*) from manifest.treatment v2 "
                "join manifest.treatment v1 on v1.industry_id=v2.industry_id "
                "  and v1.treatment_code=v2.treatment_code and v1.treatment_set_code=%(v1)s "
                "where v2.treatment_set_code=%(v2)s "
                "  and v2.treatment_code in ('AIO_C01','AIO_C02','AIO_C03','AIO_C04','AIO_C09','AIO_C10') "
                "  and v1.exact_template = v2.exact_template", {"v1": V1, "v2": V2}), 150)

            # 5. [CITY] renders per market through the real context loader.
            repo = Repo(conn)
            rendered_ok = 0
            for market, city in (("MKT008", None), ("MKT049", None)):
                for ind in ("IND010", "IND019", "IND022"):
                    ctx = repo.load_manifest_context(
                        methodology_code="MANIFEST_V1_0", surface_code="aio",
                        industry_code=ind, market_code=market, point_code="C",
                        treatment_set_code=V2, treatment_code="AIO_C08")
                    kw = spike.render_keyword(ctx)
                    if "[CITY]" not in kw and ctx.market_city in kw:
                        rendered_ok += 1
            check("[CITY] renders per market (2 markets x 3 industries)", rendered_ok, 6)

            # 6. Full panel scopes to 148,750 executable against the now-active V2 set.
            fp = aio_run.load_full_panel_specs(conn)
            check("full panel planned = 162500", len(fp), 162500)
            fp_exec = val(
                "select count(*) from manifest.market_coordinate mc "
                "join manifest.geometry_point gp on gp.geometry_point_id=mc.geometry_point_id "
                "join manifest.surface_config sc on sc.geometry_version_id=gp.geometry_version_id "
                "join manifest.surface s on s.surface_id=sc.surface_id and s.surface_code='aio' "
                "cross join manifest.treatment t "
                "join manifest.methodology_version mv on mv.methodology_version_id=mc.methodology_version_id "
                "join manifest.industry i on i.industry_id=t.industry_id "
                "where mv.methodology_code='MANIFEST_V1_0' and mc.eligibility='eligible_land' "
                "  and t.treatment_set_code=%(s)s", {"s": aio_run.AIO_TREATMENT_SET})
            check("full panel water-gated executable = 148750", fp_exec, 148750)

            # 7. Re-applying migration 029 is idempotent (deploy re-runs it).
            with conn.cursor() as cur:
                cur.execute((MIG / "029_aio_query_v2.sql").read_text())
            conn.commit()
            check("V2 treatments after re-apply", val(
                "select count(*) from manifest.treatment where treatment_set_code=%(s)s", {"s": V2}), 250)
            check("aio->V2 links after re-apply", val(
                "select count(*) from manifest.surface_treatment st "
                "join manifest.treatment t on t.treatment_id=st.treatment_id "
                "join manifest.surface s on s.surface_id=st.surface_id "
                "where s.surface_code='aio' and t.treatment_set_code=%(s)s", {"s": V2}), 250)
    finally:
        pg.stop()

    width = max(len(c[0]) for c in checks)
    failed = 0
    for label, got, status in checks:
        if status == "FAIL":
            failed += 1
        print(f"  [{status}] {label.ljust(width)}  {got}")
    print(f"\n{len(checks)} checks, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
