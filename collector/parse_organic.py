"""Pure parser: DataForSEO Organic advanced response -> ParsedOrganic.

Deterministic Python parsing before any LLM (CLAUDE.md). No I/O. Mirrors
parse_maps: a valid empty result is a real observation ('returned'), never an
error (missing != zero); unexpected structure is 'parser_failure'; a provider
error status is 'provider_failure'; 40102 "No Search Results" is a valid empty
observation.

The advanced endpoint returns a heterogeneous item list (organic, local_pack,
people_also_ask, related_searches, ...). EVERY block is preserved as an item
(result_type kept); only an organic web destination is flagged `is_destination`
so the normalizer resolves it to a canonical web entity. `returned_result_count`
counts the organic-type items (the Organic surface's result depth); the total
block count is preserved in `serp_metadata`.
"""
from __future__ import annotations
from typing import Any, Optional

from .models import OrganicItem, ParsedOrganic

DFS_OK = 20000
ORGANIC_TYPE = "organic"


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def parse_organic(response: dict[str, Any]) -> ParsedOrganic:
    tasks = response.get("tasks") or []
    if not tasks:
        return ParsedOrganic("parser_failure", None, None, {"reason": "no tasks in response"}, [],
                             _to_float(response.get("cost")), None)
    task = tasks[0]
    task_id = task.get("id")
    cost = _to_float(task.get("cost")) if task.get("cost") is not None else _to_float(response.get("cost"))

    tsc = task.get("status_code")
    if tsc != DFS_OK:
        md = {"status_code": tsc, "status_message": task.get("status_message")}
        # 40102 "No Search Results" is a completed task with an empty result set
        # -- a VALID empty scientific observation, not a technical failure
        # (missing != zero; never retried for a "better" result).
        if tsc == 40102:
            return ParsedOrganic("returned", 0, None, md, [], cost, task_id)
        return ParsedOrganic("provider_failure", None, None, md, [], cost, task_id)

    results = task.get("result") or []
    if not results:
        # provider accepted but returned no result block: a valid (empty) observation
        return ParsedOrganic("returned", 0, None, {"result_count": task.get("result_count", 0)}, [], cost, task_id)

    result = results[0]
    raw_items = result.get("items") or []
    total_blocks = _to_int(result.get("items_count"))

    items: list[OrganicItem] = []
    organic_count = 0
    for seq, it in enumerate(raw_items, start=1):
        result_type = it.get("type")
        domain = it.get("domain")
        url = it.get("url")
        is_destination = result_type == ORGANIC_TYPE and bool(domain or url)
        if result_type == ORGANIC_TYPE:
            organic_count += 1
        items.append(OrganicItem(
            result_sequence=seq,
            rank_absolute=_to_int(it.get("rank_absolute")),
            rank_group=_to_int(it.get("rank_group")),
            result_type=result_type,
            title_raw=it.get("title"),
            # organic items expose the snippet as `description`; some blocks use `snippet`
            snippet_raw=it.get("description") or it.get("snippet"),
            url_raw=url,
            domain_raw=domain,
            page_number=_to_int(it.get("page")),
            position_on_page=_to_int(it.get("position_on_page")),
            is_destination=is_destination,
            provider_fields=it,
        ))

    serp_metadata = {
        "keyword": result.get("keyword"),
        "type": result.get("type"),
        "se_domain": result.get("se_domain"),
        "location_code": result.get("location_code"),
        "language_code": result.get("language_code"),
        "check_url": result.get("check_url"),
        "datetime": result.get("datetime"),
        "items_count": result.get("items_count"),
        "se_results_count": result.get("se_results_count"),
        "item_types": result.get("item_types"),
        "total_block_count": len(items),
        "organic_result_count": organic_count,
    }
    return ParsedOrganic("returned", organic_count, total_blocks, serp_metadata, items, cost, task_id)
