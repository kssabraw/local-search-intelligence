#!/usr/bin/env python3
"""End-to-end OFFLINE validation of the Stage-1 3x5 pilot batch run harness.

Applies migrations 001-NNN to an ephemeral pgvector Postgres, then drives the
FULL frozen pilot matrix (3 industries x 5 markets x 4 queries x 13 points x 2
surfaces = 1,560 pre-water jobs) through `collector.pilot.PilotRunner` with FAKE
providers (the captured Maps/Organic fixtures) and an in-memory raw store. NO
paid call, NO network.

Asserts:
  * water-gate accounting: planned 1,560 -> executable 1,368 / structurally
    excluded 192 (57 eligible coordinates x 3 industries x 4 queries x 2 surfaces);
  * every executable job collected a returned observation; excluded coordinates
    produced NO observation and NO cost (missing != zero, COL008);
  * a full re-run is idempotent (no new observations, no paid call);
  * QA/Wave-Acceptance v0.1 evaluation of the clean wave == COMPLETE with every
    gate at 1.0, and the ops.wave_evaluation row persists;
  * a wave whose provider fails (provider_failure fixture) is accounted (job
    accounting 1.0) but downgraded to FAILED (valid-observation rate collapses),
    proving technical failure != scientific absence and != integrity violation.
"""
from __future__ import annotations
import copy
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

MAPS_FIXTURE = ROOT / "tests" / "fixtures" / "maps_advanced_sample.json"
ORGANIC_FIXTURE = ROOT / "tests" / "fixtures" / "organic_advanced_sample.json"

# Expected water-gate accounting for the pilot markets (MAPORG13 geometry),
# computed independently from manifest/SED_Coordinates_GeoEligible_v1_0.csv:
#   MKT008=12, MKT011=13, MKT021=9, MKT040=13, MKT049=10  -> 57 eligible coords.
EXPECTED_PLANNED = 1560
EXPECTED_EXECUTABLE = 57 * 3 * 4 * 2      # eligible coords x industries x queries x surfaces = 1368
EXPECTED_EXCLUDED = EXPECTED_PLANNED - EXPECTED_EXECUTABLE  # 192


class FakeProvider:
    """Returns a captured fixture verbatim; never touches the network."""

    def __init__(self, advanced_bytes: bytes, *, force_status: int | None = None):
        self._advanced = json.loads(advanced_bytes)
        if force_status is not None:
            self._advanced = copy.deepcopy(self._advanced)
            self._advanced["tasks"][0]["status_code"] = force_status
            self._advanced["tasks"][0]["result"] = None
        self._advanced_bytes = json.dumps(self._advanced).encode()
        self._task_id = self._advanced["tasks"][0]["id"]

    def task_post(self, payload):
        post = {"status_code": 20000, "tasks": [{"id": self._task_id, "status_code": 20000}]}
        return post, json.dumps(post).encode(), self._task_id

    def task_get_advanced(self, task_id):
        return self._advanced, self._advanced_bytes


def make_factory(force_status: int | None = None):
    maps_bytes = MAPS_FIXTURE.read_bytes()
    org_bytes = ORGANIC_FIXTURE.read_bytes()

    def factory(ctx):
        raw = org_bytes if ctx.surface_code == "organic" else maps_bytes
        return FakeProvider(raw, force_status=force_status)

    return factory


class CellFakeProvider:
    """Maps provider whose place_ids/cids are made unique per (industry, market)
    cell — mirroring reality, where a place_id is a single physical business local
    to one metro. This lets the concurrency test assert Maps entity correctness
    under (industry, market, surface) partitioning."""

    def __init__(self, advanced_bytes: bytes, cell_key: str):
        adv = json.loads(advanced_bytes)
        for res in adv["tasks"][0].get("result") or []:
            for it in res.get("items") or []:
                if it.get("place_id"):
                    it["place_id"] = f"{it['place_id']}-{cell_key}"
                if it.get("cid") is not None:
                    it["cid"] = f"{it['cid']}-{cell_key}"
        self._advanced = adv
        self._advanced_bytes = json.dumps(adv).encode()
        self._task_id = adv["tasks"][0]["id"]

    def task_post(self, payload):
        post = {"status_code": 20000, "tasks": [{"id": self._task_id, "status_code": 20000}]}
        return post, json.dumps(post).encode(), self._task_id

    def task_get_advanced(self, task_id):
        return self._advanced, self._advanced_bytes


