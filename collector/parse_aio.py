"""Pure parser: DataForSEO Organic advanced response -> ParsedAio.

The AIO surface of record (ADR-0008) is the AI Overview EMBEDDED in the organic
Google SERP, captured on the organic endpoint (`DFS_AIO_V2`, load_async_ai_overview
+ calculate_rectangles). ONE response therefore carries two tracks: the organic
results + Local Pack (parsed by `parse_organic`, for the H3 within-observation
join) and the `ai_overview` block (parsed here into the aio.* model).

Deterministic Python parsing before any LLM (CLAUDE.md) — no I/O, no LLM. Mirrors
`parse_organic`: a valid provider status with NO `ai_overview` block is a real
observation with `aio_triggered=false` (the PREVALENCE negative / denominator —
missing != zero, NEVER `provider_not_observable`); 40102 "No Search Results" is a
valid empty observation; a provider error status is `provider_failure`; unexpected
structure is `parser_failure`.

This module reuses the shipped, tested helpers `aio_destination.classify_destination`
(AIO PRD Sec.69 destination_type) and `aio_destination.decode_searchviewer_svid`
(SearchViewer svid -> Knowledge-Graph MID) to classify each reference card as a
website *source* or a *business* appearance and to key the business by KG-MID.
"""
from __future__ import annotations
from typing import Any, Optional

from .aio_destination import (DEST_MAPS, DEST_SEARCHVIEWER, classify_destination,
                              decode_searchviewer_svid)
from .models import AioLink, AioPresentationUnit, AioReference, ParsedAio

DFS_OK = 20000
DFS_NO_RESULTS = 40102
AIO_TYPE = "ai_overview"
AIO_ELEMENT_TYPE = "ai_overview_element"

# A reference whose destination resolves to one of these types is a GBP / business
# surface (grounded in the ADR-0005 probe: businesses appear as SearchViewer deep
# links, occasionally Maps), so it becomes an aio.business_appearance + destination
# keyed by Knowledge-Graph MID rather than a website source_occurrence.
_BUSINESS_DEST_TYPES = frozenset({DEST_SEARCHVIEWER, DEST_MAPS})


def _to_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _rectangle(node: Any) -> Optional[dict[str, Any]]:
    """Return {x,y,width,height} ints if the node carries a pixel rectangle, else None."""
    if not isinstance(node, dict):
        return None
    r = node.get("rectangle")
    if not isinstance(r, dict):
        return None
    keys = {k.lower() for k in r.keys()}
    if not ({"x", "y"} <= keys and {"width", "height"} <= keys):
        return None
    return {"x": _to_int(r.get("x")), "y": _to_int(r.get("y")),
            "width": _to_int(r.get("width")), "height": _to_int(r.get("height"))}


def _has_body(aio: dict[str, Any]) -> bool:
    """A loaded AI Overview body: markdown/text, references, or element items present."""
    if any(isinstance(aio.get(k), str) and aio.get(k).strip()
           for k in ("markdown", "text", "answer", "content")):
        return True
    if isinstance(aio.get("references"), list) and aio.get("references"):
        return True
    return isinstance(aio.get("items"), list) and bool(aio.get("items"))


def _parse_links(element: dict[str, Any], unit_sequence: int) -> list[AioLink]:
    out: list[AioLink] = []
    for lk in element.get("links") or []:
        if isinstance(lk, dict):
            out.append(AioLink(unit_sequence=unit_sequence,
                               title_raw=lk.get("title") or lk.get("text"),
                               url_raw=lk.get("url") or lk.get("link")))
    return out


def _parse_reference(seq: int, ref: dict[str, Any]) -> AioReference:
    url = ref.get("url") or ref.get("link")
    dest_type = classify_destination(url)
    is_business = dest_type in _BUSINESS_DEST_TYPES
    kg_mid = decode_searchviewer_svid(url) if is_business else None
    return AioReference(
        ref_sequence=seq,
        source_raw=ref.get("source") or ref.get("publisher"),
        domain_raw=ref.get("domain"),
        url_raw=url,
        title_raw=ref.get("title"),
        snippet_raw=ref.get("text") or ref.get("snippet"),
        image_url_raw=ref.get("image_url") or ref.get("favicon") or ref.get("image"),
        datetime_raw=ref.get("datetime") or ref.get("date"),
        rank_absolute=_to_int(ref.get("rank_absolute")),
        rank_group=_to_int(ref.get("rank_group")),
        is_reference=ref.get("is_reference"),
        rectangle=_rectangle(ref),
        destination_type=dest_type,
        is_business=is_business,
        kg_mid=kg_mid,
        provider_fields=ref,
    )


