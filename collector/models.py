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