def make_cell_factory():
    """Maps: per-cell distinct place_ids (as in production). Organic: the fixture's
    web domains/urls verbatim, so EVERY organic cell creates the SAME domains/urls
    concurrently — the exact cross-worker race the repository layer must survive."""
    maps_bytes = MAPS_FIXTURE.read_bytes()
    org_bytes = ORGANIC_FIXTURE.read_bytes()

    def factory(ctx):
        if ctx.surface_code == "organic":
            return FakeProvider(org_bytes)
        return CellFakeProvider(maps_bytes, f"{ctx.industry_id}:{ctx.market_id}")

    return factory


class RaisingProvider:
    """task_post succeeds (task created + raw stored) but task_get raises a
    ProviderError — mimicking a DataForSEO poll-timeout / stuck task, the exact
    shape of the production pilot's 7 organic failures."""

    def __init__(self, message: str):
        self._message = message

    def task_post(self, payload):
        post = {"status_code": 20000, "tasks": [{"id": "raise-task", "status_code": 20100}]}
        return post, json.dumps(post).encode(), "raise-task"

    def task_get_advanced(self, task_id):
        from collector.dataforseo import ProviderError
        raise ProviderError(self._message)


def make_error_factory():
    """Organic at MKT040 raises a ProviderError (poll-timeout shape); everything
    else collects normally."""
    maps_bytes = MAPS_FIXTURE.read_bytes()
    org_bytes = ORGANIC_FIXTURE.read_bytes()

    def factory(ctx):
        if ctx.surface_code == "organic" and "MKT040" in ctx.coordinate_code:
            return RaisingProvider(
                "task raise-task not ready within 300.0s (last provider status 40602: Task In Queue)")
        if ctx.surface_code == "organic":
            return FakeProvider(org_bytes)
        return CellFakeProvider(maps_bytes, f"{ctx.industry_id}:{ctx.market_id}")

    return factory


def error_capture_phase(check) -> None:
    """Fresh DB: a pocket of organic jobs (MKT040) hit a ProviderError. Prove the
    run COMPLETES (never aborts), records accounted terminal_failures with the
    provider error captured in job_event.details, and evaluates to FAILED with a
    reconciled job-accounting rate — the exact production incident, handled."""
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector import pilot

    pg = LocalPG()
    try:
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()
        db = pg.dsn()

        def conn_factory():
            return psycopg.connect(db)

        # Two fully-eligible markets: MKT040 (organic fails) + MKT011 (clean contrast).
        specs = pilot.expand_matrix(markets=["MKT040", "MKT011"])
        expected_exec = 12 * 52  # 3 ind x 2 mkt x 2 surf groups, 4 queries x 13 pts each
        mkt040_organic = 3 * 52  # 3 industries x (4 queries x 13 points)
        with psycopg.connect(db) as conn:
            runner = pilot.PilotRunner(conn, provider_factory=make_error_factory(), raw_store=store,
                                       wave_code="PILOT-ERRCAP", max_workers=4,
                                       conn_factory=conn_factory, sleep=lambda s: None)
            runner.setup()
            res = runner.run(specs)  # MUST NOT raise despite 156 provider errors
            report = pilot.evaluate_wave(conn, "PILOT-ERRCAP", persist=True)
            print("errcap run:", json.dumps(res.summary(), default=str))

            def scalar(sql):
                return conn.execute(sql).fetchone()[0]

            check("[errcap] run completed without aborting", res.executable, expected_exec)
            check("[errcap] no worker faults (job errors handled in-band)", res.worker_faults, 0)
            check("[errcap] technical_failures == MKT040 organic", res.technical_failures, mkt040_organic)
            check("[errcap] terminal_failure events for MKT040 organic", scalar(
                "select count(*) from ops.job_event e join ops.collection_job j on j.job_id=e.job_id "
                "join manifest.market mk on mk.market_id=j.market_id "
                "join manifest.surface s on s.surface_id=j.surface_id "
                "where e.status='terminal_failure' and mk.market_code='MKT040' and s.surface_code='organic'"),
                mkt040_organic)
            check("[errcap] provider error message captured in details", scalar(
                "select count(*) from ops.job_event e where e.status='terminal_failure' "
                "and e.details->>'error_message' like '%not ready within%'") >= mkt040_organic, True)
            check("[errcap] job_accounting_rate == 1.0 (all accounted)",
                  report["metrics"]["job_accounting_rate"], 1.0)
            check("[errcap] status FAILED", report["status"], "FAILED")
            check("[errcap] no integrity violation (technical loss, not quarantine)",
                  len(report["integrity_violations"]), 0)
            check("[errcap] Maps unaffected (100%)",
                  report["metrics"]["valid_scientific_observation_rate_each_primary_surface"]["maps"], 1.0)
    finally:
        pg.stop()


