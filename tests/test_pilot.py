"""Unit tests for the pilot batch run harness (pure logic; no DB, no provider).

Matrix generation, the water-gate/order invariants, the retry classifier, and
the QA/Wave-Acceptance status ladder are tested here. The end-to-end DB path
(accounting, idempotency, QA persistence) is covered by
scripts/validate_pilot.py against a real ephemeral schema.
"""
from __future__ import annotations

from collector import pilot
from collector.pilot import PilotJobSpec
from collector.raw_store import RawStoreError


# ---------------------------------------------------------------------------
# matrix generation
# ---------------------------------------------------------------------------
def test_full_matrix_is_1560_prewater():
    specs = pilot.expand_matrix()
    assert len(specs) == 1560  # 3 x 5 x 2 x 4 x 13
    assert len(set(specs)) == 1560  # all distinct


def test_matrix_generation_order_matches_contract():
    # job-generator v0.7: industry -> market -> surface -> condition -> point.
    specs = pilot.expand_matrix()
    first, second = specs[0], specs[1]
    # the innermost loop is point: first two differ only by point
    assert (first.surface, first.industry, first.market, first.treatment) == \
           (second.surface, second.industry, second.market, second.treatment)
    assert first.point == pilot.PILOT_POINTS[0]
    assert second.point == pilot.PILOT_POINTS[1]
    # market varies more slowly than surface/treatment/point but faster than industry
    assert specs[0].industry == pilot.PILOT_INDUSTRIES[0]
    per_industry = 5 * 2 * 4 * 13
    assert specs[per_industry].industry == pilot.PILOT_INDUSTRIES[1]


def test_matrix_filters_narrow_without_reordering():
    specs = pilot.expand_matrix(industries=["IND010"], markets=["MKT008"], surfaces=["maps"],
                                treatments=["Q1"])
    assert len(specs) == 13  # one cell, one query, one surface, 13 points
    assert [s.point for s in specs] == pilot.PILOT_POINTS
    assert all(s.surface == "maps" and s.industry == "IND010" for s in specs)


def test_concurrent_partition_keeps_a_maps_place_id_within_one_worker():
    # A (industry, market, surface) group is never split across workers, so every
    # coordinate of one cell -- where a Maps place_id is local -- is processed by a
    # single worker (correct entity reuse). Verify the grouping invariant the
    # concurrent runner relies on: no two groups share an (industry, market, surface).
    specs = pilot.expand_matrix()
    groups: dict[tuple, list] = {}
    for s in specs:
        groups.setdefault((s.industry, s.market, s.surface), []).append(s)
    assert len(groups) == 3 * 5 * 2  # 30 partition groups
    # every spec lands in exactly one group; groups fully cover the matrix
    assert sum(len(v) for v in groups.values()) == len(specs)
    # each group is a single cell+surface (the unit within which place_ids may recur)
    for (ind, mkt, surf), members in groups.items():
        assert all(m.industry == ind and m.market == mkt and m.surface == surf for m in members)


def test_pilot_universe_matches_claude_md():
    assert pilot.PILOT_INDUSTRIES == ["IND010", "IND019", "IND022"]
    assert pilot.PILOT_MARKETS == ["MKT008", "MKT011", "MKT021", "MKT040", "MKT049"]
    assert pilot.PILOT_SURFACES == ["maps", "organic"]
    assert pilot.PILOT_TREATMENTS == ["Q1", "Q2", "Q3", "Q4"]
    assert len(pilot.PILOT_POINTS) == 13
    assert pilot.PILOT_POINTS[0] == "C"


def test_spec_label_is_stable():
    s = PilotJobSpec("maps", "IND010", "MKT008", "Q1", "C")
    assert s.label == "maps:IND010:MKT008:Q1:C"


# ---------------------------------------------------------------------------
# retry classification — only connection-ESTABLISHMENT failures may retry,
# because run_spike always re-POSTs and re-POSTing after the request has already
# left the socket would duplicate a paid provider task.
# ---------------------------------------------------------------------------
class ConnectError(Exception):
    """Stand-in for httpx.ConnectError (no request was ever sent)."""


class ConnectTimeout(Exception):
    """Stand-in for httpx.ConnectTimeout."""


class ReadTimeout(Exception):
    """Stand-in for httpx.ReadTimeout (request WAS sent; response lost)."""


