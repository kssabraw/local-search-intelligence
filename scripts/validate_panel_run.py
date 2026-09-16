#!/usr/bin/env python3
"""OFFLINE validation of the two-phase decoupled panel runner (step 2).

Applies migrations 001-NNN to an ephemeral pgvector Postgres, then drives
`collector.panel_run.PanelRunner` (batched submit -> ready-roster collect ->
reconcile) with a FAKE batch provider and an in-memory raw store. NO paid call,
NO network.

Scope kept small but real: IND010 x {MKT008, MKT011} x Q1-Q4 x 13 points x
{maps, organic}. MKT008 has 12 eligible MAPORG coords, MKT011 has 13 -> 25
eligible x 4 queries x 2 surfaces = 200 executable, + 8 structurally excluded
(1 water coord x 4 x 2), 208 planned. maps and organic are each exactly one full
100-task batch.

Asserts:
  * clean run: 208 planned -> 200 executable / 8 excluded; 200 submitted, 200
    collected, 200 valid; one observation + one cost per executable job; NO
    observation/cost on an excluded coordinate; wave is kind='sentinel' with its
    panel_subset_id set; QA/Wave-Acceptance == COMPLETE (all gates 1.0);
  * one paid task per job: exactly 200 attempts, each with a provider_task_id;
  * idempotent resume: a run that only SUBMITS (no collect), then a second run on
    the same wave, re-POSTs NOTHING (0 new attempts), resumes the outstanding
    tasks (200 resumed_pending, 0 submitted), and collects them -> 200
    observations, QA COMPLETE;
  * reconcile: tasks that never become ready are recorded as accounted
    terminal_failures (collect_timeout), QA FAILED (technical loss) not
    QUARANTINED (integrity intact).
"""
from __future__ import annotations
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

MAPS_FIXTURE = ROOT / "tests" / "fixtures" / "maps_advanced_sample.json"
ORGANIC_FIXTURE = ROOT / "tests" / "fixtures" / "organic_advanced_sample.json"

EXECUTABLE = 200
EXCLUDED = 8
PLANNED = 208


class FakeBatchProvider:
    """A per-surface decoupled provider that never touches the network.

    Submission assigns a unique task id per payload and marks it outstanding;
    tasks_ready returns the outstanding roster; task_get returns the surface
    fixture and clears the task. `ready=False` models tasks that never become
    ready (the reconcile / collect-timeout path)."""

    def __init__(self, surface: str, advanced_bytes: bytes, *, ready: bool = True,
                 roster_empty: bool = False):
        import threading
        self.surface = surface
        self._advanced = json.loads(advanced_bytes)
        self._advanced_bytes = json.dumps(self._advanced).encode()
        self._ready = ready
        # roster_empty models DataForSEO's tasks_ready roster having AGED OUT the
        # completed tasks (as it does within hours) while task_get-by-id still works
        # for ~30 days -- the exact resume-after-delay condition that stalled the live
        # Full Panel. The collector must not depend on the roster.
        self._roster_empty = roster_empty
        self._outstanding: set[str] = set()
        self._n = 0
        # A single per-surface fake is shared by every collect worker on that surface,
        # so its mutable roster must be thread-safe under the concurrent collect path.
        self._lock = threading.Lock()

    def task_post_batch(self, payloads):
        ids = []
        with self._lock:
            for _ in payloads:
                self._n += 1
                tid = f"{self.surface}-task-{self._n}"
                self._outstanding.add(tid)
                ids.append(tid)
        post = {"status_code": 20000, "tasks": [{"id": t, "status_code": 20100} for t in ids]}
        return post, json.dumps(post).encode(), ids

    def tasks_ready(self):
        with self._lock:
            ready = [] if (self._roster_empty or not self._ready) else sorted(self._outstanding)
        data = {"status_code": 20000, "tasks": [{"result": [{"id": t} for t in ready]}]}
        return data, json.dumps(data).encode(), ready

    def task_get_advanced(self, task_id):
        # Direct fetch by task id. ready=False models a task that never becomes ready
        # within the provider poll window (task_get raises), driving the reconcile /
        # collect_timeout path -- now roster-independent, since the collector fetches
        # by stored id instead of the tasks_ready roster.
        if not self._ready:
            from collector.dataforseo import ProviderError
            raise ProviderError(f"task {task_id} not ready (fake)")
        with self._lock:
            self._outstanding.discard(task_id)
        return self._advanced, self._advanced_bytes