def _empty_aio(state: str, cost: Optional[float], task_id: Optional[str],
               metadata: dict[str, Any]) -> ParsedAio:
    """An observation with NO AI Overview: the prevalence negative (aio_triggered=false,
    form='absent'). Valid for a returned SERP that simply had no AIO, and for a
    provider/parser failure (which the caller records as a terminal failure)."""
    return ParsedAio(
        observation_state=state, aio_triggered=False, aio_presentation_form="absent",
        async_ai_overview_loaded=False, response_text_raw=None, response_markdown_raw=None,
        serp_rank_absolute=None, serp_rank_group=None, serp_position=None, serp_rectangle=None,
        serp_preceding_block_count=None, serp_preceding_block_types=None,
        presentation_units=[], references=[], response_metadata=metadata,
        provider_cost_usd=cost, provider_task_id=task_id,
    )


def parse_aio(response: dict[str, Any]) -> ParsedAio:
    tasks = response.get("tasks") or []
    if not tasks:
        return _empty_aio("parser_failure", None, None, {"reason": "no tasks in response"})
    task = tasks[0]
    task_id = task.get("id")
    cost = task.get("cost")
    try:
        cost = float(cost) if cost is not None and cost != "" else None
    except (TypeError, ValueError):
        cost = None

    tsc = task.get("status_code")
    if tsc not in (DFS_OK, DFS_NO_RESULTS):
        return _empty_aio("provider_failure", cost, task_id,
                          {"status_code": tsc, "status_message": task.get("status_message")})

    results = task.get("result") or []
    if tsc == DFS_NO_RESULTS or not results:
        # A completed task with an empty SERP: no AIO, a valid prevalence negative.
        return _empty_aio("returned", cost, task_id,
                          {"status_code": tsc, "status_message": task.get("status_message"),
                           "result_count": task.get("result_count", 0)})

    result = results[0]
    raw_items = result.get("items") or []

    # Locate the standalone ai_overview block among the SERP items (PAA-embedded AIO
    # is out of scope, ADR-0008 Sec.3 -> only a top-level `ai_overview` item counts).
    aio_index: Optional[int] = None
    aio_block: Optional[dict[str, Any]] = None
    for idx, it in enumerate(raw_items):
        if isinstance(it, dict) and it.get("type") == AIO_TYPE:
            aio_index, aio_block = idx, it
            break

    base_metadata = {
        "keyword": result.get("keyword"), "check_url": result.get("check_url"),
        "datetime": result.get("datetime"), "item_types": result.get("item_types"),
        "location_code": result.get("location_code"), "language_code": result.get("language_code"),
        "total_block_count": len(raw_items),
    }

    if aio_block is None:
        # SERP returned, but no AI Overview block: the prevalence negative.
        return _empty_aio("returned", cost, task_id, {**base_metadata, "aio_triggered": False})

    # SERP placement: where the AIO block sits among ALL SERP items (top vs middle).
    preceding = [it for it in raw_items[:aio_index] if isinstance(it, dict)]
    preceding_types = [str(it.get("type")) for it in preceding if it.get("type") is not None]
    serp_rect = _rectangle(aio_block)

    loaded = _has_body(aio_block)
    is_stub = bool(aio_block.get("asynchronous_ai_overview")) and not loaded
    form = "async_stub" if is_stub else "standalone"

    markdown = aio_block.get("markdown")
    text = aio_block.get("text") or aio_block.get("answer") or markdown

    units: list[AioPresentationUnit] = []
    for useq, el in enumerate((aio_block.get("items") or []), start=1):
        if not isinstance(el, dict):
            continue
        units.append(AioPresentationUnit(
            unit_sequence=useq,
            unit_type=el.get("type") or AIO_ELEMENT_TYPE,
            heading_raw=el.get("title") or el.get("heading"),
            text_raw=el.get("text") or el.get("description"),
            rectangle=_rectangle(el),
            links=_parse_links(el, useq),
            provider_fields=el,
        ))

    references: list[AioReference] = []
    for rseq, ref in enumerate((aio_block.get("references") or []), start=1):
        if isinstance(ref, dict):
            references.append(_parse_reference(rseq, ref))

    return ParsedAio(
        observation_state="returned",
        aio_triggered=True,
        aio_presentation_form=form,
        async_ai_overview_loaded=loaded,
        response_text_raw=text if isinstance(text, str) else None,
        response_markdown_raw=markdown if isinstance(markdown, str) else None,
        serp_rank_absolute=_to_int(aio_block.get("rank_absolute")),
        serp_rank_group=_to_int(aio_block.get("rank_group")),
        serp_position=aio_block.get("position"),
        serp_rectangle=serp_rect,
        serp_preceding_block_count=len(preceding),
        serp_preceding_block_types=preceding_types,
        presentation_units=units,
        references=references,
        response_metadata={**base_metadata, "aio_triggered": True,
                           "aio_presentation_form": form, "async_ai_overview_loaded": loaded},
        provider_cost_usd=cost,
        provider_task_id=task_id,
    )