def test_connection_establishment_errors_are_retryable():
    # No paid task can exist yet -> a re-POST is the first successful POST.
    assert pilot.is_retryable(ConnectError("connection refused"))
    assert pilot.is_retryable(ConnectTimeout("connect timed out"))


def test_post_submission_and_logic_errors_are_not_retryable():
    # Anything that can occur AFTER the request left the socket must be terminal:
    # re-POSTing it would duplicate a paid DataForSEO task.
    assert not pilot.is_retryable(ReadTimeout("read timed out"))            # response lost, task may exist
    assert not pilot.is_retryable(RuntimeError("connection reset by peer"))  # mid-response reset
    assert not pilot.is_retryable(RuntimeError("task abc not ready within 300.0s"))  # provider poll timeout
    assert not pilot.is_retryable(RuntimeError("provider returned 503"))    # server-side, task may exist
    assert not pilot.is_retryable(TimeoutError("timed out"))                 # ambiguous -> conservative
    # storage / logic errors are never retryable
    assert not pilot.is_retryable(RawStoreError("signature verification failed"))
    assert not pilot.is_retryable(ValueError("coordinate is structural_water_exclusion"))
    assert not pilot.is_retryable(LookupError("no manifest context"))


# ---------------------------------------------------------------------------
# QA status ladder
# ---------------------------------------------------------------------------
def _clean_metrics():
    return {
        "job_accounting_rate": 1.0,
        "valid_scientific_observation_rate_overall": 1.0,
        "raw_payload_integrity_rate": 1.0,
        "critical_manifest_conformity_rate": 1.0,
        "normalization_parity_rate_overall": 1.0,
        "resolution_state_coverage_rate": 1.0,
        "stratum_failures": [],
    }


def _clean_surface():
    return {"maps": {"valid_rate": 1.0}, "organic": {"valid_rate": 1.0}}


def _clean_norm():
    return {"maps": 1.0, "organic": 1.0}


def test_status_complete():
    assert pilot._classify_status(_clean_metrics(), [], _clean_surface(), _clean_norm()) == "COMPLETE"


def test_status_quarantined_on_any_integrity_violation():
    # An integrity violation wins over everything, even with perfect metrics.
    integrity = [{"rule": "COL008", "detail": "call on excluded coord", "count": 1}]
    assert pilot._classify_status(_clean_metrics(), integrity, _clean_surface(), _clean_norm()) == "QUARANTINED"


def test_status_partial_between_thresholds():
    m = _clean_metrics()
    m["valid_scientific_observation_rate_overall"] = 0.992  # < 0.995 complete, > 0.97 partial-min
    surf = {"maps": {"valid_rate": 0.992}, "organic": {"valid_rate": 1.0}}
    assert pilot._classify_status(m, [], surf, _clean_norm()) == "PARTIAL"


def test_status_failed_below_partial_minimum():
    m = _clean_metrics()
    m["valid_scientific_observation_rate_overall"] = 0.90  # < 0.97 partial-min
    surf = {"maps": {"valid_rate": 0.80}, "organic": {"valid_rate": 1.0}}
    assert pilot._classify_status(m, [], surf, _clean_norm()) == "FAILED"


def test_status_failed_on_stratum_floor_breach():
    m = _clean_metrics()
    m["stratum_failures"] = [{"stratum": "IND010:MKT021:maps", "rate": 0.90}]
    assert pilot._classify_status(m, [], _clean_surface(), _clean_norm()) == "FAILED"


def test_status_failed_when_job_accounting_incomplete():
    # An unaccounted executable job (denominator cannot reconcile) -> FAILED.
    m = _clean_metrics()
    m["job_accounting_rate"] = 0.999
    assert pilot._classify_status(m, [], _clean_surface(), _clean_norm()) == "FAILED"


def test_status_partial_on_surface_specific_shortfall():
    # Overall fine, but one primary surface between its complete and partial floors.
    m = _clean_metrics()
    surf = {"maps": {"valid_rate": 0.996}, "organic": {"valid_rate": 0.97}}
    assert pilot._classify_status(m, [], surf, _clean_norm()) == "PARTIAL"


def test_rate_helper_treats_empty_denominator_as_complete():
    assert pilot._rate(0, 0) == 1.0
    assert pilot._rate(1, 2) == 0.5
