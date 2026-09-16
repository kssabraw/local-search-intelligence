"""Tests for the AIO capture-probe sweep (matrix, wave code, gate, roll-up).

DB-free: the runner itself is exercised end-to-end against real schema in
scripts/validate_aio_probe.py; here we cover the pure logic and the paid gate.
"""
import json

from collector import aio_probe
from collector.aio_probe import (AIO_PROBE_CONDITIONS_V0, default_wave_code,
                                 expand_probe_matrix, summarize_capture)


def test_matrix_default_is_3x5_by_conditions_at_center():
    specs = expand_probe_matrix()
    assert len(specs) == 3 * 5 * len(AIO_PROBE_CONDITIONS_V0)  # 30
    assert {s.surface for s in specs} == {"aio"}
    assert {s.point for s in specs} == {"C"}
    assert {s.treatment for s in specs} == set(AIO_PROBE_CONDITIONS_V0)


def test_matrix_v07_generation_order():
    specs = expand_probe_matrix(industries=["IND010", "IND019"], markets=["MKT008", "MKT011"],
                                conditions=["AIO_C01", "AIO_C04"])
    labels = [(s.industry, s.market, s.treatment) for s in specs]
    # industry -> market -> condition
    assert labels == [
        ("IND010", "MKT008", "AIO_C01"), ("IND010", "MKT008", "AIO_C04"),
        ("IND010", "MKT011", "AIO_C01"), ("IND010", "MKT011", "AIO_C04"),
        ("IND019", "MKT008", "AIO_C01"), ("IND019", "MKT008", "AIO_C04"),
        ("IND019", "MKT011", "AIO_C01"), ("IND019", "MKT011", "AIO_C04"),
    ]


def test_default_wave_code_shape():
    import datetime
    code = default_wave_code(datetime.datetime(2026, 9, 16, tzinfo=datetime.timezone.utc))
    assert code == "AIOPROBE-AIOPROBE_V0-20260916"


def test_organic_mode_matrix_and_wave_code():
    import datetime
    specs = expand_probe_matrix(mode="organic")
    assert len(specs) == 3 * 5 * 1            # default single near-me condition (Q1) = 15 tasks
    assert {s.surface for s in specs} == {"organic"}
    assert {s.treatment for s in specs} == {"Q1"}
    code = default_wave_code(datetime.datetime(2026, 9, 16, tzinfo=datetime.timezone.utc), mode="organic")
    assert code == "AIOPROBE-ORG-AIOPROBE_V0-20260916"


def test_organic_dry_run_plan(capsys):
    rc = aio_probe.main(["--mode", "organic", "--dry-run"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["probe_mode"] == "organic"
    assert plan["surface"] == "organic"
    assert plan["planned_jobs"] == 15
    assert plan["would_use_wave_code"].startswith("AIOPROBE-ORG-")
    assert plan["inspect_scope"] == "ai_overview"


def _organic_ctx():
    from collector.models import ManifestContext
    return ManifestContext(
        methodology_version_id="m", methodology_code="MANIFEST_V1_0", surface_id="s",
        surface_code="organic", industry_id="i", market_id="mk", market_city="Vancouver",
        surface_treatment_id="st", treatment_id="t", treatment_code="Q1", treatment_kind="query",
        exact_template="locksmith near me", city_slot_required=False, coordinate_id="c",
        coordinate_code="MKT008_MAPORG_C", latitude=45.62, longitude=-122.67, eligibility="eligible_land",
        provider_profile_id="pp", provider_id="pv", post_endpoint="/v3/serp/google/organic/task_post",
        get_endpoint="/v3/serp/google/organic/task_get/advanced/{id}", location_template="{lat},{lon},200",
        language_code="en", device="desktop", operating_system="windows", result_depth=10)


def test_build_request_async_and_rectangles_flags():
    from collector import spike
    req = spike.build_request(_organic_ctx(), calculate_rectangles=True, load_async_ai_overview=True)
    assert req["calculate_rectangles"] is True
    assert req["load_async_ai_overview"] is True
    assert req["keyword"] == "locksmith near me"
    assert req["location_coordinate"].endswith(",200")
    # defaults: neither flag on an organic request
    req2 = spike.build_request(_organic_ctx())
    assert "load_async_ai_overview" not in req2
    assert "calculate_rectangles" not in req2


def test_paid_gate_refuses_without_env(monkeypatch, capsys):
    monkeypatch.delenv(aio_probe.RUN_AIO_PROBE_ENV, raising=False)
    rc = aio_probe.main(["--execute"])
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["refused"] is True


def test_dry_run_plans_without_db(capsys):
    rc = aio_probe.main(["--dry-run"])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "dry_run"
    assert plan["planned_jobs"] == 30
    assert plan["surface"] == "aio"


def test_no_execute_no_gate_is_refused_plan(capsys):
    rc = aio_probe.main([])
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "refused_no_execute"


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a, **k):
        return _FakeCursor(self._rows)


def _md(**verdicts):
    caps = {k: {"verdict": v} for k, v in verdicts.items()}
    return {"aio_capture": {"returned": True, "aio_present": bool(verdicts), "capabilities": caps}}


def test_summarize_rollup_capturable_absent_inconclusive():
    # rectangles present in one obs, absent in another => CAPTURABLE (proved >=1)
    rows = [
        (_md(element_rectangles="present", source_citations="absent"),),
        (_md(element_rectangles="absent", source_citations="absent"),),
    ]
    rep = summarize_capture(_FakeConn(rows), "AIOPROBE-TEST")
    assert rep["aio_triggered"] == 2
    assert rep["fields"]["element_rectangles"]["decision"] == "CAPTURABLE"
    # never present across triggered AIOs => NOT_OBSERVABLE
    assert rep["fields"]["source_citations"]["decision"] == "NOT_OBSERVABLE"


def test_summarize_no_triggers_is_inconclusive():
    rows = [({"aio_capture": {"returned": True, "aio_present": False,
                              "capabilities": {}}},)]
    rep = summarize_capture(_FakeConn(rows), "AIOPROBE-TEST")
    assert rep["aio_triggered"] == 0
    for field in rep["fields"].values():
        assert field["decision"] == "INCONCLUSIVE"
