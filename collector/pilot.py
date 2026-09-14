"""Stage-1 bounded 3x5 Maps+Organic pilot batch run harness.

The single-coordinate `collector.spike` is the proven per-job primitive
(immutable raw -> parse -> normalize -> resolve -> cost). This module iterates
the *frozen v1.0 executable job matrix* for the bounded pilot and drives one
`run_spike` per executable job, with:

  * deterministic matrix expansion in the job-generator v0.7 generation order
    (industry -> market -> surface -> condition/treatment -> point);
  * the water gate: a coordinate whose eligibility != 'eligible_land' is NEVER
    submitted to the provider (structural missingness is not zero, COL008 /
    PRE009). It is still recorded as a planned, `blocked_structural` job so the
    denominator reconciles (planned = executable + structurally_excluded);
  * deterministic idempotency (the existing `job_key` + the observation
    short-circuit in `run_spike`): a re-run resumes and never re-pays;
  * bounded retries for transport/provider-infra failures only; a valid
    short/empty result (e.g. DFS 40102) is a real observation, never retried;
  * a QA / Wave-Acceptance v0.1 evaluator that reads back from the DB and emits
    COMPLETE / PARTIAL / FAILED / QUARANTINED plus a separate financial block.

Matrix (frozen Manifest v1.0):
  3 industries x 5 markets x 4 queries x 13 points x 2 surfaces = 1,560 jobs
  pre-water; after the water gate 1,368 are executable (57 eligible coordinates
  x 3 industries x 4 queries x 2 surfaces) and 192 are structurally excluded.

The LIVE run makes real PAID DataForSEO calls and is gated: nothing here calls a
provider unless `--execute` is passed, and the Railway path additionally gates on
`RUN_PAID_PILOT=1`. Offline (`--dry-run`, tests, scripts/validate_pilot.py) uses
fakes and never touches the network.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import datetime
from typing import Any, Callable, Optional

from .models import ManifestContext
from .raw_store import RawStore, RawStoreError
from .repository import Repo, utcnow
from .spike import (
    COLLECTOR_VERSION,
    build_request,
    render_keyword,
    run_spike,
)

# ---------------------------------------------------------------------------
# Frozen pilot universe (Stage-1). These are the CLAUDE.md pilot cells; the
# geometry/treatment codes are the frozen Manifest v1.0 identifiers.
# ---------------------------------------------------------------------------
PILOT_INDUSTRIES = ["IND010", "IND019", "IND022"]          # Locksmith, Urgent Care, Chinese Restaurant
PILOT_MARKETS = ["MKT008", "MKT011", "MKT021", "MKT040", "MKT049"]
PILOT_SURFACES = ["maps", "organic"]
PILOT_TREATMENTS = ["Q1", "Q2", "Q3", "Q4"]                 # GOOGLE_QUERY_V1 (Q4 = [CITY])
PILOT_TREATMENT_SET = "GOOGLE_QUERY_V1"
# MAPORG13_V1 geometry: center + 1mi/3mi/5mi rings (N/E/S/W).
PILOT_POINTS = ["C", "N1", "E1", "S1", "W1", "N3", "E3", "S3", "W3", "N5", "E5", "S5", "W5"]

PILOT_COMPONENT_NAME = "pilot-3x5-maporg"
PILOT_VALID_OBSERVATION_STATES = (
    "returned", "refusal", "clarification_requested",
    "generic_guidance_only", "no_local_recommendations", "other",
)
QA_CONTRACT_CODE = "SED_WAVE_QA"
QA_CONTRACT_VERSION = "0.1"


@dataclasses.dataclass(frozen=True)
class PilotJobSpec:
    """One addressable cell of the executable job matrix (pre-water)."""
    surface: str
    industry: str
    market: str
    treatment: str
    point: str

    @property
    def label(self) -> str:
        return f"{self.surface}:{self.industry}:{self.market}:{self.treatment}:{self.point}"


def expand_matrix(
    *,
    industries: Optional[list[str]] = None,
    markets: Optional[list[str]] = None,
    surfaces: Optional[list[str]] = None,
    treatments: Optional[list[str]] = None,
    points: Optional[list[str]] = None,
) -> list[PilotJobSpec]:
    """Deterministic pre-water matrix in the job-generator v0.7 generation order:
    industry -> market -> surface -> condition(treatment) -> point.

    Filters narrow the pilot (e.g. one cell for a cautious first paid batch) but
    never change the ordering or the frozen defaults.
    """
    industries = industries or PILOT_INDUSTRIES
    markets = markets or PILOT_MARKETS
    surfaces = surfaces or PILOT_SURFACES
    treatments = treatments or PILOT_TREATMENTS
    points = points or PILOT_POINTS
    out: list[PilotJobSpec] = []
    for industry in industries:
        for market in markets:
            for surface in surfaces:
                for treatment in treatments:
                    for point in points:
                        out.append(PilotJobSpec(surface, industry, market, treatment, point))
    return out


# ---------------------------------------------------------------------------
# Retry classification: transport / provider-infra failures are retryable; a
# valid short/empty observation is never a failure and never reaches here.
# ---------------------------------------------------------------------------
_RETRYABLE_MARKERS = (
    "timeout", "timed out", "connection", "connect", "reset", "temporarily",
    "read error", "write error", "eof", "broken pipe", "502", "503", "504",
    "not ready within",  # HttpMapsProvider poll timeout (ProviderError)
)


def is_retryable(exc: BaseException) -> bool:
    """True for transport/provider-infra errors safe to retry as a NEW technical
    attempt of the SAME job (never a new paid scientific call for an already
    terminal observation). A storage/DB integrity error is NOT retryable."""
    if isinstance(exc, RawStoreError):
        return False
    name = type(exc).__name__.lower()
    if "timeout" in name or "connect" in name or ("network" in name):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _RETRYABLE_MARKERS)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
ProviderFactory = Callable[[ManifestContext], Any]


@dataclasses.dataclass
class PilotRunResult:
    wave_code: str
    wave_id: str
    planned: int
    executable: int
    structurally_excluded: int
    collected: int
    already_observed: int
    valid_returned: int
    technical_failures: int
    excluded_recorded: int
    total_cost_microusd: int
    per_job: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d.pop("per_job", None)
        return d


class PilotRunner:
    """Drives the executable matrix under one pilot wave.

    Dependencies are injected: `provider_factory(ctx)` yields a provider for a
    job's surface (a fake offline, the real HTTP client live), `raw_store` is the
    immutable raw sink. Nothing here reaches the network unless the injected
    dependencies do.
    """

    def __init__(
        self,
        conn,
        *,
        provider_factory: ProviderFactory,
        raw_store: RawStore,
        wave_code: Optional[str] = None,
        methodology_code: str = "MANIFEST_V1_0",
        max_retries: int = 3,
        backoff_base_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.conn = conn
        self.repo = Repo(conn)
        self.provider_factory = provider_factory
        self.raw_store = raw_store
        self.methodology_code = methodology_code
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.sleep = sleep
        self._now: datetime = utcnow()
        self.wave_code = wave_code or f"PILOT-3x5-{self._now:%Y%m%dT%H%M%S}"
        self._wave_id: Optional[str] = None
        self._collector_cv: Optional[str] = None

    # -- setup: pre-create the pilot wave (kind='pilot') so every job shares it --
    def setup(self) -> str:
        row = self.conn.execute(
            "select methodology_version_id from manifest.methodology_version where methodology_code=%s",
            (self.methodology_code,),
        ).fetchone()
        if row is None:
            raise LookupError(f"unknown methodology_code {self.methodology_code}")
        mv_id = row[0]
        self._wave_id = self.repo.get_or_create_wave(
            methodology_version_id=mv_id, wave_code=self.wave_code,
            wave_kind="pilot", scheduled_for=self._now)
        self._collector_cv = self.repo.component_version(
            "collector", PILOT_COMPONENT_NAME, COLLECTOR_VERSION)
        self.conn.commit()
        return self._wave_id

    def _resolve_ctx(self, spec: PilotJobSpec) -> ManifestContext:
        return self.repo.load_manifest_context(
            methodology_code=self.methodology_code, surface_code=spec.surface,
            industry_code=spec.industry, market_code=spec.market, point_code=spec.point,
            treatment_set_code=PILOT_TREATMENT_SET, treatment_code=spec.treatment)

    def _record_excluded(self, spec: PilotJobSpec, ctx: ManifestContext) -> dict[str, Any]:
        """Structural missingness: plan the job as provenance, never submit it."""
        request = build_request(ctx)
        job_id, jkey, observation_exists = self.repo.plan_job(
            ctx=ctx, wave_id=self._wave_id, replicate_no=1,
            rendered_input_text=request["keyword"], rendered_request=request,
            generated_by=self._collector_cv)
        # Emit a terminal, accounted, non-executed state exactly once.
        already = self.conn.execute(
            "select 1 from ops.job_event where job_id=%s and status='blocked_structural'",
            (job_id,),
        ).fetchone() is not None
        if not already:
            self.repo.job_event(job_id, "blocked_structural", reason_code=ctx.eligibility)
        self.conn.commit()
        return {"label": spec.label, "status": "structurally_excluded",
                "eligibility": ctx.eligibility, "job_id": str(job_id), "job_key": jkey,
                "observation_exists": observation_exists}

    def _run_one_executable(self, spec: PilotJobSpec, ctx: ManifestContext) -> dict[str, Any]:
        """One executable job with bounded retries. Each successful/terminal job is
        committed independently (resumable); a failed attempt is rolled back so no
        partial paid-call state persists before the retry."""
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.max_retries + 1):
            provider = self.provider_factory(ctx)
            try:
                result = run_spike(
                    self.conn, ctx=ctx, provider=provider, raw_store=self.raw_store,
                    wave_code=self.wave_code)
                self.conn.commit()
                result["label"] = spec.label
                result["attempts"] = attempt
                return result
            except Exception as exc:  # noqa: BLE001 - classify, don't swallow blindly
                self.conn.rollback()
                last_exc = exc
                if attempt < self.max_retries and is_retryable(exc):
                    self.sleep(self.backoff_base_s * (2 ** (attempt - 1)))
                    continue
                break
        # Retries exhausted or non-retryable: record an accounted terminal_failure
        # job (no observation) in a fresh transaction so the denominator reconciles.
        return self._record_terminal_failure(spec, ctx, last_exc)

    def _record_terminal_failure(self, spec: PilotJobSpec, ctx: ManifestContext,
                                 exc: Optional[BaseException]) -> dict[str, Any]:
        request = build_request(ctx)
        job_id, jkey, observation_exists = self.repo.plan_job(
            ctx=ctx, wave_id=self._wave_id, replicate_no=1,
            rendered_input_text=request["keyword"], rendered_request=request,
            generated_by=self._collector_cv)
        if observation_exists:
            # A prior attempt already produced a terminal observation -> accounted.
            self.conn.commit()
            return {"label": spec.label, "status": "already_observed", "job_id": str(job_id),
                    "job_key": jkey}
        reason = type(exc).__name__ if exc is not None else "unknown_error"
        self.repo.job_event(job_id, "terminal_failure", attempt_no=self.max_retries,
                            reason_code=reason)
        self.conn.commit()
        return {"label": spec.label, "status": "terminal_failure", "job_id": str(job_id),
                "job_key": jkey, "error": reason}

    def run(self, specs: list[PilotJobSpec]) -> PilotRunResult:
        if self._wave_id is None:
            self.setup()
        res = PilotRunResult(
            wave_code=self.wave_code, wave_id=str(self._wave_id), planned=0, executable=0,
            structurally_excluded=0, collected=0, already_observed=0, valid_returned=0,
            technical_failures=0, excluded_recorded=0, total_cost_microusd=0)
        for spec in specs:
            ctx = self._resolve_ctx(spec)
            res.planned += 1
            if ctx.eligibility != "eligible_land":
                out = self._record_excluded(spec, ctx)
                res.structurally_excluded += 1
                res.excluded_recorded += 1
                res.per_job.append(out)
                continue
            res.executable += 1
            out = self._run_one_executable(spec, ctx)
            status = out.get("status")
            if status == "collected":
                res.collected += 1
                if out.get("observation_state") in PILOT_VALID_OBSERVATION_STATES:
                    res.valid_returned += 1
                res.total_cost_microusd += _cost_microusd(out)
            elif status == "already_observed":
                res.already_observed += 1
            elif status == "terminal_failure":
                res.technical_failures += 1
            res.per_job.append(out)
        return res


def _cost_microusd(out: dict[str, Any]) -> int:
    usd = out.get("provider_cost_usd")
    return int(round((usd or 0.0) * 1_000_000))


# ---------------------------------------------------------------------------
# Dry-run planning (NO writes, NO provider calls)
# ---------------------------------------------------------------------------
def plan_dry_run(conn, specs: list[PilotJobSpec], *, methodology_code: str = "MANIFEST_V1_0") -> dict[str, Any]:
    """Resolve every spec, apply the water gate, render each request, and return
    the accounting. Rolls back so nothing is written; makes no provider call."""
    repo = Repo(conn)
    planned = executable = excluded = 0
    per_surface: dict[str, dict[str, int]] = {}
    per_stratum: dict[str, int] = {}
    conformity_failures: list[str] = []
    sample: list[dict[str, Any]] = []
    for spec in specs:
        ctx = repo.load_manifest_context(
            methodology_code=methodology_code, surface_code=spec.surface,
            industry_code=spec.industry, market_code=spec.market, point_code=spec.point,
            treatment_set_code=PILOT_TREATMENT_SET, treatment_code=spec.treatment)
        planned += 1
        surf = per_surface.setdefault(spec.surface, {"executable": 0, "excluded": 0})
        request = build_request(ctx)
        # PRE006 conformity: rendered keyword must equal the frozen template after
        # deterministic [CITY] substitution.
        expected_kw = render_keyword(ctx)
        if request["keyword"] != expected_kw:
            conformity_failures.append(spec.label)
        if ctx.eligibility != "eligible_land":
            excluded += 1
            surf["excluded"] += 1
            continue
        executable += 1
        surf["executable"] += 1
        stratum = f"{spec.industry}:{spec.market}:{spec.surface}"
        per_stratum[stratum] = per_stratum.get(stratum, 0) + 1
        if len(sample) < 6:
            sample.append({"label": spec.label, "keyword": request["keyword"],
                           "coordinate": ctx.coordinate_code,
                           "location_coordinate": request["location_coordinate"]})
    conn.rollback()
    return {
        "planned": planned, "executable": executable, "structurally_excluded": excluded,
        "per_surface": per_surface,
        "strata": len(per_stratum),
        "strata_under_20": {k: v for k, v in per_stratum.items() if v < 20},
        "conformity_failures": conformity_failures,
        "sample": sample,
    }


# ---------------------------------------------------------------------------
# QA / Wave-Acceptance v0.1 evaluator (step 9)
# ---------------------------------------------------------------------------
COMPLETE_THRESHOLDS = {
    "job_accounting_rate": 1.0,
    "valid_scientific_observation_rate_overall": 0.995,
    "valid_scientific_observation_rate_each_primary_surface": 0.99,
    "raw_payload_integrity_rate": 1.0,
    "critical_manifest_conformity_rate": 1.0,
    "normalization_parity_rate_overall": 0.995,
    "normalization_parity_rate_each_surface": 0.99,
    "resolution_state_coverage_rate": 0.995,
}
PARTIAL_MIN = {
    "job_accounting_rate": 1.0,
    "valid_scientific_observation_rate_overall": 0.97,
    "valid_scientific_observation_rate_each_primary_surface": 0.95,
    "raw_payload_integrity_rate": 1.0,
    "critical_manifest_conformity_rate": 1.0,
    "normalization_parity_rate_overall": 0.98,
    "normalization_parity_rate_each_surface": 0.97,
    "resolution_state_coverage_rate": 0.97,
}
STRATUM_MIN_EXECUTABLE = 20
STRATUM_PARTIAL_MIN = 0.95


def _rate(num: int, den: int) -> float:
    return 1.0 if den == 0 else num / den


def evaluate_wave(conn, wave_code: str, *, persist: bool = False,
                  evaluator_cv: Optional[str] = None) -> dict[str, Any]:
    """Read the wave back from the DB and evaluate it against QA/Wave-Acceptance
    v0.1. Returns the metrics + status; optionally writes ops.wave_evaluation and
    ops.qa_event rows. Pure read + append; never mutates observations."""
    wave_id = conn.execute(
        "select wave_id from ops.collection_wave where wave_code=%s", (wave_code,)
    ).fetchone()
    if wave_id is None:
        raise LookupError(f"no wave {wave_code}")
    wave_id = wave_id[0]

    def scalar(sql: str, params: tuple = ()) -> int:
        return conn.execute(sql, (wave_id, *params)).fetchone()[0]

    planned = scalar("select count(*) from ops.collection_job where wave_id=%s")
    executable = scalar(
        "select count(*) from ops.collection_job where wave_id=%s and planned_eligibility='eligible_land'")
    structurally_excluded = scalar(
        "select count(*) from ops.collection_job "
        "where wave_id=%s and planned_eligibility is distinct from 'eligible_land'")

    # job accounting: executable jobs that reached a terminal/accounted state
    # (an observation row, or a terminal_failure/quarantined/skipped job_event).
    accounted = scalar(
        "select count(distinct j.job_id) from ops.collection_job j "
        "where j.wave_id=%s and j.planned_eligibility='eligible_land' and ("
        " exists (select 1 from ops.observation o where o.job_id=j.job_id) or "
        " exists (select 1 from ops.job_event e where e.job_id=j.job_id "
        "         and e.status in ('terminal_failure','quarantined','skipped')))")

    valid_overall = scalar(
        "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "where j.wave_id=%s and j.planned_eligibility='eligible_land' "
        "and o.observation_state::text = any(%s)", (list(PILOT_VALID_OBSERVATION_STATES),))

    # per-surface executable + valid
    surf_rows = conn.execute(
        "select s.surface_code, count(*) filter (where j.planned_eligibility='eligible_land'), "
        "       count(*) filter (where j.planned_eligibility='eligible_land' and o.observation_state::text = any(%s)) "
        "from ops.collection_job j join manifest.surface s on s.surface_id=j.surface_id "
        "left join ops.observation o on o.job_id=j.job_id "
        "where j.wave_id=%s group by s.surface_code order by s.surface_code",
        (list(PILOT_VALID_OBSERVATION_STATES), wave_id),
    ).fetchall()
    per_surface = {code: {"executable": ex, "valid": val,
                          "valid_rate": _rate(val, ex)} for code, ex, val in surf_rows}

    # per stratum (industry x market x surface) where executable >= 20
    stratum_rows = conn.execute(
        "select i.industry_code, mk.market_code, s.surface_code, "
        "       count(*) filter (where j.planned_eligibility='eligible_land'), "
        "       count(*) filter (where j.planned_eligibility='eligible_land' and o.observation_state::text = any(%s)) "
        "from ops.collection_job j "
        "join manifest.industry i on i.industry_id=j.industry_id "
        "join manifest.market mk on mk.market_id=j.market_id "
        "join manifest.surface s on s.surface_id=j.surface_id "
        "left join ops.observation o on o.job_id=j.job_id "
        "where j.wave_id=%s group by 1,2,3",
        (list(PILOT_VALID_OBSERVATION_STATES), wave_id),
    ).fetchall()
    stratum_failures = []
    strata_evaluated = 0
    for ind, mk, surf, ex, val in stratum_rows:
        if ex >= STRATUM_MIN_EXECUTABLE:
            strata_evaluated += 1
            if _rate(val, ex) < STRATUM_PARTIAL_MIN:
                stratum_failures.append({"stratum": f"{ind}:{mk}:{surf}",
                                         "executable": ex, "valid": val, "rate": _rate(val, ex)})

    # raw payload integrity: every returned observation has an immutable raw ref (COL006)
    returned = scalar(
        "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "where j.wave_id=%s and o.observation_state='returned'")
    returned_with_raw = scalar(
        "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "where j.wave_id=%s and o.observation_state='returned' and o.raw_payload_id is not null")

    # normalization parity: returned observation produced its surface normalized row
    norm_overall = scalar(
        "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "join manifest.surface s on s.surface_id=j.surface_id "
        "where j.wave_id=%s and o.observation_state='returned' and ("
        " (s.surface_code='maps' and exists (select 1 from maps.observation m where m.observation_id=o.observation_id)) or "
        " (s.surface_code='organic' and exists (select 1 from organic.observation g where g.observation_id=o.observation_id)))")
    norm_surface_rows = conn.execute(
        "select s.surface_code, "
        " count(*) filter (where o.observation_state='returned'), "
        " count(*) filter (where o.observation_state='returned' and ("
        "  (s.surface_code='maps' and exists (select 1 from maps.observation m where m.observation_id=o.observation_id)) or "
        "  (s.surface_code='organic' and exists (select 1 from organic.observation g where g.observation_id=o.observation_id)))) "
        "from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "join manifest.surface s on s.surface_id=j.surface_id "
        "where j.wave_id=%s group by s.surface_code", (wave_id,),
    ).fetchall()
    norm_per_surface = {code: _rate(ok, ret) for code, ret, ok in norm_surface_rows}

    # resolution state coverage: every observed_object has >=1 resolution_assertion (RES002)
    objects = scalar(
        "select count(*) from core.observed_object oo "
        "join ops.observation o on o.observation_id=oo.observation_id "
        "join ops.collection_job j on j.job_id=o.job_id where j.wave_id=%s")
    objects_resolved = scalar(
        "select count(distinct oo.observed_object_id) from core.observed_object oo "
        "join ops.observation o on o.observation_id=oo.observation_id "
        "join ops.collection_job j on j.job_id=o.job_id "
        "join core.resolution_run rr on rr.observed_object_id=oo.observed_object_id "
        "join core.resolution_assertion ra on ra.resolution_run_id=rr.resolution_run_id "
        "where j.wave_id=%s")

    # critical manifest conformity: rendered keyword == frozen treatment template
    # after [CITY] substitution, for every job in the wave (PRE006).
    conformity_bad = conn.execute(
        "select count(*) from ops.collection_job j "
        "join manifest.market mk on mk.market_id=j.market_id "
        "join manifest.surface_treatment st on st.surface_treatment_id=j.surface_treatment_id "
        "join manifest.treatment t on t.treatment_id=st.treatment_id "
        "where j.wave_id=%s and j.rendered_input_text <> "
        "  case when t.city_slot_required or t.exact_template like '%%[CITY]%%' "
        "       then replace(t.exact_template,'[CITY]',mk.city) else t.exact_template end",
        (wave_id,),
    ).fetchone()[0]

    # --- critical integrity checks (any hit -> QUARANTINED) ---
    integrity: list[dict[str, Any]] = []
    # COL008 / PRE009: a provider call executed for a structurally-excluded coordinate
    excluded_executed = scalar(
        "select count(*) from ops.observation o join ops.collection_job j on j.job_id=o.job_id "
        "where j.wave_id=%s and j.planned_eligibility is distinct from 'eligible_land'")
    if excluded_executed:
        integrity.append({"rule": "COL008", "detail": "provider call on structurally-excluded coordinate",
                          "count": excluded_executed})
    # COL006: a returned observation missing its immutable raw evidence
    if returned - returned_with_raw:
        integrity.append({"rule": "COL006", "detail": "returned observation without raw payload",
                          "count": returned - returned_with_raw})
    # PRE005: duplicate scientific job identity (also enforced by a UNIQUE constraint)
    dup = scalar(
        "select count(*) - count(distinct job_key) from ops.collection_job where wave_id=%s")
    if dup:
        integrity.append({"rule": "PRE005", "detail": "duplicate job_key", "count": dup})
    # NOR004: duplicated / non-positive maps/organic rank sequence
    bad_rank = conn.execute(
        "select count(*) from ("
        " select o.observation_id from maps.result r "
        "  join ops.observation o on o.observation_id=r.observation_id "
        "  join ops.collection_job j on j.job_id=o.job_id where j.wave_id=%s "
        "  group by o.observation_id, r.result_sequence having count(*)>1 "
        " union all "
        " select o.observation_id from organic.result r "
        "  join ops.observation o on o.observation_id=r.observation_id "
        "  join ops.collection_job j on j.job_id=o.job_id where j.wave_id=%s "
        "  group by o.observation_id, r.result_sequence having count(*)>1) x",
        (wave_id, wave_id),
    ).fetchone()[0]
    if bad_rank:
        integrity.append({"rule": "NOR004", "detail": "duplicate result_sequence within an observation",
                          "count": bad_rank})
    if conformity_bad:
        integrity.append({"rule": "PRE006", "detail": "rendered query differs from frozen treatment",
                          "count": conformity_bad})

    metrics = {
        "job_accounting_rate": _rate(accounted, executable),
        "valid_scientific_observation_rate_overall": _rate(valid_overall, executable),
        "valid_scientific_observation_rate_each_primary_surface": {
            c: v["valid_rate"] for c, v in per_surface.items()},
        "raw_payload_integrity_rate": _rate(returned_with_raw, returned),
        "critical_manifest_conformity_rate": _rate(planned - conformity_bad, planned),
        "normalization_parity_rate_overall": _rate(norm_overall, returned),
        "normalization_parity_rate_each_surface": norm_per_surface,
        "resolution_state_coverage_rate": _rate(objects_resolved, objects),
        "strata_evaluated": strata_evaluated,
        "stratum_failures": stratum_failures,
    }

    status = _classify_status(metrics, integrity, per_surface, norm_per_surface)
    financial = _financial_reconciliation(conn, wave_id, executable, valid_overall)

    report = {
        "wave_code": wave_code, "wave_id": str(wave_id), "status": status,
        "denominators": {"planned": planned, "executable": executable,
                         "structurally_excluded": structurally_excluded,
                         "accounted": accounted, "returned": returned},
        "metrics": metrics, "integrity_violations": integrity,
        "per_surface": per_surface, "financial_reconciliation": financial,
        "qa_contract": {"code": QA_CONTRACT_CODE, "version": QA_CONTRACT_VERSION},
    }

    if persist:
        _persist_evaluation(conn, wave_id, report, evaluator_cv)
    return report


def _classify_status(metrics: dict[str, Any], integrity: list[dict[str, Any]],
                     per_surface: dict[str, dict[str, Any]],
                     norm_per_surface: dict[str, float]) -> str:
    if integrity:
        return "QUARANTINED"

    def surf_min(m: dict[str, float]) -> float:
        return min(m.values()) if m else 1.0

    surf_valid = {c: v["valid_rate"] for c, v in per_surface.items()}

    # FAILED: below partial minimum on any gate, or job accounting unreconciled,
    # or any evaluated stratum below its floor.
    if (metrics["job_accounting_rate"] < PARTIAL_MIN["job_accounting_rate"]
            or metrics["valid_scientific_observation_rate_overall"] < PARTIAL_MIN["valid_scientific_observation_rate_overall"]
            or surf_min(surf_valid) < PARTIAL_MIN["valid_scientific_observation_rate_each_primary_surface"]
            or metrics["raw_payload_integrity_rate"] < PARTIAL_MIN["raw_payload_integrity_rate"]
            or metrics["critical_manifest_conformity_rate"] < PARTIAL_MIN["critical_manifest_conformity_rate"]
            or metrics["normalization_parity_rate_overall"] < PARTIAL_MIN["normalization_parity_rate_overall"]
            or surf_min(norm_per_surface) < PARTIAL_MIN["normalization_parity_rate_each_surface"]
            or metrics["resolution_state_coverage_rate"] < PARTIAL_MIN["resolution_state_coverage_rate"]
            or metrics["stratum_failures"]):
        return "FAILED"

    # COMPLETE: every gate at or above the COMPLETE standard.
    if (metrics["job_accounting_rate"] >= COMPLETE_THRESHOLDS["job_accounting_rate"]
            and metrics["valid_scientific_observation_rate_overall"] >= COMPLETE_THRESHOLDS["valid_scientific_observation_rate_overall"]
            and surf_min(surf_valid) >= COMPLETE_THRESHOLDS["valid_scientific_observation_rate_each_primary_surface"]
            and metrics["raw_payload_integrity_rate"] >= COMPLETE_THRESHOLDS["raw_payload_integrity_rate"]
            and metrics["critical_manifest_conformity_rate"] >= COMPLETE_THRESHOLDS["critical_manifest_conformity_rate"]
            and metrics["normalization_parity_rate_overall"] >= COMPLETE_THRESHOLDS["normalization_parity_rate_overall"]
            and surf_min(norm_per_surface) >= COMPLETE_THRESHOLDS["normalization_parity_rate_each_surface"]
            and metrics["resolution_state_coverage_rate"] >= COMPLETE_THRESHOLDS["resolution_state_coverage_rate"]):
        return "COMPLETE"
    return "PARTIAL"


def _financial_reconciliation(conn, wave_id, executable: int, valid_returned: int) -> dict[str, Any]:
    """Separate from data acceptance (contract §financial_reconciliation).

    Reports cost-event coverage and realized spend. Unit-price drift and
    spend-vs-forecast need a versioned price/forecast baseline; when none is
    seeded we report PENDING rather than fabricate a number."""
    total = conn.execute(
        "select coalesce(sum(amount_microusd),0), count(*) from ops.cost_event where wave_id=%s",
        (wave_id,)).fetchone()
    total_microusd, cost_events = int(total[0]), int(total[1])
    jobs_with_cost = conn.execute(
        "select count(distinct j.job_id) from ops.collection_job j "
        "join ops.observation o on o.job_id=j.job_id "
        "join ops.cost_event c on c.job_id=j.job_id "
        "where j.wave_id=%s and j.planned_eligibility='eligible_land' and o.observation_state='returned'",
        (wave_id,)).fetchone()[0]
    coverage = _rate(jobs_with_cost, valid_returned)
    baseline = conn.execute(
        "select count(*) from ops.provider_price_version").fetchone()[0]
    state = "COMPLETE" if coverage >= 1.0 else "PENDING"
    if baseline == 0:
        state = "PENDING"  # no versioned price baseline to reconcile against
    return {
        "state": state,
        "total_microusd": total_microusd,
        "total_usd": round(total_microusd / 1_000_000, 6),
        "cost_events": cost_events,
        "provider_cost_event_coverage": coverage,
        "unit_price_drift": "no_versioned_baseline" if baseline == 0 else "computed",
    }


_WAVE_STATUS = {"COMPLETE": "complete", "PARTIAL": "partial", "FAILED": "failed",
                "QUARANTINED": "quarantined"}


def _persist_evaluation(conn, wave_id, report: dict[str, Any], evaluator_cv: Optional[str]) -> None:
    qcv = conn.execute(
        "select qa_contract_version_id from ops.qa_contract_version "
        "where contract_code=%s and version_code=%s", (QA_CONTRACT_CODE, QA_CONTRACT_VERSION),
    ).fetchone()
    if qcv is None:
        raise LookupError(f"QA contract {QA_CONTRACT_CODE}/{QA_CONTRACT_VERSION} not seeded")
    qcv = qcv[0]
    from psycopg.types.json import Jsonb
    d = report["denominators"]
    conn.execute(
        "insert into ops.wave_evaluation "
        "(wave_id, qa_contract_version_id, status, expected_jobs, executable_jobs, "
        " returned_observations, structurally_excluded_jobs, failed_jobs, quarantined_jobs, "
        " metrics, evaluator_component_version_id) "
        "values (%s,%s,%s::ops.wave_status,%s,%s,%s,%s,%s,%s,%s,%s)",
        (wave_id, qcv, _WAVE_STATUS[report["status"]], d["planned"], d["executable"],
         d["returned"], d["structurally_excluded"],
         d["executable"] - d["accounted"],
         sum(v["count"] for v in report["integrity_violations"]) if report["integrity_violations"] else 0,
         Jsonb(report["metrics"]), evaluator_cv))
    for v in report["integrity_violations"]:
        conn.execute(
            "insert into ops.qa_event (wave_id, severity, qa_code, expected_value, observed_value, disposition) "
            "values (%s,'critical',%s,%s,%s,'quarantine')",
            (wave_id, v["rule"], Jsonb({"threshold": 0}), Jsonb(v)))
    conn.commit()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _csv(v: Optional[str]) -> Optional[list[str]]:
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Stage-1 3x5 Maps+Organic pilot batch run harness")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--industries", default=None, help="comma list; default the 3 pilot industries")
    p.add_argument("--markets", default=None, help="comma list; default the 5 pilot markets")
    p.add_argument("--surfaces", default=None, help="comma list; default maps,organic")
    p.add_argument("--treatments", default=None, help="comma list; default Q1,Q2,Q3,Q4")
    p.add_argument("--points", default=None, help="comma list; default the 13 MAPORG points")
    p.add_argument("--wave-code", default=None)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--dry-run", action="store_true",
                   help="plan + water gate + render, print accounting; NO writes, NO provider call")
    p.add_argument("--evaluate-only", default=None, metavar="WAVE_CODE",
                   help="run the QA/Wave-Acceptance evaluation on an existing wave; no collection")
    p.add_argument("--execute", action="store_true",
                   help="REQUIRED to make live PAID calls. Without it the harness refuses to collect.")
    p.add_argument("--persist-evaluation", action="store_true",
                   help="write ops.wave_evaluation + qa_event rows after collection/evaluation")
    args = p.parse_args(argv)

    specs = expand_matrix(industries=_csv(args.industries), markets=_csv(args.markets),
                          surfaces=_csv(args.surfaces), treatments=_csv(args.treatments),
                          points=_csv(args.points))

    import psycopg
    from .config import Settings
    settings = Settings()

    with psycopg.connect(settings.db_url()) as conn:
        if args.evaluate_only:
            report = evaluate_wave(conn, args.evaluate_only, persist=args.persist_evaluation)
            print(json.dumps(report, indent=2, default=str))
            return 0

        if args.dry_run or not args.execute:
            plan = plan_dry_run(conn, specs, methodology_code=args.methodology)
            plan["mode"] = "dry_run" if args.dry_run else "refused_no_execute"
            plan["note"] = ("planning only; pass --execute (and set RUN_PAID_PILOT=1 on Railway) "
                            "to make live PAID calls")
            print(json.dumps(plan, indent=2, default=str))
            return 0

        # LIVE PAID PATH (each job's provider is built from its resolved surface config).
        from .config import ProviderCreds, StorageConfig
        from .dataforseo import HttpMapsProvider
        from .raw_store import SupabaseStorageRawStore
        creds = ProviderCreds.from_env()
        raw_store = SupabaseStorageRawStore(StorageConfig.from_env())

        def provider_factory(ctx: ManifestContext):
            return HttpMapsProvider(creds, ctx.post_endpoint, ctx.get_endpoint)

        runner = PilotRunner(conn, provider_factory=provider_factory, raw_store=raw_store,
                             wave_code=args.wave_code, methodology_code=args.methodology,
                             max_retries=args.max_retries)
        runner.setup()
        result = runner.run(specs)
        report = evaluate_wave(conn, runner.wave_code, persist=args.persist_evaluation)
        print(json.dumps({"run": result.summary(), "evaluation": report}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
