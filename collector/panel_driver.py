"""Cadence driver for Full Panel / Sentinel operation (ADR-0007, design doc step 3).

The validated pieces already exist: the manifest-driven wave generator
(``collector.panel``), the Standard decoupled two-phase runner
(``collector.panel_run.PanelRunner``), and the QA/Wave-Acceptance evaluator
(``collector.pilot.evaluate_wave``). This module is the **thin cadence driver**
that ties them together for a scheduled invocation:

  1. Decide the wave ``kind`` -- Full Panel on the monthly anchor, else Sentinel.
     "Sentinel is a selection": in a Full-Panel week we run ONLY the Full Panel
     (a strict superset of the Sentinel cells), never a second Sentinel wave.
  2. Resolve the wave code (deterministic per cadence period, so a re-invocation
     in the same period *resumes* the same wave -- idempotent, no re-pay), or an
     explicit ``--wave-code`` / ``--resume`` override, then get_or_create the wave
     with the right ``wave_kind`` / ``panel_subset_id``.
  3. Run generate_wave_specs -> PanelRunner (submit -> collect -> reconcile) ->
     evaluate_wave (persisted).
  4. Surface the QA status. Anything below COMPLETE is surfaced (non-zero exit);
     there are no silent partials.

Cadence anchor (engineering choice, revisable without a methodology amendment --
ADR-0007 / design doc §4, §7): the **first scheduled run of a calendar month that
has no ``full_panel`` wave yet** runs the Full Panel; every other scheduled weekly
run that month runs the Sentinel. This is declarative over DB state (not a
hardcoded calendar), so it is resume-safe and needs no cadence-anchor table.

Gating (ADR-0007 decision 4): a NEW ``RUN_PAID_PANEL`` env gate, default ``0`` /
closed, INDEPENDENT of ``RUN_PAID_SPIKE`` / ``RUN_PAID_PILOT``. The paid
``--execute`` path refuses unless ``RUN_PAID_PANEL=1`` -- belt-and-suspenders over
the Railway shell gate, so even a manual ``--execute`` cannot spend without the
open gate. This module makes NO paid call without both ``--execute`` and the open
gate; ``--dry-run`` (the default) is a set-based plan with no writes and no calls.

The graduated first live step remains one **Sentinel** wave (~$2.64) on explicit
owner "go", evaluate COMPLETE, then a Full Panel -- never before.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import panel, pilot
from .dataforseo import MAX_TASKS_PER_POST
from .models import ManifestContext
from .panel_run import PanelRunner, PanelRunResult
from .pilot import PilotJobSpec
from .raw_store import RawStore
from .repository import utcnow

RUN_PAID_PANEL_ENV = "RUN_PAID_PANEL"
AUTO = "auto"
KIND_CHOICES = (AUTO, panel.FULL_PANEL, panel.SENTINEL)

# Exit codes (distinct so a scheduler can react): 0 COMPLETE, 3 gate refused,
# 4 wave evaluated below COMPLETE (PARTIAL/FAILED/QUARANTINED -- no silent partial).
EXIT_OK = 0
EXIT_GATE_REFUSED = 3
EXIT_BELOW_COMPLETE = 4


# ---------------------------------------------------------------------------
# Cadence-anchor decision + deterministic per-period wave codes
# ---------------------------------------------------------------------------
def _month_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = start.replace(year=start.year + 1, month=1) if start.month == 12 \
        else start.replace(month=start.month + 1)
    return start, nxt


def decide_kind(conn, *, methodology_code: str, now: Optional[datetime] = None) -> str:
    """Full Panel on the monthly anchor (no ``full_panel`` wave yet this calendar
    month), else Sentinel. Declarative over DB state, so a re-run inside a
    Full-Panel week still resolves to ``full_panel`` (and resumes it) rather than
    kicking off a Sentinel."""
    now = now or utcnow()
    start, nxt = _month_bounds(now)
    row = conn.execute(
        "select count(*) from ops.collection_wave w "
        "join manifest.methodology_version mv on mv.methodology_version_id = w.methodology_version_id "
        "where w.wave_kind = 'full_panel' and mv.methodology_code = %s "
        "and w.scheduled_for >= %s and w.scheduled_for < %s",
        (methodology_code, start, nxt),
    ).fetchone()
    full_panel_this_month = int(row[0]) > 0
    return panel.SENTINEL if full_panel_this_month else panel.FULL_PANEL


def default_wave_code(kind: str, now: Optional[datetime] = None) -> str:
    """A deterministic wave code anchored to the cadence period, so the same
    scheduled period naturally resumes the same wave (get_or_create is a no-op the
    second time; jobs with a committed observation short-circuit -- no re-pay).

      * Full Panel -> ``FULLPANEL-<YYYYMM>``  (one per calendar month)
      * Sentinel   -> ``SENTINEL-<ISOyear>W<ISOweek>``  (one per ISO week)
    """
    now = now or utcnow()
    if kind == panel.FULL_PANEL:
        return f"FULLPANEL-{now:%Y%m}"
    if kind == panel.SENTINEL:
        return f"SENTINEL-{now:%G}W{now:%V}"
    raise ValueError(f"unknown wave kind {kind!r}; expected one of {panel.WAVE_KINDS}")


def latest_wave(conn, *, kind: str, methodology_code: str) -> Optional[str]:
    """The most recently created wave_code of this kind for the methodology, or
    None. Used by ``--resume`` to continue the latest wave of a kind regardless of
    the current cadence period (idempotency is per wave; completed jobs are never
    re-collected or re-paid)."""
    row = conn.execute(
        "select w.wave_code from ops.collection_wave w "
        "join manifest.methodology_version mv on mv.methodology_version_id = w.methodology_version_id "
        "where w.wave_kind = %s and mv.methodology_code = %s "
        "order by w.created_at desc, w.wave_code desc limit 1",
        (kind, methodology_code),
    ).fetchone()
    return row[0] if row else None


def resolve_kind(conn, *, kind: str, methodology_code: str, now: Optional[datetime] = None) -> str:
    if kind == AUTO:
        return decide_kind(conn, methodology_code=methodology_code, now=now)
    if kind in panel.WAVE_KINDS:
        return kind
    raise ValueError(f"unknown --kind {kind!r}; expected one of {KIND_CHOICES}")


def resolve_wave_code(conn, *, kind: str, methodology_code: str, wave_code: Optional[str],
                      resume: bool, now: Optional[datetime] = None) -> str:
    """Explicit ``--wave-code`` wins; else ``--resume`` continues the latest wave of
    the kind; else a deterministic per-period code (which itself resumes an existing
    same-period wave via get_or_create)."""
    if wave_code:
        return wave_code
    if resume:
        latest = latest_wave(conn, kind=kind, methodology_code=methodology_code)
        if latest:
            return latest
    return default_wave_code(kind, now)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_panel_cadence(
    conn,
    *,
    batch_provider_factory: Callable[[ManifestContext], Any],
    raw_store: RawStore,
    kind: str = AUTO,
    methodology_code: str = "MANIFEST_V1_0",
    wave_code: Optional[str] = None,
    resume: bool = False,
    batch_size: int = MAX_TASKS_PER_POST,
    poll_interval_s: float = 5.0,
    collect_timeout_s: float = 3600.0,
    workers: int = 1,
    conn_factory: Optional[Callable[[], Any]] = None,
    persist_evaluation: bool = True,
    now: Optional[datetime] = None,
    specs: Optional[list[PilotJobSpec]] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Drive one scheduled cadence invocation end to end and return the result.

    ``specs`` is an injection seam for offline validation/tests (a small scope on
    ephemeral pgvector); in production it is None and the full manifest-driven
    scope for ``kind`` is generated. Providers + raw_store are injected so this
    function itself never constructs a live client -- the paid client is built only
    by ``main`` after the ``RUN_PAID_PANEL`` gate.
    """
    resolved_kind = resolve_kind(conn, kind=kind, methodology_code=methodology_code, now=now)
    resolved_code = resolve_wave_code(
        conn, kind=resolved_kind, methodology_code=methodology_code,
        wave_code=wave_code, resume=resume, now=now)

    runner = PanelRunner(
        conn, batch_provider_factory=batch_provider_factory, raw_store=raw_store,
        kind=resolved_kind, methodology_code=methodology_code, wave_code=resolved_code,
        batch_size=batch_size, poll_interval_s=poll_interval_s,
        collect_timeout_s=collect_timeout_s, max_workers=workers, conn_factory=conn_factory,
        sleep=sleep)
    runner.setup()

    if specs is None:
        specs = panel.generate_wave_specs(conn, kind=resolved_kind, methodology_code=methodology_code)

    res: PanelRunResult = runner.run(specs)
    report = pilot.evaluate_wave(conn, runner.wave_code, persist=persist_evaluation)
    return {
        "kind": resolved_kind,
        "wave_code": runner.wave_code,
        "wave_id": str(runner._wave_id),
        "scheduled_for": (now or utcnow()).isoformat(),
        "run": res.summary(),
        "evaluation": report,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _gate_open() -> bool:
    return os.environ.get(RUN_PAID_PANEL_ENV) == "1"


def _dry_run(conn, *, kind: str, methodology_code: str) -> dict[str, Any]:
    """Set-based plan (no writes, no provider call). Decides the kind the same way
    a live run would, then prints the water-gated accounting + cost estimate."""
    resolved_kind = resolve_kind(conn, kind=kind, methodology_code=methodology_code)
    plan = panel.plan_wave(conn, kind=resolved_kind, methodology_code=methodology_code)
    conn.rollback()  # planning only
    plan["mode"] = "dry_run"
    plan["resolved_kind"] = resolved_kind
    plan["would_use_wave_code"] = default_wave_code(resolved_kind)
    plan["note"] = ("planning only; a live run requires --execute AND RUN_PAID_PANEL=1. "
                    "No paid call is made from a dry run.")
    return plan


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Full Panel / Sentinel cadence driver (Maps + Organic). Decides the wave kind, "
                    "mints/resumes the wave, runs the decoupled panel runner, and evaluates QA. "
                    "Paid collection requires --execute AND RUN_PAID_PANEL=1 (default closed).")
    p.add_argument("--kind", default=AUTO, choices=list(KIND_CHOICES),
                   help="auto (default): Full Panel on the monthly anchor, else Sentinel.")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--wave-code", default=None,
                   help="explicit wave code (wins over --resume and the per-period default)")
    p.add_argument("--resume", action="store_true",
                   help="continue the latest wave of the resolved kind instead of a new per-period wave "
                        "(idempotency is per wave; completed jobs are not re-collected/re-paid)")
    p.add_argument("--batch-size", type=int, default=MAX_TASKS_PER_POST,
                   help=f"tasks per POST (1..{MAX_TASKS_PER_POST}); default {MAX_TASKS_PER_POST}")
    p.add_argument("--poll-interval", type=float, default=5.0,
                   help="seconds between tasks_ready polls in the collect phase")
    p.add_argument("--collect-timeout", type=float, default=3600.0,
                   help="seconds a submitted task may stay un-ready before it becomes an accounted "
                        "terminal_failure (collect_timeout); resumable, never re-POSTed")
    p.add_argument("--workers", type=int, default=1,
                   help="parallel COLLECT workers (default 1 = sequential). Work is partitioned by "
                        "(industry, market, surface) so entity resolution stays correct; capped at the "
                        "number of such groups. Submission stays single-threaded.")
    p.add_argument("--dry-run", action="store_true",
                   help="print the water-gated accounting + cost estimate; NO writes, NO provider call")
    p.add_argument("--evaluate-only", default=None, metavar="WAVE_CODE",
                   help="run the QA/Wave-Acceptance evaluation on an existing wave; no collection")
    p.add_argument("--execute", action="store_true",
                   help="REQUIRED (with RUN_PAID_PANEL=1) to make live PAID panel calls")
    p.add_argument("--persist-evaluation", action="store_true",
                   help="write ops.wave_evaluation + qa_event rows after collection/evaluation")
    args = p.parse_args(argv)

    # Gate BEFORE any DB connection so a refused paid run is cheap and DB-free.
    if args.execute and not args.dry_run and not args.evaluate_only and not _gate_open():
        print(json.dumps({
            "refused": True,
            "reason": f"{RUN_PAID_PANEL_ENV} != 1: paid panel collection is gated (default closed, "
                      f"independent of RUN_PAID_SPIKE/RUN_PAID_PILOT). Set {RUN_PAID_PANEL_ENV}=1 on the "
                      f"service to open the gate for a run, on explicit owner 'go' (Sentinel-first).",
        }, indent=2))
        return EXIT_GATE_REFUSED

    import psycopg
    from .config import Settings
    settings = Settings()

    with psycopg.connect(settings.db_url()) as conn:
        if args.evaluate_only:
            report = pilot.evaluate_wave(conn, args.evaluate_only, persist=args.persist_evaluation)
            print(json.dumps(report, indent=2, default=str))
            return EXIT_OK if report["status"] == "COMPLETE" else EXIT_BELOW_COMPLETE

        if args.dry_run or not args.execute:
            plan = _dry_run(conn, kind=args.kind, methodology_code=args.methodology)
            if not args.dry_run:
                plan["mode"] = "refused_no_execute"
            print(json.dumps(plan, indent=2, default=str))
            return EXIT_OK

        # LIVE PAID PATH -- gate already confirmed open above.
        from .config import ProviderCreds, StorageConfig
        from .dataforseo import HttpMapsProvider
        from .raw_store import SupabaseStorageRawStore
        creds = ProviderCreds.from_env()
        raw_store = SupabaseStorageRawStore(StorageConfig.from_env())

        def batch_provider_factory(ctx: ManifestContext):
            # HttpMapsProvider implements the BatchProvider seam (task_post_batch /
            # tasks_ready / task_get_advanced) as well as the per-job methods.
            return HttpMapsProvider(creds, ctx.post_endpoint, ctx.get_endpoint,
                                    poll_interval_s=args.poll_interval)

        # Each parallel collect worker opens its own connection (psycopg conns are not
        # thread-safe). Only used when --workers>1; the setup/eval connection is `conn`.
        db_url = settings.db_url()

        def conn_factory():
            return psycopg.connect(db_url)

        out = run_panel_cadence(
            conn, batch_provider_factory=batch_provider_factory, raw_store=raw_store,
            kind=args.kind, methodology_code=args.methodology, wave_code=args.wave_code,
            resume=args.resume, batch_size=args.batch_size, poll_interval_s=args.poll_interval,
            collect_timeout_s=args.collect_timeout, workers=max(1, args.workers),
            conn_factory=conn_factory, persist_evaluation=args.persist_evaluation)
        print(json.dumps(out, indent=2, default=str))
        status = out["evaluation"]["status"]
        # No silent partials: only a COMPLETE wave exits 0.
        return EXIT_OK if status == "COMPLETE" else EXIT_BELOW_COMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