def make_factory(*, ready: bool = True, roster_empty: bool = False):
    """One PERSISTENT fake per surface, shared across runs (so a resume run sees
    the tasks a prior run submitted)."""
    maps_bytes = MAPS_FIXTURE.read_bytes()
    org_bytes = ORGANIC_FIXTURE.read_bytes()
    cache: dict[str, FakeBatchProvider] = {}

    def factory(ctx):
        s = ctx.surface_code
        if s not in cache:
            cache[s] = FakeBatchProvider(s, org_bytes if s == "organic" else maps_bytes,
                                         ready=ready, roster_empty=roster_empty)
        return cache[s]

    return factory


def _specs(conn):
    from collector import panel, pilot
    return pilot.expand_matrix(
        industries=["IND010"], markets=["MKT008", "MKT011"], surfaces=panel.SURFACES,
        treatments=panel.load_treatments(conn, methodology_code="MANIFEST_V1_0"),
        points=panel.load_points(conn))


def main() -> int:
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector import panel_run, pilot

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

            specs = _specs(conn)
            check("scope spec count (pre-water)", len(specs), PLANNED)

            # ---- concurrent clean run FIRST (fresh entity graph, so it exercises
            #      parallel web-entity CREATION + the ordered per-domain pre-lock) ----
            def conn_factory():
                return psycopg.connect(pg.dsn())

            crun = panel_run.PanelRunner(
                conn, batch_provider_factory=make_factory(), raw_store=store,
                kind="sentinel", wave_code="PANEL-CONCURRENT", poll_interval_s=0,
                sleep=lambda s: None, max_workers=4, conn_factory=conn_factory)
            cres = crun.run(specs)
            print("concurrent run:", json.dumps(cres.summary(), default=str))
            check("concurrent collected", cres.collected, EXECUTABLE)
            check("concurrent valid_returned", cres.valid_returned, EXECUTABLE)
            check("concurrent collect_timeouts", cres.collect_timeouts, 0)
            check("concurrent collect_faults", cres.collect_faults, 0)
            cwid = scalar("select wave_id from ops.collection_wave where wave_code='PANEL-CONCURRENT'")
            check("concurrent observations (one per executable)", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "where j.wave_id=%s", (cwid,)), EXECUTABLE)
            check("concurrent cost events (one per executable)", scalar(
                "select count(*) from ops.cost_event where wave_id=%s", (cwid,)), EXECUTABLE)
            check("concurrent distinct provider_task_ids == executable", scalar(
                "select count(distinct a.provider_task_id) from ops.collection_attempt a "
                "join ops.collection_job j on j.job_id=a.job_id where j.wave_id=%s", (cwid,)), EXECUTABLE)
            # Entity-graph integrity under parallel creation: the UNIQUE indexes +
            # ordered per-domain pre-lock must yield exactly one canonical entity per
            # normalized domain / url (no identifier split, no duplicate).
            check("concurrent: no duplicate web_domain", scalar(
                "select count(*) - count(distinct normalized_domain) from core.web_domain"), 0)
            check("concurrent: no duplicate web_url", scalar(
                "select count(*) - count(distinct normalized_url) from core.web_url"), 0)
            check("concurrent QA COMPLETE", pilot.evaluate_wave(conn, "PANEL-CONCURRENT")["status"], "COMPLETE")

            # ---- roster-aged resume: tasks_ready returns EMPTY (completed tasks aged
            #      off the roster) but task_get-by-id still works. This is the exact
            #      condition that stalled the live Full Panel. Direct fetch must still
            #      collect everything (both sequential and concurrent). ----
            rag = panel_run.PanelRunner(
                conn, batch_provider_factory=make_factory(roster_empty=True), raw_store=store,
                kind="sentinel", wave_code="PANEL-ROSTER-AGED", poll_interval_s=0,
                sleep=lambda s: None, max_workers=4, conn_factory=conn_factory)
            ragres = rag.run(specs)
            print("roster-aged run:", json.dumps(ragres.summary(), default=str))
            check("roster-aged collected despite empty tasks_ready", ragres.collected, EXECUTABLE)
            check("roster-aged collect_timeouts", ragres.collect_timeouts, 0)
            check("roster-aged collect_faults", ragres.collect_faults, 0)
            check("roster-aged QA COMPLETE", pilot.evaluate_wave(conn, "PANEL-ROSTER-AGED")["status"], "COMPLETE")

            # ---- clean run: submit + collect ----
            runner = panel_run.PanelRunner(
                conn, batch_provider_factory=make_factory(), raw_store=store,
                kind="sentinel", wave_code="PANEL-CLEAN", poll_interval_s=0, sleep=lambda s: None)
            res = runner.run(specs)
            print("clean run:", json.dumps(res.summary(), default=str))
            check("clean planned", res.planned, PLANNED)
            check("clean executable", res.executable, EXECUTABLE)
            check("clean structurally_excluded", res.structurally_excluded, EXCLUDED)
            check("clean submitted", res.submitted, EXECUTABLE)
            check("clean collected", res.collected, EXECUTABLE)
            check("clean valid_returned", res.valid_returned, EXECUTABLE)
            check("clean submit_failures", res.submit_failures, 0)
            check("clean collect_timeouts", res.collect_timeouts, 0)

            wid = scalar("select wave_id from ops.collection_wave where wave_code='PANEL-CLEAN'")
            check("wave kind sentinel", scalar(
                "select wave_kind::text from ops.collection_wave where wave_code='PANEL-CLEAN'"), "sentinel")
            check("wave panel_subset_id set", scalar(
                "select panel_subset_id is not null from ops.collection_wave where wave_code='PANEL-CLEAN'"), True)
            check("observations (one per executable)", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "where j.wave_id=%s", (wid,)), EXECUTABLE)
            check("cost events (one per executable)", scalar(
                "select count(*) from ops.cost_event where wave_id=%s", (wid,)), EXECUTABLE)
            check("blocked_structural events", scalar(
                "select count(*) from ops.job_event e join ops.collection_job j on j.job_id=e.job_id "
                "where j.wave_id=%s and e.status='blocked_structural'", (wid,)), EXCLUDED)
            check("NO observation on excluded coord", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "where j.wave_id=%s and j.planned_eligibility is distinct from 'eligible_land'", (wid,)), 0)
            check("NO cost on excluded coord", scalar(
                "select count(*) from ops.cost_event c join ops.collection_job j on j.job_id=c.job_id "
                "where j.wave_id=%s and j.planned_eligibility is distinct from 'eligible_land'", (wid,)), 0)
            # one paid task per job: 200 attempts, each with a provider_task_id.
            check("attempts == executable", scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s", (wid,)), EXECUTABLE)
            check("every attempt has a provider_task_id", scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s and a.provider_task_id is null", (wid,)), 0)
            check("distinct provider_task_ids == executable", scalar(
                "select count(distinct a.provider_task_id) from ops.collection_attempt a "
                "join ops.collection_job j on j.job_id=a.job_id where j.wave_id=%s", (wid,)), EXECUTABLE)

            report = pilot.evaluate_wave(conn, "PANEL-CLEAN", persist=True)
            check("clean QA COMPLETE", report["status"], "COMPLETE")
            check("clean QA no integrity violations", len(report["integrity_violations"]), 0)
            check("clean QA job_accounting 1.0", report["metrics"]["job_accounting_rate"], 1.0)
            check("clean QA valid rate 1.0",
                  report["metrics"]["valid_scientific_observation_rate_overall"], 1.0)

            # ---- idempotent resume: submit-only, then resume on the same wave ----
            resume_factory = make_factory()  # persistent per-surface fakes shared by both resume runners
            r1 = panel_run.PanelRunner(
                conn, batch_provider_factory=resume_factory, raw_store=store,
                kind="sentinel", wave_code="PANEL-RESUME", poll_interval_s=0, sleep=lambda s: None)
            r1.setup()
            res1 = panel_run.PanelRunResult(wave_code=r1.wave_code, wave_id=str(r1._wave_id), kind="sentinel")
            r1.submit_phase(specs, res1)  # SUBMIT ONLY (no collect)
            wid2 = scalar("select wave_id from ops.collection_wave where wave_code='PANEL-RESUME'")
            check("resume: submitted, nothing collected yet",
                  (res1.submitted, scalar("select count(*) from ops.observation o "
                                          "join ops.collection_job j on j.job_id=o.job_id where j.wave_id=%s", (wid2,))),
                  (EXECUTABLE, 0))
            attempts_after_submit = scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s", (wid2,))
            check("resume: attempts after submit == executable", attempts_after_submit, EXECUTABLE)

            r2 = panel_run.PanelRunner(
                conn, batch_provider_factory=resume_factory, raw_store=store,
                kind="sentinel", wave_code="PANEL-RESUME", poll_interval_s=0, sleep=lambda s: None)
            res2 = r2.run(specs)
            print("resume run:", json.dumps(res2.summary(), default=str))
            check("resume re-POSTed nothing (0 submitted)", res2.submitted, 0)
            check("resume picked up outstanding tasks", res2.resumed_pending, EXECUTABLE)
            check("resume collected the outstanding tasks", res2.collected, EXECUTABLE)
            check("resume created no new attempts", scalar(
                "select count(*) from ops.collection_attempt a join ops.collection_job j on j.job_id=a.job_id "
                "where j.wave_id=%s", (wid2,)), attempts_after_submit)
            check("resume observations == executable", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "where j.wave_id=%s", (wid2,)), EXECUTABLE)
            check("resume QA COMPLETE", pilot.evaluate_wave(conn, "PANEL-RESUME")["status"], "COMPLETE")

            # ---- reconcile: tasks never become ready -> accounted collect_timeout ----
            # ready=False -> every direct task_get raises ProviderError (never ready)
            # -> every task reconciled as an accounted collect_timeout.
            rec = panel_run.PanelRunner(
                conn, batch_provider_factory=make_factory(ready=False), raw_store=store,
                kind="sentinel", wave_code="PANEL-RECON", poll_interval_s=0,
                sleep=lambda s: None)
            resr = rec.run(specs)
            print("reconcile run:", json.dumps(resr.summary(), default=str))
            check("reconcile submitted", resr.submitted, EXECUTABLE)
            check("reconcile collected 0", resr.collected, 0)
            check("reconcile collect_timeouts == executable", resr.collect_timeouts, EXECUTABLE)
            widr = scalar("select wave_id from ops.collection_wave where wave_code='PANEL-RECON'")
            check("reconcile terminal_failure events == executable", scalar(
                "select count(*) from ops.job_event e join ops.collection_job j on j.job_id=e.job_id "
                "where j.wave_id=%s and e.status='terminal_failure'", (widr,)), EXECUTABLE)
            check("reconcile NO observations (nothing collected)", scalar(
                "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
                "where j.wave_id=%s", (widr,)), 0)
            recon_report = pilot.evaluate_wave(conn, "PANEL-RECON")
            check("reconcile QA job_accounting 1.0 (all accounted)",
                  recon_report["metrics"]["job_accounting_rate"], 1.0)
            check("reconcile QA FAILED (technical loss)", recon_report["status"], "FAILED")
            check("reconcile QA no integrity violation (not quarantined)",
                  len(recon_report["integrity_violations"]), 0)

        print(f"\n{'check':<54} {'result':<28} status")
        print("-" * 96)
        failed = 0
        for label, r, status in checks:
            failed += status == "FAIL"
            print(f"{label:<54} {r:<28} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
