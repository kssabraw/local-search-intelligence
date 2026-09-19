#!/usr/bin/env python3
"""End-to-end OFFLINE validation of the AIO collection driver (ADR-0008, Stage 2).

Applies all migrations to an ephemeral pgvector Postgres, then drives
``collector.aio_driver.run_aio_collection`` (now the DECOUPLED two-phase
``AioPanelRunner``) over a small AIO scope with a FAKE batch DataForSEO provider and
an in-memory raw store. NO paid call, NO network.

Asserts:
  * a clean AIO wave submits (batch task_post) then collects, normalizes both tracks
    (aio.* + co-returned organic context), and evaluates QA/Wave-Acceptance v0.1 =
    COMPLETE (the aio surface is recognized by the normalization-parity evaluator);
  * the FULL PANEL scope resolves the frozen 25x50 x 10-condition x 13-point matrix
    (162,500 planned) and the water gate yields 148,750 executable;
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


class FakeAioBatchProvider:
    """DECOUPLED fake for the AioPanelRunner: batch ``task_post_batch`` assigns a
    unique task id per payload (remembering task_id -> keyword), and
    ``task_get_advanced`` returns the loaded organic-AIO fixture with that job's
    keyword substituted (distinct raw bytes per job). The fixture's single
    SearchViewer business (KG-MID /g/1q62g1d9q) recurs in EVERY cell — the
    cross-cell business the KG-MID lock must resolve to ONE entity. One instance is
    shared per surface across every collect worker (and across a resume run), so its
    task_id->keyword map is thread-safe and survives resume."""

    def __init__(self, base: dict):
        import threading
        self._base = base
        self._kw: dict[str, str] = {}
        self._n = 0
        self._lock = threading.Lock()

    def task_post_batch(self, payloads):
        ids = []
        with self._lock:
            for pl in payloads:
                self._n += 1
                tid = f"aio-task-{self._n}"
                self._kw[tid] = pl["keyword"]
                ids.append(tid)
        post = {"status_code": 20000, "tasks": [{"id": t, "status_code": 20100} for t in ids]}
        return post, json.dumps(post).encode(), ids

    def task_get_advanced(self, task_id):
        with self._lock:
            kw = self._kw.get(task_id, "locksmith near me")
        resp = copy.deepcopy(self._base)
        resp["tasks"][0]["id"] = task_id
        if resp["tasks"][0].get("result"):
            resp["tasks"][0]["result"][0]["keyword"] = kw
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

    # One persistent per-surface fake, shared across submit + every collect worker +
    # a resume run (mirrors the production single-provider-per-surface use, and keeps
    # the decoupled task_id->keyword roster coherent across workers).
    shared_provider = FakeAioBatchProvider(base)

    def provider_factory(ctx):
        return shared_provider

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
            check("clean run submitted (decoupled batch post)", out1["run"]["submitted"], 4)
            check("clean run collected", out1["run"]["collected"], 4)
            check("clean run valid_returned", out1["run"]["valid_returned"], 4)
            check("clean run 0 collect_timeouts", out1["run"]["collect_timeouts"], 0)
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
            check("concurrent collect_faults 0", out2["run"]["collect_faults"], 0)
            check("concurrent collect_timeouts 0", out2["run"]["collect_timeouts"], 0)
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
            # Resolve a structural-water coordinate from the AIO surface's CURRENT
            # geometry via surface_config — i.e. the SAME geometry run_aio_collection
            # resolves each job against. Deriving it (rather than hardcoding a
            # geometry_code) keeps this check correct across geometry repoints — e.g.
            # the ADR-0009 / migration 026 unification AIO9_V1 -> GEOGRID13E_V1 — so it
            # can never silently test a point the AIO surface no longer collects.
            water = conn.execute(
                "select mk.market_code, gp.point_code "
                "from manifest.surface_config sc "
                "join manifest.methodology_version mv on mv.methodology_version_id=sc.methodology_version_id "
                "  and mv.methodology_code='MANIFEST_V1_0' "
                "join manifest.surface s on s.surface_id=sc.surface_id and s.surface_code='aio' "
                "join manifest.geometry_point gp on gp.geometry_version_id=sc.geometry_version_id "
                "join manifest.market_coordinate mc on mc.geometry_point_id=gp.geometry_point_id "
                "  and mc.methodology_version_id=sc.methodology_version_id "
                "join manifest.market mk on mk.market_id=mc.market_id "
                "where mc.eligibility <> 'eligible_land' and mk.market_code = any(%s) "
                "order by mk.market_code, gp.point_code limit 1", (PILOT_MARKETS,)).fetchone()
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
                check("water coord present in the AIO surface geometry", "none found", "at least one")

            # ---- Case 4: FULL PANEL scope (planned matrix + water-gated executable) ----
            # No collection — just prove the full-panel scope selection resolves the
            # frozen 25x50 universe x all 10 conditions x the active AIO 13-point grid,
            # and that the water gate yields the documented 148,750 executable.
            fp = aio_run.load_full_panel_specs(conn)
            check("full panel planned = 25x50x10x13 = 162500", len(fp), 162500)
            check("full panel distinct industries = 25", len({s.industry for s in fp}), 25)
            check("full panel distinct markets = 50", len({s.market for s in fp}), 50)
            check("full panel distinct conditions = 10", len({s.treatment for s in fp}), 10)
            check("full panel distinct points = 13", len({s.point for s in fp}), 13)
            # Water-gated executable, computed set-based (same gate the runner applies
            # per job) — must equal the documented full AIO panel size.
            fp_exec = scalar(
                "select count(*) "
                "from manifest.methodology_version mv "
                "join manifest.industry i on true "
                "join manifest.treatment t on t.methodology_version_id=mv.methodology_version_id "
                "  and t.industry_id=i.industry_id and t.treatment_set_code=%s "
                "join manifest.market mk on true "
                "join manifest.surface s on s.surface_code='aio' "
                "join manifest.surface_treatment st on st.methodology_version_id=mv.methodology_version_id "
                "  and st.surface_id=s.surface_id and st.treatment_id=t.treatment_id "
                "join manifest.surface_config sc on sc.methodology_version_id=mv.methodology_version_id "
                "  and sc.surface_id=s.surface_id "
                "join manifest.geometry_point gp on gp.geometry_version_id=sc.geometry_version_id "
                "join manifest.market_coordinate mc on mc.methodology_version_id=mv.methodology_version_id "
                "  and mc.market_id=mk.market_id and mc.geometry_point_id=gp.geometry_point_id "
                "  and mc.eligibility='eligible_land' "
                "where mv.methodology_code='MANIFEST_V1_0'", aio_run.AIO_TREATMENT_SET)
            check("full panel water-gated executable = 148750", fp_exec, 148750)

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
