#!/usr/bin/env python3
"""End-to-end OFFLINE validation of the AIO collection driver (ADR-0008, Stage 2).

Applies migrations 001-025 to an ephemeral pgvector Postgres, then drives
``collector.aio_driver.run_aio_collection`` over a small AIO scope with a FAKE
DataForSEO provider and an in-memory raw store. NO paid call, NO network.

Asserts:
  * a clean AIO wave normalizes both tracks (aio.* + co-returned organic context)
    and evaluates QA/Wave-Acceptance v0.1 = COMPLETE (the aio surface is recognized
    by the normalization-parity evaluator);
  * a CONCURRENT run (workers>1, cell-partitioned) with the SAME cross-cell business
    KG-MID in every cell mints exactly ONE business_location entity — 0 KG-MID
    identifier split — and a clean web-entity graph (0 duplicate domains/URLs);
  * an idempotent resume re-collects nothing / re-pays nothing;
  * the water gate: a structural-water AIO coordinate is recorded blocked_structural
    and NEVER submitted;
  * the RUN_PAID_AIO gate refuses a paid --execute run when closed, DB-free.
"""
from __future__ import annotations
import copy
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
LOADED = FIX / "aio_overview_organic_loaded.json"


class FakeAioProvider:
    """task_post -> task_get_advanced returning the loaded organic-AIO fixture with a
    unique task id + the job's keyword (distinct raw bytes per job). The fixture's
    single SearchViewer business (KG-MID /g/1q62g1d9q) recurs in EVERY cell — the
    cross-cell business the KG-MID lock must resolve to one entity."""

    def __init__(self, base: dict):
        self._base = base
        self._tid = None
        self._kw = None

    def task_post(self, payload):
        self._kw = payload["keyword"]
        self._tid = "aio-" + hashlib.sha256(self._kw.encode()).hexdigest()[:12]
        post = {"status_code": 20000, "tasks": [{"id": self._tid, "status_code": 20100}]}
        return post, json.dumps(post).encode(), self._tid

    def task_get_advanced(self, task_id):
        assert task_id == self._tid
        resp = copy.deepcopy(self._base)
        resp["tasks"][0]["id"] = task_id
        if resp["tasks"][0].get("result"):
            resp["tasks"][0]["result"][0]["keyword"] = self._kw
        return resp, json.dumps(resp, sort_keys=True).encode()


