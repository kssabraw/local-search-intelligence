"""Plain data structures shared across the vertical slice."""
from __future__ import annotations
import dataclasses
from typing import Any, Optional


@dataclasses.dataclass(frozen=True)
class ManifestContext:
    """Resolved manifest identifiers needed to plan one collection job."""
    methodology_version_id: str
    methodology_code: str
    surface_id: str
    surface_code: str
    industry_id: str
    market_id: str
    market_city: str
    surface_treatment_id: str
    treatment_id: str
    treatment_code: str
    treatment_kind: str
    exact_template: str
    city_slot_required: bool
    coordinate_id: str
    coordinate_code: str
    latitude: float
    longitude: float
    eligibility: str
    provider_profile_id: str
    provider_id: str
    post_endpoint: str
    get_endpoint: str
    location_template: str
    language_code: Optional[str]
    device: Optional[str]
    operating_system: Optional[str]
    result_depth: Optional[int]


@dataclasses.dataclass(frozen=True)
class MapsItem:
    """One normalized item parsed from a DataForSEO Maps advanced response."""
    result_sequence: int
    rank_absolute: Optional[int]
    rank_group: Optional[int]
    provider_item_type: Optional[str]
    title_raw: Optional[str]
    category_raw: Optional[str]
    rating: Optional[float]
    review_count: Optional[int]
    address_raw: Optional[str]
    phone_raw: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    url_raw: Optional[str]
    domain_raw: Optional[str]
    place_id: Optional[str]
    cid: Optional[str]
    provider_fields: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ParsedMaps:
    observation_state: str          # ops.observation_state, e.g. 'returned'
    returned_result_count: Optional[int]
    provider_depth: Optional[int]
    search_metadata: dict[str, Any]
    items: list[MapsItem]
    provider_cost_usd: Optional[float]
    provider_task_id: Optional[str]


@dataclasses.dataclass(frozen=True)
class OrganicItem:
    """One item block parsed from a DataForSEO Organic advanced SERP response.

    A DataForSEO organic 'advanced' response is a heterogeneous item list
    (`organic`, `local_pack`, `people_also_ask`, `related_searches`, ...). Every
    block becomes an `organic.result` row (result_type preserved); only an
    organic web destination (`is_destination`) additionally becomes a
    `core.observed_object` and is resolved to a canonical web entity.
    """
    result_sequence: int
    rank_absolute: Optional[int]
    rank_group: Optional[int]
    result_type: Optional[str]
    title_raw: Optional[str]
    snippet_raw: Optional[str]
    url_raw: Optional[str]
    domain_raw: Optional[str]
    page_number: Optional[int]
    position_on_page: Optional[int]
    is_destination: bool
    provider_fields: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ParsedOrganic:
    observation_state: str          # ops.observation_state, e.g. 'returned'
    returned_result_count: Optional[int]   # count of organic-type result items
    provider_depth: Optional[int]          # total SERP item blocks returned
    serp_metadata: dict[str, Any]
    items: list[OrganicItem]
    provider_cost_usd: Optional[float]
    provider_task_id: Optional[str]


# ---------------------------------------------------------------------------
# AIO (organic AI Overview) — ADR-0008 surface of record. One organic-endpoint
# response carries the AI Overview (parsed here) AND the organic + Local-Pack
# context (parsed by ParsedOrganic on the same response).
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AioLink:
    """An inline answer-text link (``ai_overview_link``) — a citation distinct from
    a sidebar reference card (AIO PRD Sec.18)."""
    unit_sequence: Optional[int]    # the presentation unit it appeared in (None = element-less)
    title_raw: Optional[str]
    url_raw: Optional[str]


@dataclasses.dataclass(frozen=True)
class AioPresentationUnit:
    """One ``ai_overview_element`` child of the AI Overview block."""
    unit_sequence: int
    unit_type: str
    heading_raw: Optional[str]
    text_raw: Optional[str]
    rectangle: Optional[dict[str, Any]]     # {x,y,width,height} or None
    links: list[AioLink]
    provider_fields: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class AioReference:
    """One ``references[]`` sidebar card. Classified by its destination URL into a
    website *source* (a citation) or a *business* appearance (a GBP/SearchViewer
    surface resolved by Knowledge-Graph MID)."""
    ref_sequence: int
    source_raw: Optional[str]       # publisher
    domain_raw: Optional[str]
    url_raw: Optional[str]
    title_raw: Optional[str]
    snippet_raw: Optional[str]
    image_url_raw: Optional[str]
    datetime_raw: Optional[str]
    rank_absolute: Optional[int]
    rank_group: Optional[int]
    is_reference: Optional[bool]
    rectangle: Optional[dict[str, Any]]
    destination_type: str           # aio_destination.classify_destination(url)
    is_business: bool               # destination is a GBP/business surface
    kg_mid: Optional[str]           # decoded from a SearchViewer svid when a business
    provider_fields: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class ParsedAio:
    """The AI Overview parsed out of one organic SERP response.

    ``aio_triggered`` is the PREVALENCE signal: ``false`` (no ``ai_overview`` block
    on the SERP) is a VALID NEGATIVE — the denominator — never missingness
    (CLAUDE.md: missing != zero; ADR-0008 Sec.2). ``observation_state`` mirrors the
    provider-level status the co-returned organic parse sees, so both tracks agree.
    """
    observation_state: str          # 'returned' | 'provider_failure' | 'parser_failure'
    aio_triggered: bool             # an ai_overview block present on the SERP (stub or loaded)
    aio_presentation_form: str      # 'standalone' | 'async_stub' | 'absent'
    async_ai_overview_loaded: bool  # a loaded AIO body returned
    response_text_raw: Optional[str]
    response_markdown_raw: Optional[str]
    serp_rank_absolute: Optional[int]      # AIO block position among ALL SERP items (1 = top)
    serp_rank_group: Optional[int]
    serp_position: Optional[str]           # 'left' | 'right'
    serp_rectangle: Optional[dict[str, Any]]
    serp_preceding_block_count: Optional[int]     # 0 = top of page
    serp_preceding_block_types: Optional[list[str]]
    presentation_units: list[AioPresentationUnit]
    references: list[AioReference]
    response_metadata: dict[str, Any]
    provider_cost_usd: Optional[float]
    provider_task_id: Optional[str]
