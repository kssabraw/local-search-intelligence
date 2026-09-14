"""DB-free guards for the Full Panel / Sentinel cadence driver.

The full cadence flow (kind decision over real waves, mint/resume, submit ->
collect -> reconcile, QA COMPLETE) is validated end to end against an ephemeral
pgvector cluster in scripts/validate_panel_driver.py (no paid call). These cover
the pure decision logic, the deterministic wave codes, and the RUN_PAID_PANEL gate
refusal -- none of which need a database.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector import panel, panel_driver


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Returns a fixed scalar for the single count(*) query decide_kind runs."""
    def __init__(self, count):
        self._count = count
        self.calls = 0

    def execute(self, sql, params=()):
        self.calls += 1
        return _FakeResult([self._count])


# ---- deterministic per-period wave codes ----
def test_default_wave_code_full_panel():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    assert panel_driver.default_wave_code("full_panel", now) == "FULLPANEL-202609"


def test_default_wave_code_sentinel_iso_week():
    now = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)  # ISO 2026-W38
    assert panel_driver.default_wave_code("sentinel", now) == f"SENTINEL-{now:%G}W{now:%V}"


def test_default_wave_code_rejects_unknown_kind():
    with pytest.raises(ValueError):
        panel_driver.default_wave_code("weekly")


# ---- month bounds (incl. December rollover) ----
def test_month_bounds_midmonth():
    start, nxt = panel_driver._month_bounds(datetime(2026, 9, 14, 5, 30, tzinfo=timezone.utc))
    assert start == datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert nxt == datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_month_bounds_december_rollover():
    start, nxt = panel_driver._month_bounds(datetime(2026, 12, 20, tzinfo=timezone.utc))
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert nxt == datetime(2027, 1, 1, tzinfo=timezone.utc)


# ---- cadence-anchor decision ----
def test_decide_kind_no_full_panel_this_month_is_full_panel():
    conn = _FakeConn(0)
    assert panel_driver.decide_kind(conn, methodology_code="MANIFEST_V1_0") == panel.FULL_PANEL


def test_decide_kind_full_panel_exists_is_sentinel():
    conn = _FakeConn(1)
    assert panel_driver.decide_kind(conn, methodology_code="MANIFEST_V1_0") == panel.SENTINEL


# ---- resolve_kind ----
def test_resolve_kind_explicit_passthrough_needs_no_db():
    # explicit kinds never touch the connection
    assert panel_driver.resolve_kind(None, kind="sentinel", methodology_code="X") == "sentinel"
    assert panel_driver.resolve_kind(None, kind="full_panel", methodology_code="X") == "full_panel"


def test_resolve_kind_auto_delegates_to_decide():
    conn = _FakeConn(0)
    assert panel_driver.resolve_kind(conn, kind="auto", methodology_code="X") == panel.FULL_PANEL


def test_resolve_kind_rejects_unknown():
    with pytest.raises(ValueError):
        panel_driver.resolve_kind(None, kind="weekly", methodology_code="X")


# ---- RUN_PAID_PANEL gate refusal (DB-free: gate is checked before any connect) ----
def test_execute_without_gate_is_refused(monkeypatch, capsys):
    monkeypatch.delenv(panel_driver.RUN_PAID_PANEL_ENV, raising=False)
    rc = panel_driver.main(["--execute"])
    assert rc == panel_driver.EXIT_GATE_REFUSED
    assert '"refused": true' in capsys.readouterr().out.lower()


def test_execute_with_gate_zero_is_refused(monkeypatch):
    monkeypatch.setenv(panel_driver.RUN_PAID_PANEL_ENV, "0")
    assert panel_driver.main(["--execute"]) == panel_driver.EXIT_GATE_REFUSED


def test_gate_open_predicate(monkeypatch):
    monkeypatch.setenv(panel_driver.RUN_PAID_PANEL_ENV, "1")
    assert panel_driver._gate_open() is True
    monkeypatch.setenv(panel_driver.RUN_PAID_PANEL_ENV, "0")
    assert panel_driver._gate_open() is False
