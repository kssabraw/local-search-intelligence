"""Two-phase decoupled panel runner (ADR-0007, design doc step 2).

The pilot's ``PilotRunner`` drives one synchronous ``task_post`` -> poll
``task_get`` per job. That does not scale to the Full Panel (~118,000 executable
Maps+Organic jobs). This runner uses DataForSEO's Standard **decoupled** method:

  submit phase  -- water-gate, then batch ``task_post`` (<=100 tasks/POST),
                   persisting one paid task per job (attempt.provider_task_id);
  collect phase -- poll the per-surface ``tasks_ready`` roster and pull each ready
                   task with ``task_get_advanced``, then drive the SHARED
                   scientific back half (``spike.finalize_collected``) --
                   immutable raw -> parse -> normalize -> resolve -> cost;
  reconcile     -- any submitted task never seen ready within the collect window
                   is recorded as an accounted terminal_failure (resumable),
                   never re-POSTed.

Guardrails preserved verbatim from the validated pilot path:
  * immutable append-only raw stored before normalization (fail-on-exists);
  * missing != zero -- structural coordinates are gated out before submission and
    recorded ``blocked_structural`` (planned = executable + structurally_excluded);
  * ONE paid task per scientific job -- idempotency is at submission: a job that
    already has a committed observation is skipped, and a job that already carries
    a submitted ``provider_task_id`` is collect-only on resume (never re-POSTed);
  * a valid short/empty result is a real observation, never retried for a
    "better" one; the QA evaluator (``pilot.evaluate_wave``) is reused unchanged.

This module makes no paid call on its own: providers are injected and replaced by
fakes offline (scripts/validate_panel_run.py, tests). The paid CLI + the
``RUN_PAID_PANEL`` gate + cadence live in the driver (design doc step 3).
"""
from __future__ import annotations

import dataclasses
import time
from datetime import datetime
from typing import Any, Callable, Optional

from . import panel, pilot
from .dataforseo import MAX_TASKS_PER_POST
from .models import ManifestContext
from .pilot import PilotJobSpec
from .raw_store import RawStore
from .repository import Repo, utcnow
from .spike import (
    COLLECTOR_VERSION,
    PARSER_VERSION_MAPS,
    PARSER_VERSION_ORGANIC,
    RESOLVER_VERSION_MAPS,
    RESOLVER_VERSION_ORGANIC,
    build_request,
    finalize_collected,
    usd_to_microusd,
)

VALID_OBSERVATION_STATES = pilot.PILOT_VALID_OBSERVATION_STATES
BatchProviderFactory = Callable[[ManifestContext], Any]


@dataclasses.dataclass
class _Pending:
    """A submitted paid task awaiting collection."""
    task_id: str
    surface: str
    ctx: ManifestContext
    job_id: str
    attempt_id: str
    jkey: str
    spec: PilotJobSpec


@dataclasses.dataclass
class _BatchEntry:
    """A planned, request-raw-stored job awaiting its batched POST."""
    ctx: ManifestContext
    job_id: str
    jkey: str
    request: dict[str, Any]
    req_payload_id: str
    spec: PilotJobSpec


