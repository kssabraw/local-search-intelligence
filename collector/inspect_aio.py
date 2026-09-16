"""AIO capture-feasibility structural inspector (ADR-0005, AIO PRD).

The AIO surface is behind the ADR-0005 per-surface capture gate: before we trust
(or extend) the ``aio.*`` schema, we must PROVE the provider actually returns the
fields the AIO measurement model requires, and mark everything it does not return
``provider_not_observable`` rather than as empty columns implying absence.

``inspect_aio_capture`` answers that question deterministically for one DataForSEO
AI Mode / AI Overview ``task_get`` advanced response. It is:

  * **Pure Python** -- no LLM. Per the parent PRD's hard rule, an LLM never
    re-extracts structured provider fields; this walks the raw JSON and inventories
    what is present. (The heavier normalization into ``aio.*`` is deliberately NOT
    done here -- that is committed only AFTER the probe proves feasibility.)
  * **Schema-agnostic / defensive.** DataForSEO's exact AI-surface schema is not
    assumed: the walker recurses the whole response and detects capabilities by
    structure + value patterns (a ``rectangle`` object anywhere, a ``references``
    array, GBP/SearchViewer destination URLs, ...), and always emits a raw
    ``structure_fingerprint`` (every observed item ``type`` + the key sets seen)
    so a human can verify the verdicts against the immutable raw payload.

Each capability the AIO PRD requires (element-level structure + rectangles [PRD
Sec.17/32], reference-vs-inline-link citations [Sec.18], local-business-card
modules + embedded GBP + SearchViewer/Maps destinations [Sec.69]) gets a verdict:

  * ``present``   -- found, with evidence (JSON paths / sample keys / counts).
  * ``absent``    -- a valid AIO block came back but this field was not in it
                     (=> build no column; mark ``provider_not_observable``).
  * ``uncertain`` -- no AIO block came back at all in this response, so this
                     response cannot speak to the field (roll-up decides across
                     the whole probe wave).

This module makes NO network call and NO DB write; it is a pure function over a
parsed provider response, unit-tested against synthetic fixtures and run live
(over immutable raw) by ``collector.aio_probe``.
"""
from __future__ import annotations

import re
from typing import Any, Optional

INSPECTOR_VERSION = "aio-capture-inspector-0.2.0"

# Provider status codes that count as a real, returned response (not a transport
# failure). 20000 = Ok; 40102 = "No Search Results" (a valid empty observation,
# missing != zero -- consistent with collector.parse_maps).
_RETURNED_STATUS = (20000, 40102)

# The capability checklist, keyed to the AIO PRD sections. Order is stable so the
# report reads top-to-bottom as source -> element -> placement -> local surfaces.
CAPABILITY_KEYS = (
    "aio_answer_text",            # Sec.15/17: main answer text/markdown returned at all
    "element_level_structure",   # Sec.17: element/sub-element structure, not one blob
    "element_rectangles",        # Sec.17/32: pixel rectangle geometry (placement / above-fold)
    "source_citations",          # Sec.16/18: references/sources array (source visibility)
    "reference_vs_link",         # Sec.18: reference/citation distinguishable from inline link
    "local_business_cards",      # Sec.69: structured local-business-card module(s)
    "embedded_gbp",              # Sec.69: direct embedded GBP / Maps entity surface
    "destination_searchviewer",  # Sec.69: SearchViewer / Maps / GBP destination classification
    "business_position_order",   # Sec.32/69: position / rank / order for selected businesses
)

# URL/value patterns that mark a Google-hosted business destination (embedded GBP /
# Maps / SearchViewer). Used for capability detection only -- never to normalize.
_GBP_DEST_PATTERNS = (
    re.compile(r"/maps/", re.I),
    re.compile(r"google\.[^/]+/maps", re.I),
    re.compile(r"google\.[^/]+/localservices", re.I),
    re.compile(r"/local(?:_|/|\?)", re.I),
    re.compile(r"searchviewer", re.I),
    re.compile(r"[?&]tbm=lcl", re.I),
    re.compile(r"google\.[^/]+/search\?[^\"]*ludocid", re.I),
)
# Keys/type-fragments that hint at a structured local-business surface.
_LOCAL_TYPE_HINTS = ("local_pack", "local_services", "map", "places", "business",
                     "hotels_pack", "top_sights", "google_business")
