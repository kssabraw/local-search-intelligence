"""DB-free guards for the decoupled panel runner + batch provider.

The full submit -> collect -> reconcile + resume behavior is validated end to end
against an ephemeral pgvector cluster in scripts/validate_panel_run.py (no paid
call). These cover the pure argument guards and the ready-endpoint derivation.
"""
from __future__ import annotations

import pytest

from collector import dataforseo
from collector.config import ProviderCreds
from collector.panel_run import PanelRunner


def _runner(**kw):
    return PanelRunner(conn=None, batch_provider_factory=lambda ctx: None,
                       raw_store=None, **kw)


def test_runner_rejects_unknown_kind():
    with pytest.raises(ValueError):
        _runner(kind="weekly")


@pytest.mark.parametrize("bad", [0, -1, 101, 1000])
def test_runner_rejects_out_of_range_batch_size(bad):
    with pytest.raises(ValueError):
        _runner(kind="sentinel", batch_size=bad)


def test_runner_accepts_valid_kinds_and_sets_wave_prefix():
    fp = _runner(kind="full_panel")
    se = _runner(kind="sentinel")
    assert fp.wave_code.startswith("FULLPANEL-")
    assert se.wave_code.startswith("SENTINEL-")
    assert fp.batch_size == dataforseo.MAX_TASKS_PER_POST


def test_batch_cap_is_100():
    assert dataforseo.MAX_TASKS_PER_POST == 100


def test_ready_endpoint_derived_from_task_post():
    p = dataforseo.HttpMapsProvider(
        ProviderCreds(login="x", password="y"),
        "/v3/serp/google/maps/task_post", "/v3/serp/google/maps/task_get/advanced/{id}")
    assert p._ready_endpoint() == "/v3/serp/google/maps/tasks_ready"


def test_ready_endpoint_refuses_non_task_post_endpoint():
    p = dataforseo.HttpMapsProvider(
        ProviderCreds(login="x", password="y"), "/v3/serp/google/maps/live/advanced", "{id}")
    with pytest.raises(dataforseo.ProviderError):
        p._ready_endpoint()


def test_task_post_batch_rejects_oversize(monkeypatch):
    p = dataforseo.HttpMapsProvider(
        ProviderCreds(login="x", password="y"),
        "/v3/serp/google/maps/task_post", "{id}")
    with pytest.raises(ValueError):
        p.task_post_batch([{"keyword": "k"}] * 101)
    with pytest.raises(ValueError):
        p.task_post_batch([])