def main() -> int:
    import psycopg
    from collector import aio_driver, aio_run
    from collector.pilot import PILOT_MARKETS, PilotJobSpec
    from collector.raw_store import InMemoryRawStore

    pg = LocalPG()
    checks = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    base = json.loads(LOADED.read_text())

    def provider_factory(ctx):
        return FakeAioProvider(base)

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()
        db_url = pg.dsn()

        def conn_factory():
            return psycopg.connect(db_url)

        with psycopg.connect(db_url) as conn:
            def scalar(sql, *p):
                return conn.execute(sql, p).fetchone()[0]

            # ---- gate refusal (DB-free path in main; here assert the predicate) ----
            os.environ.pop(aio_driver.RUN_PAID_AIO_ENV, None)
            check("gate closed by default", aio_driver._gate_open(), False)
            os.environ[aio_driver.RUN_PAID_AIO_ENV] = "1"
            check("gate opens with RUN_PAID_AIO=1", aio_driver._gate_open(), True)
            os.environ.pop(aio_driver.RUN_PAID_AIO_ENV, None)

            # ---- Case 1: clean graduated wave (single worker) -> QA COMPLETE ----
            specs1 = aio_run.expand_aio_matrix(industries=["IND010"], markets=["MKT008", "MKT011"])
            check("graduated 1-industry x 2-market x 2-cond scope", len(specs1), 4)
            out1 = aio_driver.run_aio_collection(
                conn, provider_factory=provider_factory, raw_store=store,
                wave_code="AIO-RUN-CLEAN", specs=specs1, persist_evaluation=True)
            print("clean:", json.dumps(out1["run"], default=str))
            check("clean run executable", out1["run"]["executable"], 4)
            check("clean run collected", out1["run"]["collected"], 4)
            check("clean run valid_returned", out1["run"]["valid_returned"], 4)
            check("clean QA status COMPLETE", out1["evaluation"]["status"], "COMPLETE")
            check("aio norm parity 1.0", out1["evaluation"]["metrics"][
                "normalization_parity_rate_each_surface"].get("aio"), 1.0)
            check("aio observations written", scalar(
                "select count(*) from aio.observation a join ops.observation o on o.observation_id=a.observation_id "
                "join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='AIO-RUN-CLEAN'"), 4)
            check("all triggered (loaded fixture)", scalar(
                "select count(*) from aio.observation a join ops.observation o on o.observation_id=a.observation_id "
                "join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='AIO-RUN-CLEAN' and a.aio_triggered"), 4)
            check("wave_evaluation persisted COMPLETE", scalar(
                "select status::text from ops.wave_evaluation we join ops.collection_wave w on w.wave_id=we.wave_id "
                "where w.wave_code='AIO-RUN-CLEAN'"), "complete")

            # idempotent resume: nothing re-collected / re-paid
            cost_before = scalar("select count(*) from ops.cost_event")
            out1b = aio_driver.run_aio_collection(
                conn, provider_factory=provider_factory, raw_store=store,
                wave_code="AIO-RUN-CLEAN", specs=specs1, persist_evaluation=False)
            check("resume already_observed all", out1b["run"]["already_observed"], 4)
            check("resume collected 0 (no re-pay)", out1b["run"]["collected"], 0)
            check("resume added no cost events", scalar("select count(*) from ops.cost_event"), cost_before)

            # ---- Case 2: CONCURRENT run, same cross-cell KG-MID in every cell ----
            # 3 industries x 5 markets = 15 cells (groups); 2 conditions each = 30 jobs.
            specs2 = aio_run.expand_aio_matrix()
            check("full graduated scope (3x5x2)", len(specs2), 30)
            out2 = aio_driver.run_aio_collection(
                conn, provider_factory=provider_factory, raw_store=store,
                wave_code="AIO-RUN-CONC", specs=specs2, workers=5,
                conn_factory=conn_factory, persist_evaluation=False)
            print("concurrent:", json.dumps(out2["run"], default=str))
            check("concurrent collected 30", out2["run"]["collected"], 30)
            check("concurrent worker_faults 0", out2["run"]["worker_faults"], 0)
            check("concurrent QA COMPLETE", out2["evaluation"]["status"], "COMPLETE")
            # THE KG-MID split test: one business_location entity for the shared MID.
            check("KG-MID business_location entities == 1 (no split)", scalar(
                "select count(*) from core.entity where entity_type_code='business_location'"), 1)
            check("KG-MID external_identifier == 1", scalar(
                "select count(*) from core.external_identifier where identifier_type='google_kg_mid'"), 1)
            check("KG-MID resolves to ONE entity (0 identifier split)", scalar(
                "select count(distinct entity_id) from core.external_identifier_assertion eia "
                "join core.external_identifier ei on ei.external_identifier_id=eia.external_identifier_id "
                "where ei.identifier_type='google_kg_mid'"), 1)
            check("0 duplicate web_domain (concurrent)", scalar(
                "select count(*) from (select normalized_domain from core.web_domain group by 1 having count(*)>1) t"), 0)
            check("0 duplicate web_url (concurrent)", scalar(
                "select count(*) from (select normalized_url from core.web_url group by 1 having count(*)>1) t"), 0)
            # 30 business appearances (one per observation) but one entity
            check("30 business_appearances across the wave", scalar(
                "select count(*) from aio.business_appearance ba join ops.observation o on o.observation_id=ba.observation_id "
                "join ops.collection_job j on j.job_id=o.job_id join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='AIO-RUN-CONC'"), 30)

            # ---- Case 3: water gate — a structural-water AIO coordinate is never submitted ----
            water = conn.execute(
                "select mk.market_code, gp.point_code "
                "from manifest.market_coordinate mc "
                "join manifest.market mk on mk.market_id=mc.market_id "
                "join manifest.geometry_point gp on gp.geometry_point_id=mc.geometry_point_id "
                "join manifest.geometry_version gv on gv.geometry_version_id=gp.geometry_version_id "
                "where gv.geometry_code='AIO9_V1' and mc.eligibility <> 'eligible_land' "
                "and mk.market_code = any(%s) limit 1", (PILOT_MARKETS,)).fetchone()
            if water:
                wmarket, wpoint = water
                wspec = [PilotJobSpec("aio", "IND010", wmarket, "AIO_C01", wpoint)]
                outw = aio_driver.run_aio_collection(
                    conn, provider_factory=provider_factory, raw_store=store,
                    wave_code="AIO-RUN-WATER", specs=wspec, persist_evaluation=False)
                check(f"water coord {wmarket}:{wpoint} structurally_excluded",
                      outw["run"]["structurally_excluded"], 1)
                check("water coord not executed (0 executable)", outw["run"]["executable"], 0)
                check("water coord: no observation submitted", scalar(
                    "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                    "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-RUN-WATER'"), 0)
            else:
                check("water coord present among pilot AIO9 points", "none found", "at least one")

        print(f"\n{'check':<52} {'result':<28} status")
        print("-" * 92)
        failed = 0
        for label, resl, status in checks:
            failed += status == "FAIL"
            print(f"{label:<52} {resl:<28} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