def concurrency_phase(check) -> None:
    """Fresh DB: run the FULL 1,368-job matrix with parallel workers and prove no
    duplicate entities are created under concurrent resolution (the crux of safe
    parallelism). Runs on its own ephemeral cluster so the shared web domains/urls
    are created for the first time BY the concurrent workers."""
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector import pilot

    pg = LocalPG()
    try:
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()
        db = pg.dsn()

        def conn_factory():
            return psycopg.connect(db)

        specs = pilot.expand_matrix()
        with psycopg.connect(db) as conn:
            runner = pilot.PilotRunner(conn, provider_factory=make_cell_factory(), raw_store=store,
                                       wave_code="PILOT-CONC", max_workers=8,
                                       conn_factory=conn_factory, sleep=lambda s: None)
            runner.setup()
            res = runner.run(specs)
            report = pilot.evaluate_wave(conn, "PILOT-CONC", persist=True)
            print("concurrent run:", json.dumps(res.summary(), default=str))

            def scalar(sql):
                return conn.execute(sql).fetchone()[0]

            check("[conc] executable (8 workers)", res.executable, EXPECTED_EXECUTABLE)
            check("[conc] structurally_excluded", res.structurally_excluded, EXPECTED_EXCLUDED)
            check("[conc] collected", res.collected, EXPECTED_EXECUTABLE)
            check("[conc] valid_returned", res.valid_returned, EXPECTED_EXECUTABLE)
            check("[conc] technical_failures", res.technical_failures, 0)
            check("[conc] observations (one per exec job)",
                  scalar("select count(*) from ops.observation"), EXPECTED_EXECUTABLE)
            check("[conc] QA status COMPLETE", report["status"], "COMPLETE")
            check("[conc] QA no integrity violations", len(report["integrity_violations"]), 0)
            # THE CRUX: no external identifier (place_id / web domain / web url) is
            # ever bound to more than one entity, even under concurrent creation.
            check("[conc] NO identifier split across entities", scalar(
                "select count(*) from (select external_identifier_id from core.external_identifier_assertion "
                "where resolution_state='resolved' group by external_identifier_id "
                "having count(distinct entity_id)>1) x"), 0)
            # Shared web domains/urls: every organic cell created the same set
            # concurrently, yet they dedupe to exactly the fixture's 2 + 2.
            check("[conc] web_domain deduped to 2", scalar("select count(*) from core.web_domain"), 2)
            check("[conc] web_url deduped to 2", scalar("select count(*) from core.web_url"), 2)
            check("[conc] no duplicate normalized_domain",
                  scalar("select count(*)-count(distinct normalized_domain) from core.web_domain"), 0)
            check("[conc] no duplicate normalized_url",
                  scalar("select count(*)-count(distinct normalized_url) from core.web_url"), 0)
            # Per-cell Maps place_ids: 15 (industry x market) cells x 2 businesses.
            check("[conc] business_location per-cell (15x2=30)",
                  scalar("select count(*) from core.business_location"), 30)
            check("[conc] no duplicate place_id identifier",
                  scalar("select count(*)-count(distinct identifier_value) from core.external_identifier "
                         "where identifier_type='place_id'"), 0)
    finally:
        pg.stop()


