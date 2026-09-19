"""Decoupled (two-phase) panel runner for the AIO surface (ADR-0008, Stage 2).

The graduated first AIO wave rode ``pilot.PilotRunner`` — one synchronous
``task_post`` -> poll ``task_get`` per job. That is fine at ~30 tasks but does not
scale to the full 25×50 × 10-condition × 13-point AIO panel (~148,750 executable):
each job blocks on the async AI-Overview load before the next starts. This runner
reuses DataForSEO's Standard **decoupled** method exactly as the Maps/Organic Full
Panel does — batch ``task_post`` (≤100/POST) then collect each task by its stored
``provider_task_id`` — by SUBCLASSING the validated ``panel_run.PanelRunner`` and
overriding only the surface-specific seams. There is NO parallel per-surface
collection stack (parent-PRD architecture rule): the submit/collect/reconcile
machinery, the water gate, the one-paid-task-per-job idempotency, the parallel
cell-partitioned collect, and the QA evaluator are all inherited unchanged.

AIO-specific overrides:
  * wave kind is ``ad_hoc`` (AIO has no committed cadence in ops.wave_kind) and the
    wave-code prefix is ``AIO`` (the driver passes an explicit monthly code);
  * the manifest context resolves against the ``AIO_QUERY_V1`` treatment set;
  * the request sets ``load_async_ai_overview`` so a triggered standalone AIO's
    markdown + references are returned (DFS_AIO_V2, migration 025);
  * the scientific back half is the two-track ``spike.finalize_aio`` — ONE
    observation carrying both the ``ai_overview`` subtree (``aio.*``) and the
    co-returned organic + Local-Pack context. KG-MID / web-entity split-safety
    under parallel collect is handled inside ``finalize_aio`` (ordered web-then-
    business advisory pre-locks), the same guarantee the pilot AIO path proved.

Makes no paid call on its own: providers are injected and replaced by fakes offline
(scripts/validate_aio_panel_run.py). The paid CLI + ``RUN_PAID_AIO`` gate live in
``aio_driver``.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Optional

from . import aio_run
from .dataforseo import MAX_TASKS_PER_POST
from .models import ManifestContext
from .panel_run import PanelRunner, _Pending
from .raw_store import RawStore
from .repository import Repo
from .spike import (
    COLLECTOR_VERSION,
    PARSER_VERSION_AIO,
    PARSER_VERSION_ORGANIC,
    RESOLVER_VERSION_AIO,
    RESOLVER_VERSION_ORGANIC,
    build_request,
    finalize_aio,
)


class AioPanelRunner(PanelRunner):
    """Two-phase decoupled AIO collection runner (see module docstring)."""

    def __init__(
        self,
        conn,
        *,
        batch_provider_factory: Callable[[ManifestContext], Any],
        raw_store: RawStore,
        methodology_code: str = "MANIFEST_V1_0",
        wave_code: Optional[str] = None,
        batch_size: int = MAX_TASKS_PER_POST,
        poll_interval_s: float = 5.0,
        collect_timeout_s: float = 3600.0,
        sleep: Callable[[float], None] = time.sleep,
        max_workers: int = 1,
        conn_factory: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(
            conn, batch_provider_factory=batch_provider_factory, raw_store=raw_store,
            kind=aio_run.AIO_WAVE_KIND, methodology_code=methodology_code, wave_code=wave_code,
            batch_size=batch_size, poll_interval_s=poll_interval_s,
            collect_timeout_s=collect_timeout_s, sleep=sleep, max_workers=max_workers,
            conn_factory=conn_factory)
        # Resolve each AIO job's context against the AIO_QUERY_V1 treatment set.
        self._treatment_set = aio_run.AIO_TREATMENT_SET
        # The AIO two-track finalize needs organic parser/resolver versions in
        # addition to the aio ones cached by the base _versions maps.
        self._parser_org_cv: dict[str, str] = {}
        self._resolver_org_cv: dict[str, str] = {}

    # ---- surface hooks ----
    def _allowed_kinds(self) -> tuple[str, ...]:
        return (aio_run.AIO_WAVE_KIND,)  # 'ad_hoc'

    def _wave_prefix(self) -> str:
        return aio_run.AIO_WAVE_PREFIX  # 'AIO'

    def _build_request(self, ctx: ManifestContext) -> dict[str, Any]:
        # DFS_AIO_V2 rides the organic endpoint; request the async AIO body so a
        # standalone AI Overview's markdown + references (and rectangles) come back.
        return build_request(ctx, load_async_ai_overview=True)

    def _versions(self, surface: str) -> tuple[str, str, str]:
        """Register + cache the AIO component versions. Returns (collector, parser_aio,
        resolver_aio) for base-class compatibility; the organic-track versions the
        two-track finalize also needs are cached separately (_finalize reads them)."""
        if surface not in self._collector_cv:
            self._collector_cv[surface] = self.repo.component_version(
                "collector", "aio-panel", COLLECTOR_VERSION)
            self._parser_cv[surface] = self.repo.component_version(
                "parser", "aio-organic-overview", PARSER_VERSION_AIO)
            self._resolver_cv[surface] = self.repo.component_version(
                "resolver", "aio-normalizer", RESOLVER_VERSION_AIO)
            self._parser_org_cv[surface] = self.repo.component_version(
                "parser", "organic-advanced", PARSER_VERSION_ORGANIC)
            self._resolver_org_cv[surface] = self.repo.component_version(
                "resolver", "web-url-first", RESOLVER_VERSION_ORGANIC)
        return self._collector_cv[surface], self._parser_cv[surface], self._resolver_cv[surface]

    def _finalize(self, conn, repo: Repo, p: _Pending, *, get_json: dict[str, Any],
                  get_payload_id: str, received: datetime) -> dict[str, Any]:
        self._versions(p.surface)  # ensure both tracks' versions are registered/cached
        return finalize_aio(
            conn, ctx=p.ctx, job_id=p.job_id, attempt_id=p.attempt_id, wave_id=self._wave_id,
            provider_task_id=p.task_id, get_json=get_json, get_payload_id=get_payload_id,
            received=received,
            parser_cv_aio=self._parser_cv[p.surface], parser_cv_organic=self._parser_org_cv[p.surface],
            resolver_cv_aio=self._resolver_cv[p.surface], resolver_cv_organic=self._resolver_org_cv[p.surface],
            graph_release=self._graph_release, wave_code=self.wave_code, jkey=p.jkey,
            cost_purpose=f"{p.surface}_panel_task")