_GBP_TYPE_HINTS = ("knowledge_graph", "google_business", "gbp", "local_pack", "map")
_BUSINESS_ATTR_KEYS = ("place_id", "cid", "rating", "reviews_count", "review_count",
                       "address", "phone", "feature_id")
_REFERENCE_KEYS = ("references", "sources", "citations")
_LINK_KEYS = ("links", "link", "url", "buttons", "actions")
_RECT_KEYS = ("rectangle", "rect", "bounding_box", "bounds")


def _iter_nodes(node: Any, path: str = "$"):
    """Yield (path, node) for every dict/list node in the tree, depth-first."""
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _iter_nodes(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _iter_nodes(v, f"{path}[{i}]")


def _is_rectangle(v: Any) -> bool:
    """A rectangle object: a dict carrying pixel geometry (x/y + width/height)."""
    if not isinstance(v, dict):
        return False
    keys = {k.lower() for k in v.keys()}
    has_xy = ("x" in keys and "y" in keys)
    has_wh = ("width" in keys and "height" in keys)
    return has_xy and has_wh


def _looks_like_business(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    keys = {k.lower() for k in node.keys()}
    # A business-ish node: has a title/name plus at least one local attribute.
    has_name = bool(keys & {"title", "name", "domain"})
    return has_name and bool(keys & set(_BUSINESS_ATTR_KEYS))


def _result0(get_json: dict[str, Any]) -> tuple[Optional[dict], Optional[dict], Optional[int], Optional[str], Optional[float]]:
    """Return (task, result0, status_code, status_message, cost_usd)."""
    tasks = (get_json or {}).get("tasks") or []
    task = tasks[0] if tasks else None
    status_code = task.get("status_code") if task else None
    status_message = task.get("status_message") if task else None
    cost_usd = task.get("cost") if task else None
    results = (task.get("result") if task else None) or []
    result0 = results[0] if results else None
    return task, result0, status_code, status_message, cost_usd


def _verdict(present: bool, aio_present: bool, count: int = 0, evidence: Optional[list] = None) -> dict[str, Any]:
    if present:
        v = "present"
    elif aio_present:
        v = "absent"
    else:
        v = "uncertain"
    return {"verdict": v, "count": count, "evidence": (evidence or [])[:5]}


SCOPE_RESPONSE = "response"       # whole result is the AIO content (AI Mode)
SCOPE_AI_OVERVIEW = "ai_overview"  # only the ai_overview element subtree(s) (organic SERP)


def _has_content(node: Any) -> bool:
    """A dict carrying real AIO content (answer text, references, or child items)."""
    if not isinstance(node, dict):
        return False
    if any(isinstance(node.get(k), str) and node.get(k).strip()
           for k in ("markdown", "text", "answer", "content")):
        return True
    if any(isinstance(node.get(k), list) and node.get(k) for k in _REFERENCE_KEYS):
        return True
    return isinstance(node.get("items"), list) and bool(node.get("items"))


def inspect_aio_capture(get_json: dict[str, Any], *, scope: str = SCOPE_RESPONSE) -> dict[str, Any]:
    """Inventory one AI Mode / AI Overview advanced response for AIO-PRD capture fields.

    ``scope`` decides WHERE capability detection runs:

      * ``response`` (default, AI Mode) -- the whole result IS the AI answer, so the
        detectors walk the entire response.
      * ``ai_overview`` (the organic SERP probe) -- restrict detection to the
        ``ai_overview``/``*_ai_overview_*`` element subtree(s) ONLY, so the
        ever-present SERP ``local_pack`` / ``google_reviews`` modules are NOT
        conflated with an AI-Overview-embedded local card. On the organic surface an
        AI Overview is one item among many; only its own subtree speaks to AIO
        capture.

    The structure fingerprint is always computed over the FULL response (context for
    human verification). Returns a JSON-serializable dict stored verbatim into
    ops.observation parser_metadata by the probe.
    """
    task, result0, status_code, status_message, cost_usd = _result0(get_json)
    returned = status_code in _RETURNED_STATUS
    nodes = list(_iter_nodes(result0)) if result0 is not None else []

    # ---- generic structural fingerprint (ALWAYS over the full response) ----
    item_types: dict[str, int] = {}
    key_universe: set[str] = set()
    for _, n in nodes:
        if isinstance(n, dict):
            key_universe.update(str(k) for k in n.keys())
            t = n.get("type")
            if isinstance(t, str):
                item_types[t] = item_types.get(t, 0) + 1
    top_items = (result0.get("items") if isinstance(result0, dict) else None) or []
    n_items = len(top_items) if isinstance(top_items, list) else 0
    container_type = result0.get("type") if isinstance(result0, dict) else None
    aio_element_types = [t for t in item_types
                         if ("ai_overview" in t or "ai_mode" in t) and t != container_type]

    # ---- the SCOPE the capability detectors run over ----
    # AIO "root" nodes = items whose type names an AI-Overview/AI-Mode element (never
    # the result container itself). An async, un-loaded stub (asynchronous_ai_overview
    # true, no content) is a root but carries no capture content.
    aio_roots = [(p, n) for p, n in nodes if isinstance(n, dict)
                 and ("ai_overview" in str(n.get("type") or "") or "ai_mode" in str(n.get("type") or ""))
                 and n.get("type") != container_type]
    async_stub_present = any(n.get("asynchronous_ai_overview") or not _has_content(n) for _, n in aio_roots)

    if scope == SCOPE_AI_OVERVIEW:
        seen: set[int] = set()
        scope_nodes: list[tuple[str, Any]] = []
        for p, root in aio_roots:
            for sp, sn in _iter_nodes(root, p):
                if id(sn) not in seen:
                    seen.add(id(sn))
                    scope_nodes.append((sp, sn))
        # Present only when an AI Overview element with real content came back (a bare
        # async stub does not count -> INCONCLUSIVE until loaded with load_async_ai_overview).
        content_present = any(_has_content(n) for _, n in aio_roots)
        aio_present = bool(status_code == 20000 and content_present)
    else:
        scope_nodes = nodes
        has_answer_full = any(_has_content(n) and isinstance(n, dict) and any(
            isinstance(n.get(k), str) and n.get(k).strip() for k in ("markdown", "text", "answer", "content"))
            for _, n in nodes)
        aio_present = bool(status_code == 20000 and (aio_element_types or has_answer_full))

    scope_key_universe = {str(k) for _, n in scope_nodes if isinstance(n, dict) for k in n.keys()}

    # ---- capability detections (over scope_nodes) ----
    has_answer = any(isinstance(n, dict) and any(
        isinstance(n.get(k), str) and n.get(k).strip() for k in ("markdown", "text", "answer", "content"))
        for _, n in scope_nodes)
    rect_paths = [p for p, n in scope_nodes if _is_rectangle(n) or (
        isinstance(n, dict) and any(k.lower() in _RECT_KEYS and _is_rectangle(n.get(k)) for k in n))]
    ref_paths, ref_count = [], 0
    for p, n in scope_nodes:
        if isinstance(n, dict):
            for k, v in n.items():
                if k.lower() in _REFERENCE_KEYS and isinstance(v, list) and v:
                    ref_paths.append(f"{p}.{k}")
                    ref_count += len(v)
    inline_link_paths = []
    for p, n in scope_nodes:
        if isinstance(n, dict) and not any(rp for rp in ref_paths if p.startswith(rp)):
            for k, v in n.items():
                if k.lower() == "links" and isinstance(v, list) and v:
                    inline_link_paths.append(f"{p}.{k}")
                elif k.lower() in ("is_reference", "reference"):
                    inline_link_paths.append(f"{p}.{k}")
    has_ref_flag = "is_reference" in scope_key_universe
    local_paths = []
    for p, n in scope_nodes:
        if isinstance(n, dict):
            t = str(n.get("type") or "").lower()
            if any(h in t for h in _LOCAL_TYPE_HINTS):
                local_paths.append(f"{p}({t})")
            elif _looks_like_business(n):
                local_paths.append(f"{p}(business-like)")
    gbp_type_paths = [f"{p}({str(n.get('type')).lower()})" for p, n in scope_nodes
                      if isinstance(n, dict) and any(h in str(n.get("type") or "").lower() for h in _GBP_TYPE_HINTS)]
    urls: list[str] = []
    for _, n in scope_nodes:
        if isinstance(n, dict):
            for k, v in n.items():
                if isinstance(v, str) and k.lower() in ("url", "link", "href", "destination", "source_url"):
                    urls.append(v)
    gbp_dest_urls = [u for u in urls if any(rx.search(u) for rx in _GBP_DEST_PATTERNS)]
    gbp_id_present = any(isinstance(n, dict) and (n.get("place_id") or n.get("cid") or n.get("feature_id"))
                         for _, n in scope_nodes)
    pos_present = any(isinstance(n, dict) and any(
        k.lower() in ("rank_absolute", "rank_group", "position", "order", "rank") for k in n)
        for _, n in scope_nodes)

    # No capability can read "present" when no AIO block came back: such a response
    # cannot speak to any field (verdict stays "uncertain"; the wave roll-up decides).
    def cap(flag: bool, count: int = 0, evidence: Optional[list] = None) -> dict[str, Any]:
        return _verdict(bool(flag) and aio_present, aio_present, count=count, evidence=evidence)

    capabilities = {
        "aio_answer_text": cap(has_answer, evidence=aio_element_types or ["markdown/text"]),
        "element_level_structure": cap(
            bool(aio_element_types) or (scope == SCOPE_RESPONSE and n_items > 1), count=len(aio_roots),
            evidence=aio_element_types or [f"{n_items} top items"]),
        "element_rectangles": cap(bool(rect_paths), count=len(rect_paths), evidence=rect_paths),
        "source_citations": cap(ref_count > 0, count=ref_count, evidence=ref_paths),
        "reference_vs_link": cap(
            has_ref_flag or (bool(ref_paths) and bool(inline_link_paths)),
            evidence=(["is_reference flag"] if has_ref_flag else [])
                     + [f"refs@{len(ref_paths)}", f"inline@{len(inline_link_paths)}"]),
        "local_business_cards": cap(bool(local_paths), count=len(local_paths), evidence=local_paths),
        "embedded_gbp": cap(
            bool(gbp_type_paths) or bool(gbp_dest_urls) or gbp_id_present,
            count=len(gbp_type_paths) + len(gbp_dest_urls),
            evidence=(gbp_type_paths + gbp_dest_urls) or (["place_id/cid present"] if gbp_id_present else [])),
        "destination_searchviewer": cap(bool(gbp_dest_urls), count=len(gbp_dest_urls), evidence=gbp_dest_urls),
        "business_position_order": cap(pos_present, evidence=["rank/position keys"] if pos_present else []),
    }

    return {
        "inspector_version": INSPECTOR_VERSION,
        "scope": scope,
        "provider_status_code": status_code,
        "provider_status_message": status_message,
        "returned": returned,
        "aio_present": aio_present,
        "aio_element_types": aio_element_types,
        "async_stub_present": async_stub_present,
        "provider_cost_usd": cost_usd,
        "n_top_items": n_items,
        "capabilities": capabilities,
        "structure_fingerprint": {
            "item_types": item_types,
            "key_universe": sorted(key_universe),
            "url_sample": urls[:10],
        },
    }
