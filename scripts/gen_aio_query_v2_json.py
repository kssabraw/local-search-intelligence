#!/usr/bin/env python3
"""Build the frozen AIO_QUERY_V2 condition library (manifest/aio_query_v2_conditions.json).

Deterministic composition of the two authoritative sources, so the frozen artifact is
never hand-transcribed:

  * C01, C02, C03, C04, C09, C10 are KEPT VERBATIM from the seeded ``AIO_QUERY_V1`` set
    (parsed out of ``supabase/migrations/019_manifest_v1_data.sql``) — same exact
    templates, families, city-slot flags and V1 approval basis.
  * C05, C06, C07, C08 are the owner-signed-off conversational intents (parsed out of
    ``docs/design/aio-query-v2-conversational-conditions-v0_1.md``): C05 problem-led,
    C06 duress / immediate-need, C07 price / value, C08 criteria / decision-support.

Run: python scripts/gen_aio_query_v2_json.py  (writes the JSON; --check verifies in place)

This is a build tool, not part of the runtime. No DB, no network, no paid call. Rerun it
whenever the design doc wording changes, then regenerate migration 029.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIG_019 = ROOT / "supabase" / "migrations" / "019_manifest_v1_data.sql"
DESIGN_DOC = ROOT / "docs" / "design" / "aio-query-v2-conversational-conditions-v0_1.md"
OUT = ROOT / "manifest" / "aio_query_v2_conditions.json"

TREATMENT_SET = "AIO_QUERY_V2"
SOURCE_TAG = "AIO_QUERY_V2-2026-09-19-owner-signoff"

# The conditions kept verbatim from V1, and the new conversational ones.
KEPT_CODES = ["AIO_C01", "AIO_C02", "AIO_C03", "AIO_C04", "AIO_C09", "AIO_C10"]
NEW_ROLE = {
    "AIO_C05": "problem_led",
    "AIO_C06": "duress_immediate",
    "AIO_C07": "price_value",
    "AIO_C08": "criteria_decision",
}
# Order of the 10 conditions in the frozen set (sequence 1..10).
SEQUENCE = ["AIO_C01", "AIO_C02", "AIO_C03", "AIO_C04", "AIO_C05",
            "AIO_C06", "AIO_C07", "AIO_C08", "AIO_C09", "AIO_C10"]

# Parse one seeded V1 treatment VALUES row. Templates/families never contain a single
# quote in this set, so a field-by-field single-quote parse is exact.
V1_ROW = re.compile(
    r"^\s*\('(IND\d+)',\s*'AIO_QUERY_V1',\s*'(AIO_C\d+)',\s*'query',\s*"
    r"'([^']*)',\s*(null|'[^']*'),\s*'([^']*)',\s*(\d+),\s*(true|false),\s*'([^']*)',"
)

# Parse a "- C0x: `...`" line under a "**INDxxx ...**" heading in the design doc.
DOC_HEAD = re.compile(r"^\*\*(IND\d+)\b")
DOC_COND = re.compile(r"^- (C0\d):\s*`([^`]*)`")


def parse_v1_kept() -> dict[str, dict[str, dict]]:
    """industry -> code -> {template, family, city_slot, approval} for the kept codes."""
    kept: dict[str, dict[str, dict]] = {}
    for line in MIG_019.read_text().splitlines():
        m = V1_ROW.match(line)
        if not m:
            continue
        ind, code, family, _cqc, template, _seq, city_slot, approval = m.groups()
        if code not in KEPT_CODES:
            continue
        kept.setdefault(ind, {})[code] = {
            "template": template,
            "family": family,
            "city_slot_required": (city_slot == "true"),
            "approval_basis": approval,
        }
    return kept


def parse_doc_new() -> dict[str, dict[str, str]]:
    """industry -> {'AIO_C05': template, ...} from the design doc's C05-C08 library."""
    new: dict[str, dict[str, str]] = {}
    current: str | None = None
    for line in DESIGN_DOC.read_text().splitlines():
        line = line.strip()
        h = DOC_HEAD.match(line)
        if h:
            current = h.group(1)
            continue
        c = DOC_COND.match(line)
        if c and current:
            label, text = c.group(1), c.group(2)  # label like "C05"
            new.setdefault(current, {})[f"AIO_{label}"] = text
    return new


def build() -> dict:
    kept = parse_v1_kept()
    new = parse_doc_new()
    industries = sorted(set(kept) & set(new), key=lambda s: int(s[3:]))
    if len(industries) != 25:
        raise SystemExit(
            f"expected 25 industries in both sources, got kept={len(kept)} "
            f"doc={len(new)} intersect={len(industries)}")

    out_inds = []
    for ind in industries:
        conds = []
        for seq, code in enumerate(SEQUENCE, start=1):
            if code in KEPT_CODES:
                k = kept[ind][code]
                conds.append({
                    "condition_id": code,
                    "sequence": seq,
                    "family": k["family"],
                    "condition_role": k["family"],
                    "exact_template": k["template"],
                    "city_slot_required": k["city_slot_required"],
                    "derivation": "kept_from_v1",
                    "approval_basis": k["approval_basis"],
                })
            else:
                tmpl = new[ind][code]
                conds.append({
                    "condition_id": code,
                    "sequence": seq,
                    "family": NEW_ROLE[code],
                    "condition_role": NEW_ROLE[code],
                    "exact_template": tmpl,
                    "city_slot_required": ("[CITY]" in tmpl),
                    "derivation": "conversational_v2",
                    "approval_basis": "OWNER_CONFIRMED_2026_09_19",
                })
        # Every new conversational condition must carry a [CITY] slot (per the draft).
        for c in conds:
            if c["derivation"] == "conversational_v2" and not c["city_slot_required"]:
                raise SystemExit(f"{ind} {c['condition_id']} has no [CITY] slot: {c['exact_template']!r}")
        out_inds.append({"industry_code": ind, "conditions": conds})

    return {
        "treatment_set_code": TREATMENT_SET,
        "treatment_kind": "query",
        "source_methodology_version": SOURCE_TAG,
        "provenance": {
            "kept_from_v1": KEPT_CODES,
            "conversational_v2": list(NEW_ROLE),
            "kept_source": "supabase/migrations/019_manifest_v1_data.sql (AIO_QUERY_V1)",
            "conversational_source": "docs/design/aio-query-v2-conversational-conditions-v0_1.md",
            "owner_signoff": "2026-09-19 — C07/C08 normalized to one template; C06 adapted last-minute framing for discretionary/food",
        },
        "industries": out_inds,
    }


def main() -> int:
    payload = build()
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        current = OUT.read_text() if OUT.exists() else ""
        if current != text:
            print("OUT OF DATE: manifest/aio_query_v2_conditions.json differs from generator output")
            return 1
        print("OK: manifest/aio_query_v2_conditions.json matches generator")
        return 0
    OUT.write_text(text)
    n = sum(len(i["conditions"]) for i in payload["industries"])
    print(f"wrote {OUT.relative_to(ROOT)}: {len(payload['industries'])} industries, {n} conditions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
