#!/usr/bin/env python3
"""End-to-end offline validation of the vertical-slice spike against the REAL schema.

Applies migrations 001-021 to an ephemeral pgvector Postgres, seeds included, then
runs collector.spike.run_spike for one eligible pilot coordinate
(IND010 Locksmith x MKT008 Vancouver WA, point C, maps/Q1) with a FAKE provider
(the captured Maps fixture) and an in-memory raw store. NO paid call, NO network.

Asserts the full path landed: immutable raw, one returned observation, 2 maps
results + observed objects, 2 place_id resolutions, 2 canonical entities, 1 cost
event; and that a second run is idempotent (no duplicate observation / paid call).
"""
from __future__ import annotations
import json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "maps_advanced_sample.json"


class FakeMapsProvider:
    """Returns the captured fixture; never touches the network (no paid call)."""

    def __init__(self, advanced_bytes: bytes):
        self._advanced_bytes = advanced_bytes
        self._advanced = json.loads(advanced_bytes)
        self._task_id = self._advanced["tasks"][0]["id"]

    def task_post(self, payload):
        post = {"status_code": 20000, "tasks": [{"id": self._task_id, "status_code": 20000}]}
        return post, json.dumps(post).encode(), self._task_id

    def task_get_advanced(self, task_id):
        assert task_id == self._task_id
        return self._advanced, self._advanced_bytes


def main() -> int:
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector.repository import Repo
    from collector.spike import run_spike

    pg = LocalPG()
    checks = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")

        provider = FakeMapsProvider(FIXTURE.read_bytes())
        store = InMemoryRawStore()

        with psycopg.connect(pg.dsn()) as conn:
            repo = Repo(conn)
            ctx = repo.load_manifest_context(
                methodology_code="MANIFEST_V1_0", surface_code="maps",
                industry_code="IND010", market_code="MKT008", point_code="C",
                treatment_set_code="GOOGLE_QUERY_V1", treatment_code="Q1")
            check("coordinate eligible_land", ctx.eligibility, "eligible_land")

            result = run_spike(conn, ctx=ctx, provider=provider, raw_store=store, wave_code="SPIKE-TEST")
            conn.commit()
            print("run 1:", json.dumps(result, default=str))
            check("status", result["status"], "collected")
            check("observation_state", result["observation_state"], "returned")
            check("returned_result_count", result["returned_result_count"], 2)
            check("resolved entities", result["resolved"], 2)

            def scalar(sql):
                return conn.execute(sql).fetchone()[0]

            check("raw_blob rows (request+post+get)", scalar("select count(*) from ops.raw_blob"), 3)
            check("provider_payload rows", scalar("select count(*) from ops.provider_payload"), 3)
            check("collection_job rows", scalar("select count(*) from ops.collection_job"), 1)
            check("observation rows", scalar("select count(*) from ops.observation"), 1)
            check("maps.observation rows", scalar("select count(*) from maps.observation"), 1)
            check("maps.result rows", scalar("select count(*) from maps.result"), 2)
            check("observed_object rows", scalar("select count(*) from core.observed_object"), 2)
            check("resolution_assertion resolved",
                  scalar("select count(*) from core.resolution_assertion where resolution_state='resolved'"), 2)
            check("canonical entities (business_location)",
                  scalar("select count(*) from core.entity where entity_type_code='business_location'"), 2)
            check("external_identifier place_id",
                  scalar("select count(*) from core.external_identifier where identifier_type='place_id'"), 2)
            check("cost_event rows", scalar("select count(*) from ops.cost_event"), 1)
            check("cost amount_microusd", scalar("select amount_microusd from ops.cost_event"), 2000)
            check("job_event succeeded present",
                  scalar("select count(*) from ops.job_event where status='succeeded'"), 1)

            # idempotency: a second run must NOT create a new observation or re-call the provider
            result2 = run_spike(conn, ctx=ctx, provider=provider, raw_store=store, wave_code="SPIKE-TEST")
            conn.commit()
            print("run 2:", json.dumps(result2, default=str))
            check("second run idempotent", result2["status"], "already_observed")
            check("still one observation", scalar("select count(*) from ops.observation"), 1)

        print(f"\n{'check':<44} {'result':<22} status")
        print("-" * 80)
        failed = 0
        for label, res, status in checks:
            failed += status == "FAIL"
            print(f"{label:<44} {res:<22} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
