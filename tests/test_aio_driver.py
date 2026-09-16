"""DB-free unit tests for the AIO collection driver + matrix (ADR-0008).

No DB, no provider — pure functions (matrix expansion, wave-code, gate predicate,
CLI spec building). The end-to-end DB path is covered by scripts/validate_aio_run.py.
"""
import argparse
import os
from datetime import datetime, timezone

from collector import aio_driver, aio_run
from collector.pilot import PILOT_INDUSTRIES, PILOT_MARKETS


def test_graduated_matrix_defaults():
    specs = aio_run.expand_aio_matrix()
    # 3 industries x 5 markets x 2 conditions x 1 point (center)
    assert len(specs) == len(PILOT_INDUSTRIES) * len(PILOT_MARKETS) * 2 * 1
    assert {s.surface for s in specs} == {"aio"}
    assert {s.point for s in specs} == {"C"}
    assert {s.treatment for s in specs} == {"AIO_C01", "AIO_C04"}


def test_matrix_v07_order_industry_then_market_then_condition():
    specs = aio_run.expand_aio_matrix(industries=["IND010", "IND019"], markets=["MKT008"],
                                      conditions=["AIO_C01", "AIO_C04"], points=["C"])
    assert [s.label for s in specs] == [
        "aio:IND010:MKT008:AIO_C01:C", "aio:IND010:MKT008:AIO_C04:C",
        "aio:IND019:MKT008:AIO_C01:C", "aio:IND019:MKT008:AIO_C04:C"]


def test_full_13point_10condition_scope_size():
    specs = aio_run.expand_aio_matrix(conditions=aio_run.AIO_CONDITIONS_ALL,
                                      points=aio_run.AIO_POINTS_FULL)
    assert len(specs) == 3 * 5 * 10 * 13
    assert len(aio_run.AIO_CONDITIONS_ALL) == 10
    assert len(aio_run.AIO_POINTS_FULL) == 13


def test_default_wave_code_is_per_day():
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    assert aio_driver.default_wave_code(now) == "AIO-20260916"


def test_gate_closed_by_default(monkeypatch):
    monkeypatch.delenv(aio_driver.RUN_PAID_AIO_ENV, raising=False)
    assert aio_driver._gate_open() is False
    monkeypatch.setenv(aio_driver.RUN_PAID_AIO_ENV, "1")
    assert aio_driver._gate_open() is True
    monkeypatch.setenv(aio_driver.RUN_PAID_AIO_ENV, "0")
    assert aio_driver._gate_open() is False


def _args(**over):
    base = dict(industries=None, markets=None, conditions=None, all_conditions=False,
                points=None, points_full=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_build_specs_all_conditions_flag():
    specs = aio_driver._build_specs(_args(industries="IND010", markets="MKT008", all_conditions=True))
    assert sorted({s.treatment for s in specs}) == aio_run.AIO_CONDITIONS_ALL
    assert {s.point for s in specs} == {"C"}


def test_build_specs_points_full_flag():
    specs = aio_driver._build_specs(_args(industries="IND010", markets="MKT008", points_full=True))
    assert {s.point for s in specs} == set(aio_run.AIO_POINTS_FULL)


def test_build_specs_explicit_conditions_override_all_flag():
    # explicit --conditions wins over --all-conditions
    specs = aio_driver._build_specs(
        _args(industries="IND010", markets="MKT008", conditions="AIO_C02", all_conditions=True))
    assert {s.treatment for s in specs} == {"AIO_C02"}
