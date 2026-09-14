#!/usr/bin/env python3
"""Apply supabase/migrations/001..NNN to a target Postgres and verify reconciliation.

One command for the Governing build sequence step 2 ("apply the physical schema to
a persistent environment"): applies every `supabase/migrations/[0-9][0-9][0-9]_*.sql`
in order, each file in its own transaction with stop-on-error (the same behavior as
`psql -1 -v ON_ERROR_STOP=1 -f <file>` used by scripts/validate_migrations.py), then
runs the coordinate reconciliation (1,100 -> 1,000 eligible / 91 water / 9 outside
country) and the key universe counts against the applied database.

Connection string (never printed, never committed):
  --dsn "postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"
  or set SUPABASE_DB_URL in the environment and omit --dsn.

Get the string from Supabase -> Project Settings -> Database -> Connection string.
Secrets belong only in your shell / Railway / Supabase secret management, never in
this repo or in chat (CLAUDE.md).

Examples:
  # apply to a fresh database, then verify
  python scripts/apply_migrations.py --dsn "$SUPABASE_DB_URL"
  # only verify an already-applied database (no writes)
  python scripts/apply_migrations.py --dsn "$SUPABASE_DB_URL" --check-only
  # list the files that would be applied (no connection)
  python scripts/apply_migrations.py --dry-run

Exit code 0 iff every migration applied (or --check-only) AND the reconciliation
matches. Migrations are NOT idempotent (plain `create type` / `create table`), so
applying to a database that already has the schema fails fast on the first file;
use --check-only to re-verify or --force to attempt a re-apply anyway.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"

# (label, sql, expected) -- the coordinate reconciliation rows are the critical gate;
# the rest confirm the frozen Manifest v1.0 universe landed intact. Mirrors
# scripts/validate_migrations.py so both paths assert the same invariants.
RECON_CHECKS = [
    ("extensions (vector,pg_trgm,pgcrypto)",
     "select count(*) from pg_extension where extname in ('vector','pg_trgm','pgcrypto')", 3),
    ("coordinates total", "select count(*) from manifest.market_coordinate", 1100),
    ("coordinates eligible_land",
     "select count(*) from manifest.market_coordinate where eligibility='eligible_land'", 1000),
    ("coordinates structural_water_exclusion",
     "select count(*) from manifest.market_coordinate where eligibility='structural_water_exclusion'", 91),
    ("coordinates outside_country_exclusion",
     "select count(*) from manifest.market_coordinate where eligibility='outside_country_exclusion'", 9),
    ("industries", "select count(*) from manifest.industry", 25),
    ("markets", "select count(*) from manifest.market", 50),
    ("geometry_version", "select count(*) from manifest.geometry_version", 2),
    ("geometry_point", "select count(*) from manifest.geometry_point", 22),
    ("treatments", "select count(*) from manifest.treatment", 600),
    ("surface_treatment", "select count(*) from manifest.surface_treatment", 700),
    # 4 seeded by 019 + DFS_MAPS_V2 (14z) added by amendment 022 (ADR-0006) = 5
    ("provider_profile", "select count(*) from manifest.provider_profile", 5),
    ("surface_config", "select count(*) from manifest.surface_config", 4),
    ("surfaces seeded", "select count(*) from manifest.surface", 5),
    ("qa_contract_version", "select count(*) from ops.qa_contract_version", 1),
    ("qa_rule rows", "select count(*) from ops.qa_rule", 80),
    ("methodology_version frozen",
     "select count(*) from manifest.methodology_version where status='frozen' and frozen_at is not null", 1),
]


def migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def resolve_dsn(arg_dsn: str | None) -> str:
    dsn = arg_dsn or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise SystemExit(
            "no target database: pass --dsn or set SUPABASE_DB_URL "
            "(e.g. postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres)")
    return dsn


def _schema_already_present(conn) -> bool:
    row = conn.execute(
        "select to_regclass('manifest.market_coordinate') is not null"
    ).fetchone()
    return bool(row and row[0])


def apply_all(conn, files: list[pathlib.Path]) -> None:
    """Apply each file atomically via the libpq simple-query protocol.

    Using pgconn.exec_ (not cursor.execute) runs the whole file as one server-side
    command string -- multi-statement DDL, dollar-quoted function bodies and literal
    '%' all pass through untouched -- wrapped in BEGIN/COMMIT so a failing file rolls
    back cleanly and nothing partial is left behind.
    """
    import psycopg

    for f in files:
        sql = f.read_text()
        script = b"BEGIN;\n" + sql.encode("utf-8") + b"\nCOMMIT;\n"
        res = conn.pgconn.exec_(script)
        if res.status not in (psycopg.pq.ExecStatus.COMMAND_OK,
                              psycopg.pq.ExecStatus.TUPLES_OK):
            conn.pgconn.exec_(b"ROLLBACK;")  # abandon the aborted transaction
            msg = res.error_message.decode("utf-8", "replace").strip()
            print(f"  {f.name:<45} FAIL")
            raise SystemExit(f"migration {f.name} failed:\n{msg}")
        print(f"  {f.name:<45} ok")


def verify(conn) -> int:
    results = []
    for label, sql, expected in RECON_CHECKS:
        got = conn.execute(sql).fetchone()[0]
        results.append((label, f"{got} (exp {expected})", "PASS" if got == expected else "FAIL"))
    print(f"\n{'check':<48} {'result':<22} status")
    print("-" * 84)
    failed = 0
    for label, result, status in results:
        failed += status == "FAIL"
        print(f"{label:<48} {result:<22} {status}")
    print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Apply LSI migrations to a target Postgres and verify reconciliation.")
    p.add_argument("--dsn", default=None, help="target connection string; falls back to $SUPABASE_DB_URL")
    p.add_argument("--check-only", action="store_true", help="skip applying; only run the reconciliation checks")
    p.add_argument("--dry-run", action="store_true", help="list the migration files that would be applied; no connection")
    p.add_argument("--force", action="store_true",
                   help="apply even if the schema is already present (will error on existing objects)")
    args = p.parse_args(argv)

    files = migration_files()
    if not files:
        raise SystemExit(f"no migrations found under {MIGRATIONS_DIR}")

    if args.dry_run:
        print(f"{len(files)} migrations under {MIGRATIONS_DIR}:")
        for f in files:
            print(f"  {f.name}")
        return 0

    import psycopg

    dsn = resolve_dsn(args.dsn)  # never printed
    with psycopg.connect(dsn, autocommit=True) as conn:
        present = _schema_already_present(conn)
        if args.check_only:
            if not present:
                raise SystemExit("--check-only: the LSI schema is not present on the target database")
            return verify(conn)

        if present and not args.force:
            raise SystemExit(
                "target database already has the LSI schema (manifest.market_coordinate exists).\n"
                "Migrations are not idempotent -- re-applying will error on existing objects.\n"
                "Use --check-only to re-verify the reconciliation, or --force to attempt a re-apply.")

        print(f"applying {len(files)} migrations ...")
        apply_all(conn, files)
        return verify(conn)


if __name__ == "__main__":
    sys.exit(main())