@dataclasses.dataclass
class PanelRunResult:
    wave_code: str
    wave_id: str
    kind: str
    planned: int = 0
    executable: int = 0
    structurally_excluded: int = 0
    submitted: int = 0
    resumed_pending: int = 0
    already_observed: int = 0
    collected: int = 0
    valid_returned: int = 0
    submit_failures: int = 0
    collect_timeouts: int = 0
    total_cost_microusd: int = 0

    def summary(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class PanelRunner:
    def __init__(
        self,
        conn,
        *,
        batch_provider_factory: BatchProviderFactory,
        raw_store: RawStore,
        kind: str,
        methodology_code: str = "MANIFEST_V1_0",
        wave_code: Optional[str] = None,
        batch_size: int = MAX_TASKS_PER_POST,
        poll_interval_s: float = 5.0,
        collect_timeout_s: float = 3600.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if kind not in panel.WAVE_KINDS:
            raise ValueError(f"unknown wave kind {kind!r}; expected one of {panel.WAVE_KINDS}")
        if not 1 <= batch_size <= MAX_TASKS_PER_POST:
            raise ValueError(f"batch_size must be 1..{MAX_TASKS_PER_POST}, got {batch_size}")
        self.conn = conn
        self.repo = Repo(conn)
        self.batch_provider_factory = batch_provider_factory
        self.raw_store = raw_store
        self.kind = kind
        self.methodology_code = methodology_code
        self.batch_size = batch_size
        self.poll_interval_s = poll_interval_s
        self.collect_timeout_s = collect_timeout_s
        self.sleep = sleep
        self._now: datetime = utcnow()
        prefix = "FULLPANEL" if kind == panel.FULL_PANEL else "SENTINEL"
        self.wave_code = wave_code or f"{prefix}-{self._now:%Y%m%dT%H%M%S}"
        self._wave_id: Optional[str] = None
        self._mv_id: Optional[str] = None
        # per-surface caches
        self._collector_cv: dict[str, str] = {}
        self._parser_cv: dict[str, str] = {}
        self._resolver_cv: dict[str, str] = {}
        self._graph_release: Optional[str] = None
        self._surface_ctx: dict[str, ManifestContext] = {}
        self._surface_provider: dict[str, Any] = {}

    # ---- setup ----
    def setup(self) -> str:
        row = self.conn.execute(
            "select methodology_version_id from manifest.methodology_version where methodology_code=%s",
            (self.methodology_code,),
        ).fetchone()
        if row is None:
            raise LookupError(f"unknown methodology_code {self.methodology_code}")
        self._mv_id = row[0]
        subset_id = None
        if self.kind == panel.SENTINEL:
            subset_id = self.repo.panel_subset_id(
                methodology_version_id=self._mv_id, subset_code=panel.SENTINEL_SUBSET_CODE)
            if subset_id is None:
                raise LookupError(f"panel subset {panel.SENTINEL_SUBSET_CODE} not seeded")
        self._wave_id = self.repo.get_or_create_wave(
            methodology_version_id=self._mv_id, wave_code=self.wave_code,
            wave_kind=self.kind, scheduled_for=self._now, panel_subset_id=subset_id)
        self._graph_release = self.repo.entity_graph_release(
            f"panel-{self.methodology_code}", self._mv_id)
        self.conn.commit()
        return self._wave_id

    def _versions(self, surface: str) -> tuple[str, str, str]:
        if surface not in self._collector_cv:
            is_org = surface == "organic"
            self._collector_cv[surface] = self.repo.component_version(
                "collector", f"{surface}-panel", COLLECTOR_VERSION)
            self._parser_cv[surface] = self.repo.component_version(
                "parser", "organic-advanced" if is_org else "maps-advanced",
                PARSER_VERSION_ORGANIC if is_org else PARSER_VERSION_MAPS)
            self._resolver_cv[surface] = self.repo.component_version(
                "resolver", "web-url-first" if is_org else "place-id-first",
                RESOLVER_VERSION_ORGANIC if is_org else RESOLVER_VERSION_MAPS)
        return self._collector_cv[surface], self._parser_cv[surface], self._resolver_cv[surface]

    def _ctx(self, spec: PilotJobSpec) -> ManifestContext:
        return self.repo.load_manifest_context(
            methodology_code=self.methodology_code, surface_code=spec.surface,
            industry_code=spec.industry, market_code=spec.market, point_code=spec.point,
            treatment_set_code=panel.TREATMENT_SET, treatment_code=spec.treatment)

    def _provider_for(self, surface: str) -> Any:
        if surface not in self._surface_provider:
            self._surface_provider[surface] = self.batch_provider_factory(self._surface_ctx[surface])
        return self._surface_provider[surface]

    # ---- submit phase ----
    def _existing_submitted_attempt(self, job_id: str) -> Optional[tuple[str, str]]:
        """(attempt_id, provider_task_id) if this job already has a submitted paid
        task (resume: collect-only, never re-POST)."""
        row = self.conn.execute(
            "select attempt_id, provider_task_id from ops.collection_attempt "
            "where job_id=%s and provider_task_id is not null order by attempt_no desc limit 1",
            (job_id,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def _record_excluded(self, spec: PilotJobSpec, ctx: ManifestContext) -> None:
        request = build_request(ctx)
        collector_cv, _, _ = self._versions(spec.surface)
        job_id, _, _ = self.repo.plan_job(
            ctx=ctx, wave_id=self._wave_id, replicate_no=1,
            rendered_input_text=request["keyword"], rendered_request=request, generated_by=collector_cv)
        already = self.conn.execute(
            "select 1 from ops.job_event where job_id=%s and status='blocked_structural'",
            (job_id,),
        ).fetchone() is not None
        if not already:
            self.repo.job_event(job_id, "blocked_structural", reason_code=ctx.eligibility)

    def submit_phase(self, specs: list[PilotJobSpec], res: PanelRunResult) -> list[_Pending]:
        pending: list[_Pending] = []
        # group by surface (batching is per-surface: distinct endpoints/rosters)
        by_surface: dict[str, list[PilotJobSpec]] = {}
        for s in specs:
            by_surface.setdefault(s.surface, []).append(s)

        for surface, surface_specs in by_surface.items():
            batch: list[_BatchEntry] = []
            for spec in surface_specs:
                res.planned += 1
                ctx = self._ctx(spec)
                self._surface_ctx.setdefault(surface, ctx)
                if ctx.eligibility != "eligible_land":
                    self._record_excluded(spec, ctx)
                    self.conn.commit()
                    res.structurally_excluded += 1
                    continue
                res.executable += 1
                collector_cv, _, _ = self._versions(surface)
                request = build_request(ctx)
                job_id, jkey, obs_exists = self.repo.plan_job(
                    ctx=ctx, wave_id=self._wave_id, replicate_no=1,
                    rendered_input_text=request["keyword"], rendered_request=request,
                    generated_by=collector_cv)
                if obs_exists:
                    self.conn.commit()
                    res.already_observed += 1
                    continue
                prior = self._existing_submitted_attempt(job_id)
                if prior:
                    # already submitted on a previous run -> collect only, never re-POST
                    attempt_id, task_id = prior
                    self.conn.commit()
                    pending.append(_Pending(task_id, surface, ctx, job_id, attempt_id, jkey, spec))
                    res.resumed_pending += 1
                    continue
                self.repo.job_event(job_id, "planned", actor="collector.panel")
                req_payload_id = self._store_request_raw(ctx, request)
                batch.append(_BatchEntry(ctx, job_id, jkey, request, req_payload_id, spec))
                if len(batch) >= self.batch_size:
                    self._post_batch(surface, batch, pending, res)
                    batch = []
            if batch:
                self._post_batch(surface, batch, pending, res)
        return pending

    def _store_request_raw(self, ctx: ManifestContext, request: dict[str, Any]) -> str:
        import json
        req_bytes = json.dumps([request], sort_keys=True).encode()
        blob = self.raw_store.put(surface_code=ctx.surface_code, payload_kind="request", raw_bytes=req_bytes)
        blob_id = self.repo.raw_blob(sha256=blob.sha256, bucket=blob.bucket, path=blob.path,
                                     byte_size=blob.byte_size, mime_type=blob.mime_type,
                                     content_encoding=blob.content_encoding)
        return self.repo.provider_payload(provider_id=ctx.provider_id, blob_id=blob_id,
                                          payload_kind="request", provider_task_id=None, captured_at=utcnow())

    def _post_batch(self, surface: str, batch: list[_BatchEntry],
                    pending: list[_Pending], res: PanelRunResult) -> None:
        """One batched paid POST (<=100 tasks). Persists a paid task per job."""
        provider = self._provider_for(surface)
        collector_cv, _, _ = self._versions(surface)
        data, post_bytes, task_ids = provider.task_post_batch([e.request for e in batch])
        # the shared batch post-response is stored once (content-addressed) and
        # referenced by every task's provider_acknowledged event.
        post_blob = self.raw_store.put(surface_code=surface, payload_kind="task_post_response", raw_bytes=post_bytes)
        post_blob_id = self.repo.raw_blob(sha256=post_blob.sha256, bucket=post_blob.bucket, path=post_blob.path,
                                          byte_size=post_blob.byte_size, mime_type=post_blob.mime_type,
                                          content_encoding=post_blob.content_encoding)
        first_ctx = batch[0].ctx
        post_payload_id = self.repo.provider_payload(
            provider_id=first_ctx.provider_id, blob_id=post_blob_id, payload_kind="task_post_response",
            provider_task_id=None, captured_at=utcnow())
        tasks = data.get("tasks") or []
        for i, (entry, task_id) in enumerate(zip(batch, task_ids)):
            status = str((tasks[i] or {}).get("status_code")) if i < len(tasks) else None
            attempt_id = self.repo.attempt(
                job_id=entry.job_id, attempt_no=1, provider_id=entry.ctx.provider_id,
                provider_task_id=task_id, request_payload_id=entry.req_payload_id,
                submitted_at=utcnow(), collector_cv=collector_cv)
            self.repo.attempt_event(attempt_id=attempt_id, event_type="submitted")
            self.repo.attempt_event(attempt_id=attempt_id, event_type="provider_acknowledged",
                                    response_payload_id=post_payload_id, provider_status_code=status)
            self.repo.job_event(entry.job_id, "submitted", attempt_no=1, actor="collector.panel",
                                details={"provider_task_id": task_id})
            if not task_id:
                # per-task rejection at submission (e.g. 40xxx, no id): accounted
                # terminal_failure, no paid task to collect.
                self.repo.attempt_event(attempt_id=attempt_id, event_type="terminal_failure",
                                        provider_status_code=status, error_code="task_not_created")
                self.repo.job_event(entry.job_id, "terminal_failure", attempt_no=1,
                                    actor="collector.panel", reason_code="task_not_created")
                res.submit_failures += 1
            else:
                pending.append(_Pending(task_id, surface, entry.ctx, entry.job_id, attempt_id, entry.jkey, entry.spec))
                res.submitted += 1
        self.conn.commit()

    # ---- collect phase ----
    def collect_phase(self, pending: list[_Pending], res: PanelRunResult) -> list[_Pending]:
        by_task: dict[str, _Pending] = {p.task_id: p for p in pending}
        surfaces = sorted({p.surface for p in pending})
        deadline = time.monotonic() + self.collect_timeout_s
        while by_task and time.monotonic() < deadline:
            progressed = False
            for surface in surfaces:
                if not any(p.surface == surface for p in by_task.values()):
                    continue
                provider = self._provider_for(surface)
                _, _, ready_ids = provider.tasks_ready()
                for tid in ready_ids:
                    p = by_task.get(tid)
                    if p is None:  # a ready task from another wave -- not ours
                        continue
                    self._collect_one(p, provider, res)
                    del by_task[tid]
                    progressed = True
            if by_task and not progressed:
                self.sleep(self.poll_interval_s)
        return list(by_task.values())

    def _collect_one(self, p: _Pending, provider: Any, res: PanelRunResult) -> None:
        _, parser_cv, resolver_cv = self._versions(p.surface)
        get_json, get_bytes = provider.task_get_advanced(p.task_id)
        received = utcnow()
        blob = self.raw_store.put(surface_code=p.surface, payload_kind="task_get_response", raw_bytes=get_bytes)
        blob_id = self.repo.raw_blob(sha256=blob.sha256, bucket=blob.bucket, path=blob.path,
                                     byte_size=blob.byte_size, mime_type=blob.mime_type,
                                     content_encoding=blob.content_encoding)
        get_payload_id = self.repo.provider_payload(
            provider_id=p.ctx.provider_id, blob_id=blob_id, payload_kind="task_get_response",
            provider_task_id=p.task_id, captured_at=received)
        self.repo.attempt_event(attempt_id=p.attempt_id, event_type="response_received",
                                response_payload_id=get_payload_id)
        out = finalize_collected(
            self.conn, ctx=p.ctx, job_id=p.job_id, attempt_id=p.attempt_id, wave_id=self._wave_id,
            provider_task_id=p.task_id, get_json=get_json, get_payload_id=get_payload_id,
            received=received, parser_cv=parser_cv, resolver_cv=resolver_cv,
            graph_release=self._graph_release, wave_code=self.wave_code, jkey=p.jkey,
            cost_purpose=f"{p.surface}_{self.kind}_task")
        self.conn.commit()
        res.collected += 1
        if out.get("observation_state") in VALID_OBSERVATION_STATES:
            res.valid_returned += 1
        res.total_cost_microusd += usd_to_microusd(out.get("provider_cost_usd"))

    # ---- reconcile ----
    def reconcile(self, leftover: list[_Pending], res: PanelRunResult) -> None:
        for p in leftover:
            self.repo.attempt_event(attempt_id=p.attempt_id, event_type="terminal_failure",
                                    error_code="collect_timeout")
            self.repo.job_event(p.job_id, "terminal_failure", attempt_no=1, actor="collector.panel",
                                reason_code="collect_timeout",
                                details={"provider_task_id": p.task_id, "detail": "not ready within collect window"})
            self.conn.commit()
            res.collect_timeouts += 1

    # ---- orchestration ----
    def run(self, specs: list[PilotJobSpec]) -> PanelRunResult:
        if self._wave_id is None:
            self.setup()
        res = PanelRunResult(wave_code=self.wave_code, wave_id=str(self._wave_id), kind=self.kind)
        pending = self.submit_phase(specs, res)
        leftover = self.collect_phase(pending, res)
        if leftover:
            self.reconcile(leftover, res)
        return res
