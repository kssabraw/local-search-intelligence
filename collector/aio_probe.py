"""AIO capture-feasibility probe sweep (ADR-0005, Stage 2 gate-1).

Runs a small, bounded probe over the frozen 3x5 Stage-1 pilot cells against the
seeded ``DFS_AIO_V1`` provider profile (DataForSEO AI Mode endpoint), so the AIO
schema decision is grounded in what the provider PROVES it returns rather than in
what the AIO PRD hopes for. Each probe job:

  * rides the validated single-coordinate path (``spike.run_spike(probe_only=True)``):
    immutable raw (content-addressed, fail-on-exists, gzipped) -> record an
    ``ops.observation`` whose ``parser_metadata`` carries the structural capability
    inventory (``inspect_aio.inspect_aio_capture``) -> attribute the real per-task
    cost in the ledger. NO normalization into ``aio.*`` (that is committed only if
    the probe passes);
  * honours every guardrail: structural-water coordinates are NEVER submitted
    (missing != zero), idempotency is at submission (a committed observation
    short-circuits -> resume re-POSTs nothing / re-pays nothing).

The sweep then aggregates a **capture-feasibility report** (``summarize_capture``):
per required field, does the provider ever return it (CAPTURABLE), never return it
across triggered AIOs (NOT_OBSERVABLE -> ``provider_not_observable``), or did no AIO
trigger at all (INCONCLUSIVE)? That report is what the owner reads to decide which
``aio.*`` columns to build.

Paid gate: ``RUN_AIO_PROBE`` (default ``0``/closed, independent of the
spike/pilot/panel gates). The paid ``--execute`` path refuses unless
``RUN_AIO_PROBE=1``, checked before any DB connection; ``--dry-run`` (default) is a
water-gated plan with no writes and no provider call. No paid call is made without
BOTH ``--execute`` and the open gate, on explicit owner "go".
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Optional

from . import spike
from .inspect_aio import CAPABILITY_KEYS
from .models import ManifestContext
from .pilot import PILOT_INDUSTRIES, PILOT_MARKETS, PilotJobSpec
from .raw_store import RawStore
from .repository import Repo, utcnow

RUN_AIO_PROBE_ENV = "RUN_AIO_PROBE"

# The AIO conditions come from the seeded AIO_QUERY_V1 set. The probe deliberately
# uses a SMALL versioned SUBSET (not the full 10) spanning the query-formulation
# families the AIO PRD Sec.8 makes first-class -- near-me vs explicit-city -- which
# is enough to observe field presence. This is a PROBE selection, NOT the locked
# production condition set (that stays owner-signed in the manifest).
AIO_TREATMENT_SET = "AIO_QUERY_V1"
PROBE_CONDITION_SET_VERSION = "AIOPROBE_V0"
AIO_PROBE_CONDITIONS_V0 = ("AIO_C01", "AIO_C04")   # core near-me + core explicit-city
# Capture feasibility is about field PRESENCE, not spatial coverage, so the probe
# runs the geometry center only. The 9-point AIO grid is a coverage concern that
# only matters once the surface is committed.
AIO_PROBE_POINT = "C"

# Observation states the probe treats as a real, returned AIO response.
_RETURNED_STATES = ("returned",)


@dataclasses.dataclass(frozen=True)
class ProbeMode:
    """One AIO-surface probe target. The AI Overview appears on two DataForSEO
    surfaces; ADR-0005 lets us probe each without committing schema:

      * ``ai_mode``  -- the seeded ``DFS_AIO_V1`` AI-Mode endpoint (the manifest's
        committed AIO surface). Runs the AIO conditions on the ``aio`` surface.
      * ``organic``  -- the AI-Overview element embedded in the organic SERP
        (``DFS_ORGANIC_V1``). Runs the local-intent Maps/Organic conditions on the
        ``organic`` surface with ``calculate_rectangles``, and forces the AIO
        capability inspector over the response (whose ``ai_overview`` item it probes)
        even though the surface_code is ``organic``.

    The organic mode is how we test the AI-Mode-vs-AI-Overview question empirically:
    does the structured local-business-card module + embedded-GBP card that AI Mode
    lacked appear on the organic AI-Overview surface?
    """
    key: str
    surface_code: str
    treatment_set: str
    default_conditions: tuple[str, ...]
    provider_label: str
    wave_tag: str            # inserted into the wave code ("" for ai_mode)
    force_aio_inspect: bool  # run the AIO inspector on a non-aio surface


AIMODE_MODE = ProbeMode(
    "ai_mode", "aio", AIO_TREATMENT_SET, AIO_PROBE_CONDITIONS_V0,
    "DFS_AIO_V1 (DataForSEO AI Mode)", "", False)
ORGANIC_MODE = ProbeMode(
    "organic", "organic", "GOOGLE_QUERY_V1", ("Q1",),  # Q1 = core near-me local-intent
    "DFS_ORGANIC_V1 (AI Overview embedded in the organic SERP)", "ORG", True)
PROBE_MODES = {m.key: m for m in (AIMODE_MODE, ORGANIC_MODE)}


def expand_probe_matrix(
    *,
    industries: Optional[list[str]] = None,
    markets: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    point: str = AIO_PROBE_POINT,
    mode: str = "ai_mode",
) -> list[PilotJobSpec]:
    """Deterministic probe matrix in job-generator v0.7 order (industry -> market ->
    surface -> condition -> point), for the given probe mode's surface + conditions
    at the center point."""
    m = PROBE_MODES[mode]
    industries = industries or PILOT_INDUSTRIES
    markets = markets or PILOT_MARKETS
    conditions = conditions or list(m.default_conditions)
    out: list[PilotJobSpec] = []
    for industry in industries:
        for market in markets:
            for condition in conditions:
                out.append(PilotJobSpec(m.surface_code, industry, market, condition, point))
    return out


def default_wave_code(now: Optional[datetime] = None, mode: str = "ai_mode") -> str:
    now = now or utcnow()
    tag = PROBE_MODES[mode].wave_tag
    prefix = f"AIOPROBE-{tag + '-' if tag else ''}{PROBE_CONDITION_SET_VERSION}"
    return f"{prefix}-{now:%Y%m%d}"


@dataclasses.dataclass
class ProbeRunResult:
    wave_code: str
    planned: int
    executable: int
    structurally_excluded: int
    probed: int
    already_observed: int
    triggered: int
    provider_failures: int
    total_cost_microusd: int
    per_job: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d.pop("per_job", None)
        return d


class AioProbeRunner:
    """Drives the AIO capture probe over the executable cells under one wave.

    Dependencies are injected (``provider_factory(ctx)`` yields a provider for the
    job's surface -- a fake offline, the real HTTP client live; ``raw_store`` is the
    immutable raw sink), so nothing here reaches the network unless the injected
    dependencies do.
    """

    def __init__(
        self,
        conn,
        *,
        provider_factory: Callable[[ManifestContext], Any],
        raw_store: RawStore,
        wave_code: Optional[str] = None,
        methodology_code: str = "MANIFEST_V1_0",
        calculate_rectangles: bool = True,
        mode: str = "ai_mode",
        now: Optional[datetime] = None,
    ):
        self.conn = conn
        self.repo = Repo(conn)
        self.provider_factory = provider_factory
        self.raw_store = raw_store
        self.methodology_code = methodology_code
        self.calculate_rectangles = calculate_rectangles
        self.mode = PROBE_MODES[mode]
        self._now = now or utcnow()
        self.wave_code = wave_code or default_wave_code(self._now, self.mode.key)

    def run(self, specs: list[PilotJobSpec]) -> ProbeRunResult:
        res = ProbeRunResult(
            wave_code=self.wave_code, planned=len(specs), executable=0,
            structurally_excluded=0, probed=0, already_observed=0, triggered=0,
            provider_failures=0, total_cost_microusd=0)
        for spec in specs:
            ctx = self.repo.load_manifest_context(
                methodology_code=self.methodology_code, surface_code=spec.surface,
                industry_code=spec.industry, market_code=spec.market, point_code=spec.point,
                treatment_set_code=self.mode.treatment_set, treatment_code=spec.treatment)
            if ctx.eligibility != "eligible_land":
                # Structural missingness is never submitted (missing != zero).
                res.structurally_excluded += 1
                res.per_job.append({"label": spec.label, "coordinate": ctx.coordinate_code,
                                    "status": "blocked_structural", "eligibility": ctx.eligibility})
                self.conn.rollback()
                continue
            res.executable += 1
            provider = self.provider_factory(ctx)
            out = spike.run_spike(
                self.conn, ctx=ctx, provider=provider, raw_store=self.raw_store,
                wave_code=self.wave_code, probe_only=True,
                calculate_rectangles=self.calculate_rectangles,
                force_aio_inspect=self.mode.force_aio_inspect)
            self.conn.commit()
            status = out.get("status")
            if status == "already_observed":
                res.already_observed += 1
            else:
                res.probed += 1
                if out.get("aio_present"):
                    res.triggered += 1
                if out.get("observation_state") not in _RETURNED_STATES:
                    res.provider_failures += 1
            res.per_job.append({"label": spec.label, "coordinate": ctx.coordinate_code, **{
                k: out.get(k) for k in ("status", "observation_state", "provider_status_code",
                                        "aio_present", "provider_cost_usd")}})
        # Total realized cost from the ledger for this wave (truthful attribution).
        res.total_cost_microusd = int(self.conn.execute(
            "select coalesce(sum(ce.amount_microusd),0) from ops.cost_event ce "
            "join ops.collection_wave w on w.wave_id = ce.wave_id where w.wave_code = %s",
            (self.wave_code,)).fetchone()[0])
        return res


def summarize_capture(conn, wave_code: str) -> dict[str, Any]:
    """Aggregate the wave's probe observations into a capture-feasibility report.

    Reads back each observation's ``parser_metadata->'aio_capture'`` (written by the
    inspector) and rolls each required field up to a decision verdict:

      * CAPTURABLE     -- the provider returned it in >=1 triggered AIO (build the column);
      * NOT_OBSERVABLE -- >=1 AIO triggered but the field never appeared
                          (mark provider_not_observable, do NOT build an empty column);
      * INCONCLUSIVE   -- no AIO triggered in the whole wave (cannot decide; widen the probe).
    """
    rows = conn.execute(
        "select o.parser_metadata "
        "from ops.observation o join ops.collection_job j on j.job_id = o.job_id "
        "join ops.collection_wave w on w.wave_id = j.wave_id "
        "where w.wave_code = %s and (o.parser_metadata ? 'aio_capture')",
        (wave_code,)).fetchall()

    total = len(rows)
    triggered = 0
    returned = 0
    caps = {k: {"present": 0, "absent": 0, "uncertain": 0} for k in CAPABILITY_KEYS}
    for (md,) in rows:
        cap = (md or {}).get("aio_capture") or {}
        if cap.get("returned"):
            returned += 1
        is_trig = bool(cap.get("aio_present"))
        if is_trig:
            triggered += 1
        for key, agg in caps.items():
            v = ((cap.get("capabilities") or {}).get(key) or {}).get("verdict", "uncertain")
            agg[v] = agg.get(v, 0) + 1

    def rollup(agg: dict[str, int]) -> str:
        if triggered == 0:
            return "INCONCLUSIVE"
        if agg["present"] >= 1:
            return "CAPTURABLE"
        return "NOT_OBSERVABLE"

    fields = {k: {"decision": rollup(agg), **agg} for k, agg in caps.items()}
    n_capturable = sum(1 for f in fields.values() if f["decision"] == "CAPTURABLE")
    return {
        "wave_code": wave_code,
        "observations": total,
        "returned": returned,
        "aio_triggered": triggered,
        "trigger_rate": (triggered / returned) if returned else None,
        "fields": fields,
        "capturable_fields": n_capturable,
        "required_fields": len(CAPABILITY_KEYS),
        "note": ("Decision rule (ADR-0005): CAPTURABLE => build the aio.* column; "
                 "NOT_OBSERVABLE => mark provider_not_observable, no empty column; "
                 "INCONCLUSIVE => no AIO triggered, widen the probe before deciding."),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _gate_open() -> bool:
    return os.environ.get(RUN_AIO_PROBE_ENV) == "1"


def _split(csv: Optional[str]) -> Optional[list[str]]:
    return [x.strip() for x in csv.split(",") if x.strip()] if csv else None


def _plan(specs: list[PilotJobSpec], mode: str = "ai_mode") -> dict[str, Any]:
    m = PROBE_MODES[mode]
    return {
        "mode": "dry_run",
        "probe_mode": m.key,
        "surface": m.surface_code,
        "provider_profile": m.provider_label,
        "condition_set": PROBE_CONDITION_SET_VERSION,
        "conditions": sorted({s.treatment for s in specs}),
        "point": AIO_PROBE_POINT,
        "planned_jobs": len(specs),
        "cells": sorted({f"{s.industry}:{s.market}" for s in specs}),
        "would_use_wave_code": default_wave_code(mode=m.key),
        "note": ("planning only; a live run requires --execute AND RUN_AIO_PROBE=1. "
                 "Structural-water coordinates are dropped at run time (never submitted). "
                 "No paid call is made from a dry run."),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="AIO capture-feasibility probe (ADR-0005). Sweeps the frozen 3x5 pilot cells "
                    "against DFS_AIO_V1 (AI Mode), records the structural capability inventory, and "
                    "reports which AIO-PRD fields the provider proves it returns. Paid run requires "
                    "--execute AND RUN_AIO_PROBE=1 (default closed).")
    p.add_argument("--mode", default="ai_mode", choices=list(PROBE_MODES),
                   help="ai_mode (default, DFS_AIO_V1 AI Mode) or organic (AI Overview embedded in the "
                        "organic SERP via DFS_ORGANIC_V1 — tests the AI-Mode-vs-AI-Overview question)")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--industries", default=None, help="CSV override (default = 3 pilot industries)")
    p.add_argument("--markets", default=None, help="CSV override (default = 5 pilot markets)")
    p.add_argument("--conditions", default=None,
                   help="CSV of condition codes (default = the mode's probe subset)")
    p.add_argument("--point", default=AIO_PROBE_POINT, help="geometry point (default center C)")
    p.add_argument("--wave-code", default=None, help="explicit wave code (else AIOPROBE-<V0>-<YYYYMMDD>)")
    p.add_argument("--no-rectangles", action="store_true",
                   help="do NOT request calculate_rectangles (probe whether the provider omits geometry)")
    p.add_argument("--dry-run", action="store_true", help="print the plan; NO writes, NO provider call")
    p.add_argument("--summarize-only", default=None, metavar="WAVE_CODE",
                   help="print the capture-feasibility report for an existing wave; no collection")
    p.add_argument("--execute", action="store_true",
                   help="REQUIRED (with RUN_AIO_PROBE=1) to make live PAID probe calls")
    args = p.parse_args(argv)

    specs = expand_probe_matrix(
        industries=_split(args.industries), markets=_split(args.markets),
        conditions=_split(args.conditions), point=args.point, mode=args.mode)

    # Gate BEFORE any DB connection so a refused paid run is cheap and DB-free.
    if args.execute and not args.dry_run and not args.summarize_only and not _gate_open():
        print(json.dumps({
            "refused": True,
            "reason": f"{RUN_AIO_PROBE_ENV} != 1: paid AIO capture probe is gated (default closed, "
                      f"independent of RUN_PAID_SPIKE/RUN_PAID_PILOT/RUN_PAID_PANEL). Set "
                      f"{RUN_AIO_PROBE_ENV}=1 on the service to open the gate for a run, on explicit "
                      f"owner 'go'.",
        }, indent=2))
        return 3

    if args.dry_run or (not args.execute and not args.summarize_only):
        plan = _plan(specs, args.mode)
        if not args.dry_run:
            plan["mode"] = "refused_no_execute"
        print(json.dumps(plan, indent=2))
        return 0

    import psycopg
    from .config import Settings
    settings = Settings()
    with psycopg.connect(settings.db_url()) as conn:
        if args.summarize_only:
            print(json.dumps(summarize_capture(conn, args.summarize_only), indent=2, default=str))
            return 0

        # LIVE PAID PATH -- gate already confirmed open above.
        from .config import ProviderCreds, StorageConfig
        from .dataforseo import HttpMapsProvider
        from .raw_store import SupabaseStorageRawStore
        creds = ProviderCreds.from_env()
        raw_store = SupabaseStorageRawStore(StorageConfig.from_env())

        def provider_factory(ctx: ManifestContext):
            return HttpMapsProvider(creds, ctx.post_endpoint, ctx.get_endpoint)

        runner = AioProbeRunner(
            conn, provider_factory=provider_factory, raw_store=raw_store,
            wave_code=args.wave_code, methodology_code=args.methodology,
            calculate_rectangles=not args.no_rectangles, mode=args.mode)
        run = runner.run(specs)
        report = summarize_capture(conn, runner.wave_code)
        print(json.dumps({"run": run.summary(), "report": report}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
