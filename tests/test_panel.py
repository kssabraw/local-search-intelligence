"""Unit tests for the Full Panel / Sentinel generator that need no database.

Full DB-backed count/order/water-accounting assertions live in
scripts/validate_panel.py (ephemeral pgvector, no paid call). These cover the
pure guards: wave-kind validation and the closed paid path.
"""
from __future__ import annotations

import json

import pytest

from collector import panel


def test_wave_kinds_are_maps_organic_scope():
    assert panel.WAVE_KINDS == ("full_panel", "sentinel")
    assert panel.SURFACES == ["maps", "organic"]
    assert panel.TREATMENT_SET == "GOOGLE_QUERY_V1"
    assert panel.SENTINEL_SUBSET_CODE == "SENTINEL_V1"


def test_geometry_is_surface_config_resolved_not_hardcoded():
    # The Maps/Organic geometry must NOT be a hardcoded constant: it is resolved
    # from manifest.surface_config at run time (GEOGRID13E_V1 per ADR-0009), so a
    # repoint is followed with no code change. Guards against the MAPORG13_V1 pin
    # regressing. (The DB-backed resolution is asserted in scripts/validate_panel.py.)
    assert not hasattr(panel, "GEOMETRY_CODE")


def test_load_scope_rejects_unknown_kind_before_touching_db():
    # kind is validated before the connection is used, so conn=None is safe.
    with pytest.raises(ValueError):
        panel.load_scope(None, kind="weekly", methodology_code="MANIFEST_V1_0")


def test_plan_wave_rejects_unknown_kind_before_touching_db():
    with pytest.raises(ValueError):
        panel.plan_wave(None, kind="everything", methodology_code="MANIFEST_V1_0")


def test_cli_refuses_execute_without_touching_db(capsys):
    # --execute must refuse (return 2) and never open a DB connection: live panel
    # collection is RUN_PAID_PANEL-gated and lands with the decoupled adapter.
    rc = panel.main(["--kind", "full_panel", "--execute"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["refused"] is True
    assert "RUN_PAID_PANEL" in out["reason"]


def test_cli_requires_a_kind(capsys):
    with pytest.raises(SystemExit):
        panel.main([])
