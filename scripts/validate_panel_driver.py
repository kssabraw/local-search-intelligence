#!/usr/bin/env python3
"""OFFLINE validation of the Full Panel / Sentinel cadence driver (step 3).

Applies migrations 001-NNN to an ephemeral pgvector Postgres (the full frozen
Manifest v1.0 universe), then drives `collector.panel_driver.run_panel_cadence`
end to end with a FAKE batch provider and an in-memory raw store -- exercising the
same small real scope validate_panel_run.py uses (IND010 x {MKT008, MKT011} = 208
planned -> 200 executable / 8 excluded). NO paid call, NO network.

Asserts:
  * cadence-anchor decision: on a fresh DB (no full_panel wave this month)
    decide_kind == 'full_panel'; after a full_panel wave exists this month it
    flips to 'sentinel' (the Full-Panel week runs only the Full Panel);
  * deterministic per-period wave codes (FULLPANEL-<YYYYMM>, SENTINEL-<ISO week>);
  * a full run with --kind auto mints the Full Panel wave (panel_subset_id NULL),
    collects 200/200, QA/Wave-Acceptance == COMPLETE;
  * the next --kind auto run resolves to Sentinel (panel_subset_id set), QA
    COMPLETE;
  * idempotent resume: re-running the same period / --resume re-POSTs nothing
    (0 submitted, 200 already_observed) and stays COMPLETE -- no re-pay;
  * the gate: run_panel_cadence never constructs a live client (providers are
    injected); the RUN_PAID_PANEL refusal is covered DB-free in tests/.
"""
from __future__ import annotations
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402
from validate_panel_run import make_factory, _specs, EXECUTABLE, EXCLUDED, PLANNED  # noqa: E402

METH = "MANIFEST_V1_0"


def main() -> int:
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector import panel, panel_driver, pilot
    from collector.repository import utcnow

    pg = LocalPG()
    checks: list[tuple[str, str, str]] = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()
        now = utcnow()

        with psycopg.connect(pg.dsn()) as conn:
            def scalar(sql, params=()):
                return conn.execute(sql, params).fetchone()[0]

            specs = _specs(conn)
            check("scope spec count (pre-water)", len(specs), PLANNED)

            # ---- deterministic per-period wave codes ----
            check("full panel code format", panel_driver.default_wave_code("full_panel", now),
                  f"FULLPANEL-{now:%Y%m}")
            check("sentinel code format", panel_driver.default_wave_code("sentinel", now),
                  f"SENTINEL-{now:%G}W{now:%V}")

            # ---- cadence anchor: fresh DB -> full_panel ----
            check("fresh decide_kind == full_panel",
                  panel_driver.decide_kind(conn, methodology_code=METH, now=now), "full_panel")

            # ---- run 1: --kind auto -> Full Panel (monthly anchor) ----
            out1 = panel_driver.run_panel_cadence(
                conn, batch_provider_factory=make_factory(), raw_store=store,
                kind="auto", methodology_code=METH, now=now, specs=specs,
                poll_interval_s=0, sleep=lambda s: None, persist_evaluation=True)
            print("run 1 (auto->full_panel):", json.dumps(out1["run"], default=str))
            check("run1 resolved kind full_panel", out1["kind"], "full_panel")
            check("run1 wave code is per-period FULLPANEL", out1["wave_code"], f"FULLPANEL-{now:%Y%m}")
            check("run1 executable", out1["run"]["executable"], EXECUTABLE)
            check("run1 submitted", out1["run"]["submitted"], EXECUTABLE)
            check("run1 collected", out1["run"]["collected"], EXECUTABLE)
            check("run1 structurally_excluded", out1["run"]["structurally_excluded"], EXCLUDED)
            check("run1 QA COMPLETE", out1["evaluation"]["status"], "COMPLETE")
            wid1 = out1["wave_id"]
            check("run1 wave kind full_panel", scalar(
                "select wave_kind::text from ops.collection_wave where wave_id=%s", (wid1,)), "full_panel")
            check("run1 full_panel panel_subset_id NULL", scalar(
                "select panel_subset_id is null from ops.collection_wave where wave_id=%s", (wid1,)), True)

            # ---- cadence anchor: after a full_panel wave this month -> sentinel ----
            check("after-FP decide_kind == sentinel",
                  panel_driver.decide_kind(conn, methodology_code=METH, now=now), "sentinel")

            # ---- run 2: --kind auto -> Sentinel ----
            out2 = panel_driver.run_panel_cadence(
                conn, batch_provider_factory=make_factory(), raw_store=store,
                kind="auto", methodology_code=METH, now=now, specs=specs,
                poll_interval_s=0, sleep=lambda s: None, persist_evaluation=True)
            print("run 2 (auto->sentinel):", json.dumps(out2["run"], default=str))
            check("run2 resolved kind sentinel", out2["kind"], "sentinel")
            check("run2 wave code is per-period SENTINEL", out2["wave_code"], f"SENTINEL-{now:%G}W{now:%V}")
            check("run2 collected", out2["run"]["collected"], EXECUTABLE)
            check("run2 QA COMPLETE", out2["evaluation"]["status"], "COMPLETE")
            wid2 = out2["wave_id"]
            check("run2 wave kind sentinel", scalar(
                "select wave_kind::text from ops.collection_wave where wave_id=%s", (wid2,)), "sentinel")
            check("run2 sentinel panel_subset_id set", scalar(
                "select panel_subset_id is not null from ops.collection_wave where wave_id=%s", (wid2,)), True)

            # ---- idempotent resume: same period Sentinel re-POSTs nothing ----
            attempts_before = scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s", (wid2,))
            out3 = panel_driver.run_panel_cadence(
                conn, batch_provider_factory=make_factory(), raw_store=store,
                kind="sentinel", methodology_code=METH, now=now, specs=specs,
                poll_interval_s=0, sleep=lambda s: None, persist_evaluation=False)
            print("run 3 (sentinel resume):", json.dumps(out3["run"], default=str))
            check("resume reuses the same wave", out3["wave_id"], wid2)
            check("resume re-POSTed nothing (0 submitted)", out3["run"]["submitted"], 0)
            check("resume already_observed == executable", out3["run"]["already_observed"], EXECUTABLE)
            check("resume collected nothing", out3["run"]["collected"], 0)
            check("resume created no new attempts", scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s", (wid2,)), attempts_before)
            check("resume still QA COMPLETE", out3["evaluation"]["status"], "COMPLETE")

            # ---- --resume continues the latest wave of the kind ----
            check("latest_wave(sentinel) is the run-2 wave",
                  panel_driver.latest_wave(conn, kind="sentinel", methodology_code=METH),
                  f"SENTINEL-{now:%G}W{now:%V}")

            # persisted evaluations exist (no silent partials -> a row per evaluated wave)
            check("wave_evaluation rows persisted (>=2)", scalar(
                "select count(*) >= 2 from ops.wave_evaluation"), True)

        print(f"\n{'check':<50} {'result':<32} status")
        print("-" * 96)
        failed = 0
        for label, r, status in checks:
            failed += status == "FAIL"
            print(f"{label:<50} {r:<32} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
