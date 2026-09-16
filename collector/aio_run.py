"""AIO (organic AI Overview) collection matrix + runner factory (ADR-0008, Stage 2).

The AIO surface of record is the AI Overview embedded in the organic SERP
(`DFS_AIO_V2`). Its per-job primitive is the validated single-coordinate path
`spike.run_spike`, which for the `aio` surface dispatches to `spike.finalize_aio`
(two-track: the `ai_overview` subtree into `aio.*` + the co-returned organic +
Local Pack context under one observation). This module supplies the AIO job matrix
and a thin factory that reuses the SAME validated wave runner as the Maps/Organic
pilot (`pilot.PilotRunner`) — there is NO parallel per-surface collection stack
(parent PRD architecture rule). The gated cadence CLI lives in `aio_driver.py`.

Geometry/conditions are the frozen Manifest v1.0 AIO identifiers (`AIO9_V1`,
`AIO_QUERY_V1`); nothing here changes the universe. The GRADUATED default scope is
deliberately small — the 3×5 pilot cells at the geometry CENTER for the two core
query families — so the first paid AIO wave is a cautious, cheap measurement (it
confirms the `load_async_ai_overview` add-on billing before any wider run), exactly
as Maps/Organic graduated Sentinel-first. Widening to the full 9-point × 10-condition
25×50 AIO panel is future scope with its own owner go/no-go.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .models import ManifestContext
from .pilot import PILOT_INDUSTRIES, PILOT_MARKETS, PilotJobSpec, PilotRunner
from .raw_store import RawStore

# Frozen Manifest v1.0 AIO identifiers.
AIO_SURFACE = "aio"
AIO_TREATMENT_SET = "AIO_QUERY_V1"
# AIO9_V1 geometry: center + N/E/S/W @2.5mi + @5mi (9 points).
AIO_POINTS_9 = ["C", "N2P5", "E2P5", "S2P5", "W2P5", "N5", "E5", "S5", "W5"]
# The 10 locked AIO conditions (AIO_QUERY_V1). AIO_C01 = core near-me,
# AIO_C04 = core explicit-[CITY]; the two query families the AIO PRD §8 makes
# first-class, and the graduated first-run subset.
AIO_CONDITIONS_ALL = [f"AIO_C{n:02d}" for n in range(1, 11)]
AIO_GRADUATED_CONDITIONS = ["AIO_C01", "AIO_C04"]
AIO_GRADUATED_POINTS = ["C"]

AIO_COMPONENT_NAME = "aio-collect"
AIO_WAVE_KIND = "ad_hoc"          # ops.wave_kind: AIO has no committed cadence yet (future scope)
AIO_WAVE_PREFIX = "AIO"


def expand_aio_matrix(
    *,
    industries: Optional[list[str]] = None,
    markets: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    points: Optional[list[str]] = None,
) -> list[PilotJobSpec]:
    """Deterministic AIO job matrix in job-generator v0.7 order (industry -> market
    -> surface -> condition -> point) on the `aio` surface. Defaults are the
    GRADUATED first-run scope (3×5 pilot cells, center point, the two core query
    families); filters widen or narrow it without changing the ordering."""
    industries = industries or PILOT_INDUSTRIES
    markets = markets or PILOT_MARKETS
    conditions = conditions or AIO_GRADUATED_CONDITIONS
    points = points or AIO_GRADUATED_POINTS
    out: list[PilotJobSpec] = []
    for industry in industries:
        for market in markets:
            for condition in conditions:
                for point in points:
                    out.append(PilotJobSpec(AIO_SURFACE, industry, market, condition, point))
    return out


def build_aio_runner(
    conn,
    *,
    provider_factory: Callable[[ManifestContext], Any],
    raw_store: RawStore,
    wave_code: Optional[str] = None,
    methodology_code: str = "MANIFEST_V1_0",
    max_retries: int = 3,
    max_workers: int = 1,
    conn_factory: Optional[Callable[[], Any]] = None,
) -> PilotRunner:
    """Construct the shared `PilotRunner` parametrized for the AIO surface: the
    `AIO_QUERY_V1` treatment set, an `ad_hoc` wave kind, and the AIO component /
    wave-code prefix. Concurrency is still partitioned by (industry, market,
    surface) — cell affinity — so an AIO business keyed on a market-local
    Knowledge-Graph MID is single-writer per cell (same guarantee the Maps
    place_id path relies on); web sources that recur across cells stay race-safe in
    the repository's advisory-locked web-entity creation."""
    return PilotRunner(
        conn, provider_factory=provider_factory, raw_store=raw_store,
        wave_code=wave_code, methodology_code=methodology_code,
        max_retries=max_retries, max_workers=max_workers, conn_factory=conn_factory,
        treatment_set_code=AIO_TREATMENT_SET, wave_kind=AIO_WAVE_KIND,
        component_name=AIO_COMPONENT_NAME, wave_code_prefix=AIO_WAVE_PREFIX)
