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
            check("wave_evaluation row persisted (complete)",
                  scalar("select count(*) from ops.wave_evaluation where status='complete'"), 1)

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
