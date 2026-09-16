"""Gated driver for AIO (organic AI Overview) collection (ADR-0008, Stage 2).

Analogue of ``panel_driver`` for the AIO surface: it ties the AIO job matrix
(``aio_run.expand_aio_matrix``) to the shared single-task wave runner
(``pilot.PilotRunner`` via ``aio_run.build_aio_runner``, whose ``run_spike`` per job
dispatches to ``spike.finalize_aio``) and the QA/Wave-Acceptance evaluator
(``pilot.evaluate_wave``), behind a distinct paid gate.

  1. Resolve the wave code (deterministic per day ``AIO-<YYYYMMDD>`` so a same-day
     re-invocation *resumes* the same wave — idempotent, no re-pay — or an explicit
     ``--wave-code`` / ``--resume`` override), get_or_create with ``wave_kind='ad_hoc'``.
  2. Run the water-gated, cell-partitioned matrix (structural coordinates never
     submitted; one paid task per job; completed jobs short-circuit on resume).
  3. Evaluate QA (persisted) and surface the status: anything below COMPLETE exits
     non-zero (no silent partials).

Gating: a NEW ``RUN_PAID_AIO`` env gate, default ``0`` / closed, INDEPENDENT of
``RUN_PAID_SPIKE`` / ``RUN_PAID_PILOT`` / ``RUN_PAID_PANEL`` / ``RUN_AIO_PROBE``. The
paid ``--execute`` path refuses unless ``RUN_PAID_AIO=1`` (checked before any DB
connection) — belt-and-suspenders over the Railway shell gate. No paid call is made
without BOTH ``--execute`` and the open gate; ``--dry-run`` (the default) is a
water-gated plan with no writes and no calls.

The GRADUATED first paid AIO wave is small (the 3×5 pilot cells at the geometry
center, two core query families ≈ 30 tasks) on explicit owner "go" — enough to
MEASURE the ``load_async_ai_overview`` per-trigger add-on billing before trusting
any amortized cost for a wider run. Widening to the full 9-point × 10-condition
AIO panel is future scope with its own go/no-go.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from typing import Any, Callable, Optional

from . import aio_run, pilot
from .models import ManifestContext
from .pilot import PilotJobSpec
from .raw_store import RawStore
from .repository import utcnow

RUN_PAID_AIO_ENV = "RUN_PAID_AIO"

# Exit codes (mirror panel_driver): 0 COMPLETE, 3 gate refused, 4 below COMPLETE.
EXIT_OK = 0
EXIT_GATE_REFUSED = 3
EXIT_BELOW_COMPLETE = 4


def default_wave_code(now: Optional[datetime] = None) -> str:
    """Deterministic per-day AIO wave code, so a same-day re-invocation resumes the
    same wave (get_or_create is a no-op the second time; committed jobs never
    re-pay). AIO has no committed weekly/monthly cadence yet (future scope), so the
    period is the day of the manual run."""
    now = now or utcnow()
    return f"{aio_run.AIO_WAVE_PREFIX}-{now:%Y%m%d}"


def latest_aio_wave(conn, *, methodology_code: str = "MANIFEST_V1_0") -> Optional[str]:
    """The most recently created AIO wave_code for this methodology, or None.
    Used by ``--resume``; idempotency is per wave (job_key includes wave_id), so
    resuming reuses the wave_code and completed jobs are never re-collected/re-paid."""
    row = conn.execute(
        "select w.wave_code from ops.collection_wave w "
        "join manifest.methodology_version mv on mv.methodology_version_id = w.methodology_version_id "
        "where w.wave_kind = %s and w.wave_code like %s and mv.methodology_code = %s "
        "order by w.created_at desc, w.wave_code desc limit 1",
        (aio_run.AIO_WAVE_KIND, f"{aio_run.AIO_WAVE_PREFIX}-%", methodology_code),
    ).fetchone()
    return row[0] if row else None


def resolve_wave_code(conn, *, methodology_code: str, wave_code: Optional[str],
                      resume: bool, now: Optional[datetime] = None) -> str:
    """Explicit ``--wave-code`` wins; else ``--resume`` continues the latest AIO
    wave; else a deterministic per-day code (which itself resumes a same-day wave)."""
    if wave_code:
        return wave_code
    if resume:
        latest = latest_aio_wave(conn, methodology_code=methodology_code)
        if latest:
            return latest
    return default_wave_code(now)


def run_aio_collection(
    conn,
    *,
    provider_factory: Callable[[ManifestContext], Any],
    raw_store: RawStore,
    methodology_code: str = "MANIFEST_V1_0",
    wave_code: Optional[str] = None,
    resume: bool = False,
    workers: int = 1,
    max_retries: int = 3,
    conn_factory: Optional[Callable[[], Any]] = None,
    persist_evaluation: bool = True,
    now: Optional[datetime] = None,
    specs: Optional[list[PilotJobSpec]] = None,
) -> dict[str, Any]:
    """Drive one gated AIO collection wave end to end and return the result.

    ``specs`` is an injection seam for offline validation/tests; in production it is
    None and the GRADUATED AIO scope is generated. Providers + raw_store are
    injected so this function never constructs a live client — the paid client is
    built only by ``main`` after the ``RUN_PAID_AIO`` gate."""
    resolved_code = resolve_wave_code(
        conn, methodology_code=methodology_code, wave_code=wave_code, resume=resume, now=now)
    runner = aio_run.build_aio_runner(
        conn, provider_factory=provider_factory, raw_store=raw_store,
        wave_code=resolved_code, methodology_code=methodology_code,
        max_retries=max_retries, max_workers=workers, conn_factory=conn_factory)
    runner.setup()
    if specs is None:
        specs = aio_run.expand_aio_matrix()
    res = runner.run(specs)
    report = pilot.evaluate_wave(conn, runner.wave_code, persist=persist_evaluation)
    return {
        "surface": aio_run.AIO_SURFACE,
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
    return os.environ.get(RUN_PAID_AIO_ENV) == "1"


def _csv(v: Optional[str]) -> Optional[list[str]]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def _build_specs(args) -> list[PilotJobSpec]:
    conditions = _csv(args.conditions)
    if conditions is None and args.all_conditions:
        conditions = aio_run.AIO_CONDITIONS_ALL
    points = _csv(args.points)
    if points is None and args.points_full:
        points = aio_run.AIO_POINTS_FULL
    return aio_run.expand_aio_matrix(
        industries=_csv(args.industries), markets=_csv(args.markets),
        conditions=conditions, points=points)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="AIO (organic AI Overview) collection driver. Runs the water-gated, "
                    "cell-partitioned AIO matrix through the shared runner (finalize_aio per job) "
                    "and evaluates QA. Paid collection requires --execute AND RUN_PAID_AIO=1 "
                    "(default closed). Default scope is the GRADUATED first-run cells.")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--industries", default=None, help="CSV; default the 3 pilot industries")
    p.add_argument("--markets", default=None, help="CSV; default the 5 pilot markets")
    p.add_argument("--conditions", default=None,
                   help="CSV of AIO condition codes; default the graduated subset (AIO_C01,AIO_C04)")
    p.add_argument("--all-conditions", action="store_true",
                   help="use all 10 AIO_QUERY_V1 conditions (ignored if --conditions is given)")
    p.add_argument("--points", default=None, help="CSV of geometry points; default center C")
    p.add_argument("--points-full", dest="points_full", action="store_true",
                   help="use the full GEOGRID13E_V1 13-point geometry (ignored if --points is given)")
    p.add_argument("--wave-code", default=None,
                   help="explicit wave code (wins over --resume and the per-day default)")
    p.add_argument("--resume", action="store_true",
                   help="continue the latest AIO wave instead of a new per-day wave "
                        "(idempotency is per wave; completed jobs are not re-collected/re-paid)")
    p.add_argument("--workers", type=int, default=1,
                   help="parallel workers (default 1). Work is partitioned by (industry, market, "
                        "surface) so KG-MID/web entity resolution stays correct; capped at #groups.")
    p.add_argument("--dry-run", action="store_true",
                   help="plan + water gate + render; print accounting; NO writes, NO provider call")
    p.add_argument("--evaluate-only", default=None, metavar="WAVE_CODE",
                   help="run the QA/Wave-Acceptance evaluation on an existing wave; no collection")
    p.add_argument("--execute", action="store_true",
                   help="REQUIRED (with RUN_PAID_AIO=1) to make live PAID AIO calls")
    p.add_argument("--persist-evaluation", action="store_true",
                   help="write ops.wave_evaluation + qa_event rows after collection/evaluation")
    args = p.parse_args(argv)

    specs = _build_specs(args)

    # Gate BEFORE any DB connection so a refused paid run is cheap and DB-free.
    if args.execute and not args.dry_run and not args.evaluate_only and not _gate_open():
        print(json.dumps({
            "refused": True,
            "reason": f"{RUN_PAID_AIO_ENV} != 1: paid AIO collection is gated (default closed, "
                      f"independent of RUN_PAID_SPIKE/RUN_PAID_PILOT/RUN_PAID_PANEL/RUN_AIO_PROBE). "
                      f"Set {RUN_PAID_AIO_ENV}=1 on the service to open the gate for a run, on "
                      f"explicit owner 'go' (graduated first).",
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
            plan = pilot.plan_dry_run(conn, specs, methodology_code=args.methodology,
                                      treatment_set_code=aio_run.AIO_TREATMENT_SET)
            plan["mode"] = "dry_run" if args.dry_run else "refused_no_execute"
            plan["surface"] = aio_run.AIO_SURFACE
            plan["would_use_wave_code"] = default_wave_code()
            plan["note"] = ("planning only; a live run requires --execute AND RUN_PAID_AIO=1. "
                            "Structural-water coordinates are dropped at run time (never submitted). "
                            "No paid call is made from a dry run.")
            print(json.dumps(plan, indent=2, default=str))
            return EXIT_OK

        # LIVE PAID PATH -- gate already confirmed open above.
        from .config import ProviderCreds, StorageConfig
        from .dataforseo import HttpMapsProvider
        from .raw_store import SupabaseStorageRawStore
        creds = ProviderCreds.from_env()
        raw_store = SupabaseStorageRawStore(StorageConfig.from_env())

        def provider_factory(ctx: ManifestContext):
            return HttpMapsProvider(creds, ctx.post_endpoint, ctx.get_endpoint)

        db_url = settings.db_url()

        def conn_factory():
            return psycopg.connect(db_url)

        out = run_aio_collection(
            conn, provider_factory=provider_factory, raw_store=raw_store,
            methodology_code=args.methodology, wave_code=args.wave_code, resume=args.resume,
            workers=max(1, args.workers), conn_factory=conn_factory,
            persist_evaluation=args.persist_evaluation, specs=specs)
        print(json.dumps(out, indent=2, default=str))
        status = out["evaluation"]["status"]
        return EXIT_OK if status == "COMPLETE" else EXIT_BELOW_COMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