def main() -> int:
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector import pilot

    pg = LocalPG()
    checks: list[tuple[str, str, str]] = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")

        store = InMemoryRawStore()
        with psycopg.connect(pg.dsn()) as conn:
            def scalar(sql, params=()):
                return conn.execute(sql, params).fetchone()[0]

            # ---- dry-run planning (no writes, no calls) ----
            specs = pilot.expand_matrix()
            check("matrix size (pre-water)", len(specs), EXPECTED_PLANNED)
            plan = pilot.plan_dry_run(conn, specs)
            check("dry-run planned", plan["planned"], EXPECTED_PLANNED)
            check("dry-run executable", plan["executable"], EXPECTED_EXECUTABLE)
            check("dry-run structurally_excluded", plan["structurally_excluded"], EXPECTED_EXCLUDED)
            check("dry-run conformity failures", len(plan["conformity_failures"]), 0)
            check("dry-run wrote nothing (no jobs)", scalar("select count(*) from ops.collection_job"), 0)
            check("every stratum >= 20 executable jobs", len(plan["strata_under_20"]), 0)

            # ---- full clean pilot run ----
            runner = pilot.PilotRunner(conn, provider_factory=make_factory(), raw_store=store,
                                       wave_code="PILOT-VALIDATE", sleep=lambda s: None)
            runner.setup()
            res = runner.run(specs)
            print("run:", json.dumps(res.summary(), default=str))
            check("run planned", res.planned, EXPECTED_PLANNED)
            check("run executable", res.executable, EXPECTED_EXECUTABLE)
            check("run structurally_excluded", res.structurally_excluded, EXPECTED_EXCLUDED)
            check("run collected", res.collected, EXPECTED_EXECUTABLE)
            check("run valid_returned", res.valid_returned, EXPECTED_EXECUTABLE)
            check("run technical_failures", res.technical_failures, 0)

            # DB accounting
            check("collection_job rows (all planned)",
                  scalar("select count(*) from ops.collection_job"), EXPECTED_PLANNED)
            check("executable jobs (eligible_land)",
                  scalar("select count(*) from ops.collection_job where planned_eligibility='eligible_land'"),
                  EXPECTED_EXECUTABLE)
            check("blocked_structural events",
                  scalar("select count(*) from ops.job_event where status='blocked_structural'"),
                  EXPECTED_EXCLUDED)
            check("observations (one per executable job)",
                  scalar("select count(*) from ops.observation"), EXPECTED_EXECUTABLE)
            check("NO observation on an excluded coordinate",
                  scalar("select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                         "where j.planned_eligibility is distinct from 'eligible_land'"), 0)
            check("cost events (one per executable job)",
                  scalar("select count(*) from ops.cost_event"), EXPECTED_EXECUTABLE)
            check("NO cost on an excluded coordinate",
                  scalar("select count(*) from ops.cost_event c join ops.collection_job j on j.job_id=c.job_id "
                         "where j.planned_eligibility is distinct from 'eligible_land'"), 0)

            # ---- idempotent full re-run (same wave) ----
            runner2 = pilot.PilotRunner(conn, provider_factory=make_factory(), raw_store=store,
                                        wave_code="PILOT-VALIDATE", sleep=lambda s: None)
            res2 = runner2.run(specs)
            check("re-run all already_observed", res2.already_observed, EXPECTED_EXECUTABLE)
            check("re-run collected nothing new", res2.collected, 0)
            check("still one observation per executable job",
                  scalar("select count(*) from ops.observation"), EXPECTED_EXECUTABLE)

            # ---- QA / Wave-Acceptance v0.1 evaluation (clean wave) ----
            report = pilot.evaluate_wave(conn, "PILOT-VALIDATE", persist=True)
            conn.commit()
            print("evaluation:", json.dumps(report, default=str)[:1200])
            m = report["metrics"]
            check("QA status", report["status"], "COMPLETE")
            check("QA denominators.executable", report["denominators"]["executable"], EXPECTED_EXECUTABLE)
            check("QA denominators.structurally_excluded",
                  report["denominators"]["structurally_excluded"], EXPECTED_EXCLUDED)
            check("QA job_accounting_rate", m["job_accounting_rate"], 1.0)
            check("QA valid_scientific_observation_rate_overall",
                  m["valid_scientific_observation_rate_overall"], 1.0)
            check("QA raw_payload_integrity_rate", m["raw_payload_integrity_rate"], 1.0)
            check("QA critical_manifest_conformity_rate", m["critical_manifest_conformity_rate"], 1.0)
            check("QA normalization_parity_rate_overall", m["normalization_parity_rate_overall"], 1.0)
            check("QA resolution_state_coverage_rate", m["resolution_state_coverage_rate"], 1.0)
            check("QA no integrity violations", len(report["integrity_violations"]), 0)
            check("QA per-surface both present", sorted(report["per_surface"].keys()), ["maps", "organic"])
            check("QA denominators.failed_jobs (clean wave)", report["denominators"]["failed_jobs"], 0)
            check("QA denominators.quarantined_jobs (clean wave)", report["denominators"]["quarantined_jobs"], 0)
            check("wave_evaluation row persisted (complete)",
                  scalar("select count(*) from ops.wave_evaluation where status='complete'"), 1)
            check("wave_evaluation.failed_jobs persisted", scalar(
                "select failed_jobs from ops.wave_evaluation where status='complete'"), 0)

            # financial reconciliation resolves from PENDING now that migration 023
            # seeds a versioned price; coverage is full (every billed job has a cost row).
            fin = report["financial_reconciliation"]
            check("financial coverage == 1.0", fin["provider_cost_event_coverage"], 1.0)
            check("financial baseline present (drift computed)", fin["unit_price_drift"], "computed")
            check("financial not PENDING (baseline resolved)", fin["state"] != "PENDING", True)
            check("financial billed_jobs == executable", fin["billed_jobs"], EXPECTED_EXECUTABLE)
            check("financial expected_unit seeded (600 uUSD)", fin["expected_unit_microusd"], 600)

            # ---- downgrade scenario: provider_failure wave -> FAILED (not QUARANTINED) ----
            fail_specs = pilot.expand_matrix(industries=["IND010"], markets=["MKT011"], surfaces=["maps"])
            frunner = pilot.PilotRunner(conn, provider_factory=make_factory(force_status=40501),
                                        raw_store=store, wave_code="PILOT-FAIL", sleep=lambda s: None)
            frunner.setup()
            fres = frunner.run(fail_specs)
            freport = pilot.evaluate_wave(conn, "PILOT-FAIL", persist=False)
            print("fail-wave:", json.dumps({"run": fres.summary(), "status": freport["status"],
                                            "valid_rate": freport["metrics"]["valid_scientific_observation_rate_overall"],
                                            "job_accounting": freport["metrics"]["job_accounting_rate"]}, default=str))
            # MKT011 has 13 eligible MAPORG points x 4 queries = 52 executable maps jobs, all provider_failure.
            check("fail-wave executable", fres.executable, 52)
            check("fail-wave has observations (accounted)",
                  scalar("select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                         "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='PILOT-FAIL'"), 52)
            check("fail-wave job_accounting_rate == 1.0",
                  freport["metrics"]["job_accounting_rate"], 1.0)
            check("fail-wave valid rate == 0.0",
                  freport["metrics"]["valid_scientific_observation_rate_overall"], 0.0)
            check("fail-wave status FAILED (technical loss, integrity intact)",
                  freport["status"], "FAILED")
            check("fail-wave NO integrity violation (not quarantined)",
                  len(freport["integrity_violations"]), 0)
            # telemetry: all 52 executable jobs failed to yield a valid observation.
            check("fail-wave failed_jobs == 52", freport["denominators"]["failed_jobs"], 52)
            check("fail-wave quarantined_jobs == 0", freport["denominators"]["quarantined_jobs"], 0)

            # ---- resume-latest: reuse the newest pilot wave, re-collect nothing ----
            rspecs = pilot.expand_matrix(industries=["IND022"], markets=["MKT040"], surfaces=["organic"])
            rrunner = pilot.PilotRunner(conn, provider_factory=make_factory(), raw_store=store,
                                        wave_code="PILOT-RESUME-SRC", sleep=lambda s: None)
            rrunner.setup()
            rrunner.run(rspecs)
            obs_after_first = scalar("select count(*) from ops.observation")
            # latest_pilot_wave must resolve to the wave just created (newest).
            resolved = pilot.latest_pilot_wave(conn, "MANIFEST_V1_0")
            check("latest_pilot_wave resolves newest wave", resolved, "PILOT-RESUME-SRC")
            resumed = pilot.PilotRunner(conn, provider_factory=make_factory(), raw_store=store,
                                        wave_code=resolved, sleep=lambda s: None)
            rres = resumed.run(rspecs)
            check("resume re-collected nothing (all already_observed)", rres.collected, 0)
            check("resume all already_observed", rres.already_observed, rres.executable)
            check("resume created no new observations",
                  scalar("select count(*) from ops.observation"), obs_after_first)

        # ---- concurrency phase (own fresh cluster): no duplicate entities ----
        print("\n[concurrency] fresh cluster: full matrix x 8 workers ...")
        concurrency_phase(check)

        # ---- error-capture phase (own fresh cluster): provider errors handled ----
        print("\n[error-capture] fresh cluster: a pocket of organic ProviderErrors ...")
        error_capture_phase(check)

        print(f"\n{'check':<52} {'result':<26} status")
        print("-" * 92)
        failed = 0
        for label, r, status in checks:
            failed += status == "FAIL"
            print(f"{label:<52} {r:<26} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
