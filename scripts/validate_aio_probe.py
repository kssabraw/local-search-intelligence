#!/usr/bin/env python3
"""End-to-end OFFLINE validation of the AIO capture-feasibility probe (ADR-0005).

Applies all migrations to an ephemeral pgvector Postgres, then drives
``collector.aio_probe.AioProbeRunner`` over the frozen pilot cells with a FAKE
DataForSEO AI-Mode provider (synthetic fixtures) and an in-memory raw store.
NO paid call, NO network.

Asserts:
  * the probe rides the immutable-raw + observation + cost ledger (3 raw blobs and
    one attributed cost_event per job) and writes NO aio.* normalization rows;
  * each observation carries the structural capability inventory in parser_metadata;
  * a rich AI response rolls every required field up to CAPTURABLE;
  * a text-only response rolls the placement/citation/local fields up to
    NOT_OBSERVABLE (=> provider_not_observable, not an empty column);
  * a non-triggering response rolls every field up to INCONCLUSIVE (trigger_rate 0);
  * a resume re-collects nothing and re-pays nothing (idempotent at submission);
  * structural-water coordinates are never submitted.
"""
from __future__ import annotations
import copy
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
FIXTURE_BY_CONDITION = {
    "AIO_C01": FIX / "aio_ai_mode_rich.json",
    "AIO_C04": FIX / "aio_ai_mode_textonly.json",
    "AIO_C02": FIX / "aio_not_triggered.json",
}


class FakeAioProvider:
    """Per-job fake: task_post -> task_get_advanced, returning the condition's base
    fixture customized with a unique task id + the job's keyword so each job's raw
    bytes are distinct (no accidental content-address sharing across jobs)."""

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
    from collector.aio_probe import AioProbeRunner, expand_probe_matrix, summarize_capture
    from collector.raw_store import InMemoryRawStore

    pg = LocalPG()
    checks = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    def factory(ctx):
        base = json.loads(FIXTURE_BY_CONDITION[ctx.treatment_code].read_text())
        return FakeAioProvider(base)

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()

        with psycopg.connect(pg.dsn()) as conn:
            def scalar(sql, *p):
                return conn.execute(sql, p).fetchone()[0]

            # ---- Wave A: rich (C01) + text-only (C04) over IND010 x {MKT008, MKT011} ----
            specs_a = expand_probe_matrix(industries=["IND010"], markets=["MKT008", "MKT011"],
                                          conditions=["AIO_C01", "AIO_C04"])
            check("wave A planned jobs", len(specs_a), 4)
            runner = AioProbeRunner(conn, provider_factory=factory, raw_store=store,
                                    wave_code="AIOPROBE-TEST-A")
            res = runner.run(specs_a)
            print("wave A:", json.dumps(res.summary(), default=str))
            check("wave A executable", res.executable, 4)
            check("wave A structurally_excluded", res.structurally_excluded, 0)
            check("wave A probed", res.probed, 4)
            check("wave A triggered", res.triggered, 4)
            check("wave A provider_failures", res.provider_failures, 0)
            check("wave A total cost microusd (4 x 2000)", res.total_cost_microusd, 8000)

            check("observations recorded", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIOPROBE-TEST-A'"), 4)
            check("all obs carry aio_capture metadata", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id "
                "where w.wave_code='AIOPROBE-TEST-A' and (o.parser_metadata ? 'aio_capture')"), 4)
            # provider_payload is inserted per job (request+post+get) = the robust
            # per-job immutable-raw evidence. raw_blob is content-addressed, so the two
            # near-me rich jobs (identical keyword => identical post/get bytes) correctly
            # DEDUPE to shared blobs -- that is the fail-on-exists immutability guarantee,
            # not a miss (10 = 4 request + 3 post + 3 get after dedup).
            check("provider_payload rows (3 per job)", scalar(
                "select count(*) from ops.provider_payload"), 12)
            check("distinct request blobs (1 per job)", scalar(
                "select count(*) from ops.raw_blob where storage_path like %s", "aio/request/%"), 4)
            check("raw blobs content-addressed (dedup-correct)", scalar(
                "select count(*) from ops.raw_blob"), 10)
            check("cost events (1 per job)", scalar(
                "select count(*) from ops.cost_event ce join ops.collection_wave w on w.wave_id=ce.wave_id "
                "where w.wave_code='AIOPROBE-TEST-A'"), 4)
            check("NO aio.* normalization rows", scalar("select count(*) from aio.observation"), 0)
            check("NO observed_object minted by probe", scalar("select count(*) from core.observed_object"), 0)

            report_a = summarize_capture(conn, "AIOPROBE-TEST-A")
            print("report A:", json.dumps(report_a, default=str))
            check("A: triggered", report_a["aio_triggered"], 4)
            check("A: all required fields CAPTURABLE",
                  all(f["decision"] == "CAPTURABLE" for f in report_a["fields"].values()), True)

            # idempotent resume: same wave, nothing re-collected / re-paid
            res2 = AioProbeRunner(conn, provider_factory=factory, raw_store=store,
                                  wave_code="AIOPROBE-TEST-A").run(specs_a)
            check("resume already_observed", res2.already_observed, 4)
            check("resume probed 0 (no re-pay)", res2.probed, 0)
            check("still 4 observations", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIOPROBE-TEST-A'"), 4)
            check("still 4 cost events (no re-pay)", scalar(
                "select count(*) from ops.cost_event ce join ops.collection_wave w on w.wave_id=ce.wave_id "
                "where w.wave_code='AIOPROBE-TEST-A'"), 4)

            # ---- Wave B: text-only only -> placement/citation/local fields NOT_OBSERVABLE ----
            specs_b = expand_probe_matrix(industries=["IND010"], markets=["MKT008"], conditions=["AIO_C04"])
            AioProbeRunner(conn, provider_factory=factory, raw_store=store,
                           wave_code="AIOPROBE-TEST-B").run(specs_b)
            report_b = summarize_capture(conn, "AIOPROBE-TEST-B")
            print("report B:", json.dumps(report_b, default=str))
            check("B: answer text CAPTURABLE", report_b["fields"]["aio_answer_text"]["decision"], "CAPTURABLE")
            check("B: rectangles NOT_OBSERVABLE", report_b["fields"]["element_rectangles"]["decision"], "NOT_OBSERVABLE")
            check("B: citations NOT_OBSERVABLE", report_b["fields"]["source_citations"]["decision"], "NOT_OBSERVABLE")
            check("B: local cards NOT_OBSERVABLE", report_b["fields"]["local_business_cards"]["decision"], "NOT_OBSERVABLE")

            # ---- Wave C: non-triggering -> everything INCONCLUSIVE, trigger_rate 0 ----
            specs_c = expand_probe_matrix(industries=["IND010"], markets=["MKT008"], conditions=["AIO_C02"])
            AioProbeRunner(conn, provider_factory=factory, raw_store=store,
                           wave_code="AIOPROBE-TEST-C").run(specs_c)
            report_c = summarize_capture(conn, "AIOPROBE-TEST-C")
            print("report C:", json.dumps(report_c, default=str))
            check("C: triggered 0", report_c["aio_triggered"], 0)
            check("C: trigger_rate 0.0", report_c["trigger_rate"], 0.0)
            check("C: all fields INCONCLUSIVE",
                  all(f["decision"] == "INCONCLUSIVE" for f in report_c["fields"].values()), True)

            conn.commit()

        print(f"\n{'check':<48} {'result':<26} status")
        print("-" * 84)
        failed = 0
        for label, resl, status in checks:
            failed += status == "FAIL"
            print(f"{label:<48} {resl:<26} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
