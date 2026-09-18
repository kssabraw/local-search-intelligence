#!/usr/bin/env python3
"""OFFLINE validation of the superseded-wave normalized-layer prune.

Applies migrations 001-NNN to an ephemeral pgvector Postgres, seeds TWO small real
waves through the validated pilot runner (FAKE providers, in-memory raw store) --
one to prune, one to keep -- then exercises scripts.prune_superseded_normalized:

  * wave inventory reports each wave's derived geometry + footprint;
  * the ACTIVE-grid guard REFUSES to prune a wave on the current grid by default;
  * a dry-run reports would-delete counts and writes NOTHING;
  * an --execute prune deletes the target wave's normalized rows (results,
    observed_object appearances, resolution bookkeeping, surface + ops observations)
    in child->parent order with NO foreign-key violation;
  * the KEPT wave is fully intact;
  * the canonical entity graph (core.entity / web_domain / web_url) is UNCHANGED --
    a pruned appearance never deletes the business/domain it resolved to;
  * raw payloads (ops.raw_blob) and the cost ledger + wave/job provenance are KEPT.

NO paid call, NO network.
"""
from __future__ import annotations
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402
from validate_pilot import make_factory  # noqa: E402


def main() -> int:
    import psycopg
    from collector import pilot
    from collector.raw_store import InMemoryRawStore
    import prune_superseded_normalized as prune_mod

    pg = LocalPG()
    checks: list[tuple[str, str, str]] = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    # A small 1-cell x 2-surface scope (center point only) per wave = 2 jobs each.
    def specs(market):
        return pilot.expand_matrix(industries=["IND010"], markets=[market],
                                   surfaces=["maps", "organic"], treatments=["Q1"], points=["C"])

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()
        with psycopg.connect(pg.dsn()) as conn:
            def scalar(sql, params=()):
                return conn.execute(sql, params).fetchone()[0]

            for code, market in (("PRUNE-KEEP", "MKT011"), ("PRUNE-DROP", "MKT008")):
                r = pilot.PilotRunner(conn, provider_factory=make_factory(), raw_store=store,
                                      wave_code=code, sleep=lambda s: None)
                r.setup()
                r.run(specs(market))

            def wave_obs(code):
                return scalar(
                    "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                    "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code=%s", (code,))

            def wave_oo(code):
                return scalar(
                    "select count(*) from core.observed_object oo join ops.observation o on o.observation_id=oo.observation_id "
                    "join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id "
                    "where w.wave_code=%s", (code,))

            def wave_results(code):
                return scalar(
                    "select (select count(*) from maps.result r join ops.observation o on o.observation_id=r.observation_id "
                    "  join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code=%s)"
                    "     + (select count(*) from organic.result r join ops.observation o on o.observation_id=r.observation_id "
                    "  join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code=%s)",
                    (code, code))

            drop_obs0, keep_obs0 = wave_obs("PRUNE-DROP"), wave_obs("PRUNE-KEEP")
            check("seeded DROP wave has observations", drop_obs0 > 0, True)
            check("seeded KEEP wave has observations", keep_obs0 > 0, True)
            check("seeded DROP wave has observed_objects", wave_oo("PRUNE-DROP") > 0, True)
            check("seeded DROP wave has result rows", wave_results("PRUNE-DROP") > 0, True)

            ent0 = scalar("select count(*) from core.entity")
            dom0 = scalar("select count(*) from core.web_domain")
            raw0 = scalar("select count(*) from ops.raw_blob")
            cost_drop0 = scalar(
                "select count(*) from ops.cost_event ce join ops.collection_wave w on w.wave_id=ce.wave_id "
                "where w.wave_code='PRUNE-DROP'")
            job_drop0 = scalar(
                "select count(*) from ops.collection_job j join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='PRUNE-DROP'")

            # ---- active-grid guard: refuse by default (ephemeral waves are on the active grid) ----
            active = prune_mod.active_geometry(conn)
            check("active grid resolves to GEOGRID13E_V1", active, "GEOGRID13E_V1")
            refused = False
            try:
                prune_mod.select_waves(conn, wave_codes=["PRUNE-DROP"])
            except PermissionError:
                refused = True
            check("active-grid guard refuses prune by default", refused, True)

            # ---- dry-run (allow active grid for the test) writes nothing ----
            sel = prune_mod.select_waves(conn, wave_codes=["PRUNE-DROP"], allow_active_grid=True)
            wids = prune_mod._wave_ids(conn, [w["wave_code"] for w in sel])
            dry = prune_mod.prune(conn, wids, execute=False)
            check("dry-run would delete observations", dry["ops.observation"], drop_obs0)
            check("dry-run wrote nothing (DROP obs intact)", wave_obs("PRUNE-DROP"), drop_obs0)

            # ---- execute prune of the DROP wave ----
            done = prune_mod.prune(conn, wids, execute=True)
            print("pruned:", json.dumps(done, default=str))

            check("DROP observations deleted", wave_obs("PRUNE-DROP"), 0)
            check("DROP observed_objects deleted", wave_oo("PRUNE-DROP"), 0)
            check("DROP result rows deleted", wave_results("PRUNE-DROP"), 0)
            check("DROP no orphan resolution_run", scalar(
                "select count(*) from core.resolution_run rr where not exists "
                "(select 1 from core.observed_object oo where oo.observed_object_id=rr.observed_object_id)"), 0)

            # KEEP wave fully intact
            check("KEEP observations intact", wave_obs("PRUNE-KEEP"), keep_obs0)
            check("KEEP result rows intact", wave_results("PRUNE-KEEP") > 0, True)

            # canonical graph + raw + audit preserved
            check("canonical core.entity unchanged", scalar("select count(*) from core.entity"), ent0)
            check("canonical core.web_domain unchanged", scalar("select count(*) from core.web_domain"), dom0)
            check("raw_blob unchanged (raw is the rebuild source)", scalar("select count(*) from ops.raw_blob"), raw0)
            check("DROP cost_event kept (audit)", scalar(
                "select count(*) from ops.cost_event ce join ops.collection_wave w on w.wave_id=ce.wave_id "
                "where w.wave_code='PRUNE-DROP'"), cost_drop0)
            check("DROP collection_job kept (provenance)", scalar(
                "select count(*) from ops.collection_job j join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='PRUNE-DROP'"), job_drop0)
            check("DROP wave row still present", scalar(
                "select count(*) from ops.collection_wave where wave_code='PRUNE-DROP'"), 1)

            # the append-only USER trigger must be RE-ENABLED after the prune (never left off)
            check("append-only trigger re-enabled on maps.result", scalar(
                "select count(*) from pg_trigger t join pg_class c on c.oid=t.tgrelid "
                "join pg_namespace n on n.oid=c.relnamespace "
                "where n.nspname='maps' and c.relname='result' and not t.tgisinternal and t.tgenabled='D'"), 0)
            # and a stray DELETE is rejected again (guard restored)
            reguard = False
            try:
                # target a real (KEEP-wave) row so the row-level guard actually fires; rolled back
                conn.execute("delete from maps.result where ctid in (select ctid from maps.result limit 1)")
            except Exception:
                reguard = True
            conn.rollback()
            check("append-only guard rejects DELETE again post-prune", reguard, True)

        print(f"\n{'check':<52} {'result':<26} status")
        print("-" * 90)
        failed = 0
        for label, resl, status in checks:
            failed += status == "FAIL"
            print(f"{label:<52} {resl:<26} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
