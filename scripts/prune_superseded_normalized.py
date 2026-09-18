#!/usr/bin/env python3
"""Prune the NORMALIZED layer of superseded collection waves to reclaim DB space.

Governed by docs/design/data-retention-cleanup-v0_1.md. The parent PRD rule is:
raw provider payloads are the immutable source of truth (Supabase Storage, gzipped,
content-addressed via ops.raw_blob / storage.objects) and are NEVER pruned; the
per-surface normalized tables (maps.*, organic.*, aio.*) and the per-observation
entity-appearance + resolution bookkeeping (core.observed_object, core.resolution_*)
are DERIVED and rebuildable from raw, so a superseded wave's normalized rows can be
deleted and, if ever needed, reconstructed by re-running the parser over its raw.

This prunes ONLY that derived layer, scoped to explicitly selected waves. It NEVER
touches:
  * raw payloads (ops.raw_blob, storage.objects) -- the rebuild source;
  * the canonical entity graph (core.entity / web_domain / web_url /
    external_identifier) -- shared across all waves, keyed independently of any one
    observation;
  * the cost ledger (ops.cost_event) and wave/job provenance (ops.collection_wave /
    collection_job) -- kept for audit; a pruned wave still "exists", it just has no
    normalized observations until rebuilt.

Every foreign key in the schema is ON DELETE NO ACTION (verified), so deletes are
issued explicitly child->parent; nothing cascades into the canonical entities.

SAFETY GATES (mirroring the paid-collection gates):
  * Default mode is a READ-ONLY inventory (`--list`) or a dry-run count -- no writes.
  * `--execute` additionally requires the env gate CONFIRM_PRUNE=1, and rolls the
    whole prune into ONE transaction.
  * The ACTIVE Maps/Organic grid (manifest.surface_config) is refused by default:
    a wave whose coordinates are on the currently-configured geometry is never
    pruned unless `--allow-active-grid` is passed (intended only for tests).
  * This module makes NO provider call and spends NO money.

Reclaiming physical disk: a DELETE returns space to Postgres's free map but does not
shrink the database file. After pruning, run `VACUUM (ANALYZE)` for planner health,
then `pg_repack` (online, preferred on Supabase) or `VACUUM FULL` (locks the table,
needs free scratch ~= table size) on the large tables to return space to the OS.
This script does NOT run VACUUM FULL/pg_repack itself (they need their own window).
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any, Optional

# Child -> parent delete order. Each entry: (schema.table, scoping predicate) where
# the predicate references one of the temp id sets (_prune_obs / _prune_oo /
# _prune_run) materialized at the start of the prune. Order matters: a table must be
# deleted before any table it references within this set (all FKs are NO ACTION).
_DELETE_STEPS: list[tuple[str, str]] = [
    # per-surface result rows (reference the surface observation + observed_object)
    ("maps.result", "observation_id in (select observation_id from _prune_obs)"),
    ("organic.result", "observation_id in (select observation_id from _prune_obs)"),
    # AIO / ChatGPT per-observation children (empty for maps/organic waves; scoped
    # so the script is correct for an AIO/ChatGPT wave too)
    ("aio.business_appearance", "observation_id in (select observation_id from _prune_obs)"),
    ("aio.citation", "observation_id in (select observation_id from _prune_obs)"),
    ("aio.destination", "observed_object_id in (select observed_object_id from _prune_oo)"),
    ("aio.source_occurrence", "observation_id in (select observation_id from _prune_obs)"),
    ("aio.presentation_unit", "observation_id in (select observation_id from _prune_obs)"),
    ("chatgpt.citation", "observation_id in (select observation_id from _prune_obs)"),
    ("chatgpt.entity_mention", "observation_id in (select observation_id from _prune_obs)"),
    ("chatgpt.retrieved_source", "observation_id in (select observation_id from _prune_obs)"),
    ("chatgpt.destination", "observed_object_id in (select observed_object_id from _prune_oo)"),
    ("chatgpt.fanout_query", "observation_id in (select observation_id from _prune_obs)"),
    # resolution bookkeeping (assertion -> candidate -> run), keyed on observed_object
    ("core.resolution_assertion", "resolution_run_id in (select resolution_run_id from _prune_run)"),
    ("core.resolution_candidate", "resolution_run_id in (select resolution_run_id from _prune_run)"),
    ("core.resolution_run", "observed_object_id in (select observed_object_id from _prune_oo)"),
    # entity alias/relationship assertions sourced from a pruned appearance
    ("core.entity_alias_assertion", "source_observed_object_id in (select observed_object_id from _prune_oo)"),
    ("core.entity_relationship_assertion", "source_observed_object_id in (select observed_object_id from _prune_oo)"),
    # embeddings of a pruned appearance (out of current scope; defensive)
    ("enrichment.embedding", "observed_object_id in (select observed_object_id from _prune_oo)"),
    # the per-observation appearance rows themselves
    ("core.observed_object", "observation_id in (select observation_id from _prune_obs)"),
    # per-surface observation rows
    ("maps.observation", "observation_id in (select observation_id from _prune_obs)"),
    ("organic.observation", "observation_id in (select observation_id from _prune_obs)"),
    ("aio.observation", "observation_id in (select observation_id from _prune_obs)"),
    ("chatgpt.observation", "observation_id in (select observation_id from _prune_obs)"),
    # other per-observation references (out of current scope; defensive)
    ("research.feature_value", "observation_id in (select observation_id from _prune_obs)"),
    ("research.finding_evidence", "observation_id in (select observation_id from _prune_obs)"),
    ("enrichment.enrichment_request", "trigger_observation_id in (select observation_id from _prune_obs)"),
    ("ops.qa_event", "observation_id in (select observation_id from _prune_obs)"),
    # finally the shared observation row (raw_blob, cost_event, collection_job are KEPT)
    ("ops.observation", "observation_id in (select observation_id from _prune_obs)"),
]

CONFIRM_ENV = "CONFIRM_PRUNE"


def _regclass_exists(conn, qualified: str) -> bool:
    return conn.execute("select to_regclass(%s) is not null", (qualified,)).fetchone()[0]


def wave_inventory(conn) -> list[dict[str, Any]]:
    """Every wave with its resolved geometry_code + normalized footprint (read-only).

    A wave's geometry is derived from the geometry_version its jobs' coordinates
    belong to (collection_job.coordinate_id -> market_coordinate -> geometry_point
    -> geometry_version), so it is correct regardless of any later surface repoint.
    """
    rows = conn.execute(
        """
        select w.wave_code, w.wave_kind::text as kind, gv.geometry_code,
               count(distinct j.job_id) as jobs,
               count(distinct o.observation_id) as observations,
               count(distinct oo.observed_object_id) as observed_objects
        from ops.collection_wave w
        join ops.collection_job j on j.wave_id = w.wave_id
        join manifest.market_coordinate mc on mc.coordinate_id = j.coordinate_id
        join manifest.geometry_point gp on gp.geometry_point_id = mc.geometry_point_id
        join manifest.geometry_version gv on gv.geometry_version_id = gp.geometry_version_id
        left join ops.observation o on o.job_id = j.job_id
        left join core.observed_object oo on oo.observation_id = o.observation_id
        group by w.wave_code, w.wave_kind, gv.geometry_code
        order by w.wave_code
        """
    ).fetchall()
    return [dict(wave_code=r[0], kind=r[1], geometry_code=r[2], jobs=r[3],
                 observations=r[4], observed_objects=r[5]) for r in rows]


def active_geometry(conn, methodology_code: str = "MANIFEST_V1_0") -> Optional[str]:
    """The Maps/Organic grid currently configured in surface_config, or None."""
    from collector import pilot
    try:
        return pilot.resolve_active_geometry(conn, methodology_code=methodology_code)
    except Exception:
        return None


def select_waves(conn, *, wave_codes: Optional[list[str]] = None,
                 geometry: Optional[str] = None,
                 methodology_code: str = "MANIFEST_V1_0",
                 allow_active_grid: bool = False) -> list[dict[str, Any]]:
    """Resolve the target waves from explicit codes and/or a geometry filter, and
    refuse any wave on the active Maps/Organic grid unless explicitly allowed."""
    if not wave_codes and not geometry:
        raise ValueError("select at least one of --waves or --geometry")
    inv = {w["wave_code"]: w for w in wave_inventory(conn)}
    selected: dict[str, dict[str, Any]] = {}
    if wave_codes:
        for code in wave_codes:
            if code not in inv:
                raise LookupError(f"unknown wave_code {code!r} (not present in ops.collection_wave)")
            selected[code] = inv[code]
    if geometry:
        for w in inv.values():
            if w["geometry_code"] == geometry:
                selected[w["wave_code"]] = w
    active = active_geometry(conn, methodology_code)
    if not allow_active_grid and active is not None:
        on_active = [c for c, w in selected.items() if w["geometry_code"] == active]
        if on_active:
            raise PermissionError(
                f"refusing to prune wave(s) on the ACTIVE grid {active!r}: {sorted(on_active)}. "
                f"The active grid is live data. Pass --allow-active-grid only if you truly mean it.")
    return sorted(selected.values(), key=lambda w: w["wave_code"])


def _materialize_id_sets(conn, wave_ids: list[str]) -> None:
    """Materialize the observation / observed_object / resolution_run id sets for the
    selected waves as ON COMMIT DROP temp tables, so every delete step scopes off an
    indexed set rather than re-running the wave join. Dropped at commit or rollback."""
    for t in ("_prune_run", "_prune_oo", "_prune_obs"):
        conn.execute(f"drop table if exists {t}")
    conn.execute(
        "create temp table _prune_obs on commit drop as "
        "select o.observation_id from ops.observation o "
        "join ops.collection_job j on j.job_id = o.job_id "
        "where j.wave_id = any(%s)", (wave_ids,))
    conn.execute("create unique index on _prune_obs(observation_id)")
    conn.execute(
        "create temp table _prune_oo on commit drop as "
        "select observed_object_id from core.observed_object "
        "where observation_id in (select observation_id from _prune_obs)")
    conn.execute("create unique index on _prune_oo(observed_object_id)")
    conn.execute(
        "create temp table _prune_run on commit drop as "
        "select resolution_run_id from core.resolution_run "
        "where observed_object_id in (select observed_object_id from _prune_oo)")
    conn.execute("create unique index on _prune_run(resolution_run_id)")


def prune(conn, wave_ids: list[str], *, execute: bool) -> dict[str, int]:
    """Delete (execute=True) or count (execute=False) the normalized rows of the
    given waves, in child->parent order, inside a single transaction. Returns a
    per-table rowcount. On execute=False the transaction is rolled back.

    The normalized tables are append-only at the DB level (an ops.reject_update_delete
    USER trigger blocks DELETE), so a prune must deliberately bypass that guard. We
    disable the USER trigger on each target table for the transaction and re-enable it
    before commit, leaving the SYSTEM triggers (foreign-key enforcement) ACTIVE -- so a
    mis-scoped delete would still be caught by an FK, and a plain accidental DELETE
    outside this tool is still rejected. ALTER TABLE ... TRIGGER is transactional, so a
    rollback (dry-run, or any error) restores every trigger automatically."""
    counts: dict[str, int] = {}
    _materialize_id_sets(conn, wave_ids)
    tables = [t for t, _ in _DELETE_STEPS if _regclass_exists(conn, t)]
    if not execute:
        for table, predicate in _DELETE_STEPS:
            if table in tables:
                counts[table] = conn.execute(
                    f"select count(*) from {table} where {predicate}").fetchone()[0]
        conn.rollback()
        return counts
    # execute: bypass the append-only USER trigger for this transaction only.
    for table in tables:
        conn.execute(f"alter table {table} disable trigger user")
    try:
        for table, predicate in _DELETE_STEPS:
            if table in tables:
                counts[table] = conn.execute(f"delete from {table} where {predicate}").rowcount
        for table in tables:
            conn.execute(f"alter table {table} enable trigger user")
        conn.commit()
    except Exception:
        conn.rollback()  # transactional DDL: re-enables every trigger
        raise
    return counts


def _wave_ids(conn, wave_codes: list[str]) -> list[str]:
    rows = conn.execute(
        "select wave_id from ops.collection_wave where wave_code = any(%s)", (wave_codes,)).fetchall()
    return [r[0] for r in rows]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Prune the normalized layer of superseded waves (raw payloads kept). "
                    "Read-only unless --execute AND CONFIRM_PRUNE=1.")
    p.add_argument("--list", action="store_true", help="print the wave inventory (geometry + footprint) and exit")
    p.add_argument("--waves", default=None, help="comma list of wave_codes to prune")
    p.add_argument("--geometry", default=None, help="prune all waves on this geometry_code (e.g. MAPORG13_V1)")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--allow-active-grid", action="store_true",
                   help="permit pruning waves on the active grid (tests only; refused by default)")
    p.add_argument("--execute", action="store_true",
                   help="REQUIRED to delete. Also needs CONFIRM_PRUNE=1. Without it, dry-run counts only.")
    args = p.parse_args(argv)

    import psycopg
    from collector.config import Settings
    with psycopg.connect(Settings().db_url()) as conn:
        if args.list or (not args.waves and not args.geometry):
            print(json.dumps({"waves": wave_inventory(conn)}, indent=2, default=str))
            return 0

        codes = [c.strip() for c in args.waves.split(",")] if args.waves else None
        selected = select_waves(conn, wave_codes=codes, geometry=args.geometry,
                                methodology_code=args.methodology,
                                allow_active_grid=args.allow_active_grid)
        wave_ids = _wave_ids(conn, [w["wave_code"] for w in selected])

        gate_open = os.environ.get(CONFIRM_ENV) == "1"
        do_execute = args.execute and gate_open
        counts = prune(conn, wave_ids, execute=do_execute)
        print(json.dumps({
            "mode": "executed" if do_execute else "dry_run",
            "selected_waves": [w["wave_code"] for w in selected],
            "selected_geometries": sorted({w["geometry_code"] for w in selected}),
            "rows_%s" % ("deleted" if do_execute else "would_delete"): counts,
            "total_rows": sum(counts.values()),
            "note": (
                "committed; raw payloads + canonical entities + cost ledger untouched. "
                "Run pg_repack / VACUUM FULL on the large tables to return space to the OS."
                if do_execute else
                ("refused_execute: pass --execute AND set CONFIRM_PRUNE=1 to delete"
                 if args.execute and not gate_open else
                 "dry-run only; no rows deleted")),
        }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
