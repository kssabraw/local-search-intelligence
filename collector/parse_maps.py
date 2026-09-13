"""Pure parser: DataForSEO Maps advanced response -> ParsedMaps.

Deterministic Python parsing before any LLM (CLAUDE.md). No I/O. A valid empty
result is a real observation ('returned'), never an error. Unexpected structure
is 'parser_failure'; a provider error status is 'provider_failure'.
"""
from __future__ import annotations
from typing import Any, Optional

from .models import MapsItem, ParsedMaps

DFS_OK = 20000


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


def _rating(item: dict[str, Any]) -> tuple[Optional[float], Optional[int]]:
    r = item.get("rating")
    if isinstance(r, dict):
        return _to_float(r.get("value")), _to_int(r.get("votes_count"))
    return _to_float(r), _to_int(item.get("reviews_count") or item.get("votes_count"))


def parse_maps(response: dict[str, Any]) -> ParsedMaps:
    tasks = response.get("tasks") or []
    if not tasks:
        return ParsedMaps("parser_failure", None, None, {"reason": "no tasks in response"}, [], _to_float(response.get("cost")), None)
    task = tasks[0]
    task_id = task.get("id")
    cost = _to_float(task.get("cost")) if task.get("cost") is not None else _to_float(response.get("cost"))

    if task.get("status_code") != DFS_OK:
        return ParsedMaps(
            "provider_failure", None, None,
            {"status_code": task.get("status_code"), "status_message": task.get("status_message")},
            [], cost, task_id,
        )

    results = task.get("result") or []
    if not results:
        # provider accepted but returned no result block: a valid (empty) observation
        return ParsedMaps("returned", 0, None, {"result_count": task.get("result_count", 0)}, [], cost, task_id)

    result = results[0]
    raw_items = result.get("items") or []
    depth = _to_int(result.get("items_count"))
    search_metadata = {
        "keyword": result.get("keyword"),
        "type": result.get("type"),
        "se_domain": result.get("se_domain"),
        "location_code": result.get("location_code"),
        "language_code": result.get("language_code"),
        "check_url": result.get("check_url"),
        "datetime": result.get("datetime"),
        "items_count": result.get("items_count"),
    }

    items: list[MapsItem] = []
    for seq, it in enumerate(raw_items, start=1):
        rating, reviews = _rating(it)
        items.append(MapsItem(
            result_sequence=seq,
            rank_absolute=_to_int(it.get("rank_absolute")),
            rank_group=_to_int(it.get("rank_group")),
            provider_item_type=it.get("type"),
            title_raw=it.get("title"),
            category_raw=it.get("category"),
            rating=rating,
            review_count=reviews,
            address_raw=it.get("address"),
            phone_raw=it.get("phone"),
            latitude=_to_float(it.get("latitude")),
            longitude=_to_float(it.get("longitude")),
            url_raw=it.get("url"),
            domain_raw=it.get("domain"),
            place_id=it.get("place_id"),
            cid=str(it.get("cid")) if it.get("cid") is not None else None,
            provider_fields=it,
        ))
    return ParsedMaps("returned", len(items), depth, search_metadata, items, cost, task_id)
