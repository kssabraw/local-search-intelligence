#!/usr/bin/env python3
"""Split the authoritative single-file physical schema into ordered migrations.

Source of truth: supabase/schema/physical-schema-v0_1.sql (the authoritative
artifact imported from Drive; see docs/AUTHORITATIVE-ARTIFACTS.md).

This script performs a MECHANICAL split at the deployment-order boundaries
declared in docs/contracts/physical-schema-contract-v0_1.md section 36, so the
concatenation of migrations 001..018 is byte-equivalent to the body of the
authoritative file (minus the single outer `begin;`/`commit;`) EXCEPT for one
clearly-labelled reconciliation:

  * manifest.coordinate_eligibility gains the value `outside_country_exclusion`.
    The frozen Manifest v1.0 geography classifies 9 coordinates as
    outside_country_exclusion (see manifest/SED_Geo_Eligibility_Report_v1_0.json)
    and CONTEXT.md / CLAUDE.md both define it as a first-class missingness
    state. The authoritative SQL enum omitted it; without the value the frozen
    manifest cannot be represented without collapsing a distinct missingness
    state (which "missing != zero" forbids). Adding the value implements an
    already-decided methodology state; it does not change methodology.

Re-run with:  python3 scripts/split_schema_to_migrations.py
It rewrites supabase/migrations/001_*.sql .. 018_*.sql deterministically.
"""
from __future__ import annotations
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "supabase" / "schema" / "physical-schema-v0_1.sql"
OUT = ROOT / "supabase" / "migrations"

# (number, name, start_line, end_line) 1-indexed inclusive, over the authoritative file.
SECTIONS = [
    ("001", "extensions_and_schemas", 18, 31),
    ("002", "controlled_types", 33, 112),
    ("003", "provider_component_and_price_registries", 114, 157),
    ("004", "manifest", 159, 388),
    ("005", "core_entity_base", 390, 461),
    ("006", "ops_collection_and_raw", 463, 674),
    ("007", "core_resolution", 676, 809),
    ("008", "maps", 811, 847),
    ("009", "organic", 849, 880),
    ("010", "aio", 882, 975),
    ("011", "chatgpt", 977, 1136),
    ("012", "enrichment", 1138, 1362),
    ("013", "research", 1364, 1558),
    ("014", "client", 1560, 1583),
    ("015", "indexes", 1585, 1765),
    ("016", "views", 1767, 1811),
    ("017", "immutability_triggers", 1813, 1985),
    ("018", "seed_lookups", 1987, 2088),
]

HEADER = """-- Migration {num}_{name}
-- SED Local Search Intelligence Platform -- physical schema v0.1
--
-- Mechanical split of supabase/schema/physical-schema-v0_1.sql (the
-- authoritative artifact) at the deployment-order boundaries declared in
-- docs/contracts/physical-schema-contract-v0_1.md section 36. See
-- supabase/migrations/README.md. Do NOT hand-edit; regenerate with
-- scripts/split_schema_to_migrations.py.
--
-- Research schemas are private: no grants to anon/authenticated are issued.
-- Product-facing RLS/auth is deferred to a later security contract (migration
-- 020_security in the contract's order; intentionally not created yet).
"""

RECONCILE_NOTE = """
-- RECONCILIATION (not a methodology change): the value
-- 'outside_country_exclusion' is added to manifest.coordinate_eligibility.
-- The frozen Manifest v1.0 geography classifies 9 coordinates as
-- outside_country_exclusion and CONTEXT.md / CLAUDE.md define it as a
-- first-class missingness state; the authoritative single-file SQL omitted the
-- enum value. See supabase/migrations/README.md.
"""


def main() -> None:
    lines = SRC.read_text().splitlines(keepends=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for num, name, start, end in SECTIONS:
        body = "".join(lines[start - 1:end]).rstrip("\n") + "\n"
        if num == "002":
            needle = (
                "create type manifest.coordinate_eligibility as enum (\n"
                "  'pending',\n"
                "  'eligible_land',\n"
                "  'structural_water_exclusion',\n"
                "  'manual_review',\n"
                "  'configuration_failure'\n"
                ");"
            )
            replacement = (
                "create type manifest.coordinate_eligibility as enum (\n"
                "  'pending',\n"
                "  'eligible_land',\n"
                "  'structural_water_exclusion',\n"
                "  'outside_country_exclusion',\n"
                "  'manual_review',\n"
                "  'configuration_failure'\n"
                ");"
            )
            if needle not in body:
                raise SystemExit("002: coordinate_eligibility enum not found unchanged; aborting.")
            body = body.replace(needle, replacement + "\n" + RECONCILE_NOTE.rstrip() + "\n")
        text = HEADER.format(num=num, name=name) + "\n" + body
        (OUT / f"{num}_{name}.sql").write_text(text)
        print(f"wrote {num}_{name}.sql ({end - start + 1} source lines)")


if __name__ == "__main__":
    main()
