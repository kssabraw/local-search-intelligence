"""Pure entity-resolution decision: place_id-first (ADR-0003).

No I/O. Given the identifiers on one observed object, decide the resolution
state and the strong external identifier to key the canonical business on.
Ambiguous/insufficient cases are preserved as explicit states, never silently
merged (ADR-0003 / CLAUDE.md). The repository performs the actual get-or-create
against the entity graph using this decision.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .models import AioReference, MapsItem, OrganicItem
from .normalize import normalize_domain, normalize_url


@dataclass(frozen=True)
class ResolutionDecision:
    resolution_state: str            # core.resolution_state
    resolver_stage: str
    method: Optional[str]            # e.g. 'place_id', 'domain'
    confidence: Optional[float]      # 0..1 or None
    namespace: Optional[str]         # external_identifier.namespace
    identifier_type: Optional[str]
    identifier_value: Optional[str]
    entity_type_code: Optional[str]  # core.entity_type when a new entity is minted
    link_domain_value: Optional[str] = None  # normalized domain to link a url entity to its web_domain


def resolve_maps_item(item: MapsItem) -> ResolutionDecision:
    if item.place_id:
        return ResolutionDecision(
            resolution_state="resolved", resolver_stage="place_id",
            method="place_id", confidence=1.0,
            namespace="google", identifier_type="place_id", identifier_value=item.place_id,
            entity_type_code="business_location",
        )
    if item.cid:
        return ResolutionDecision(
            resolution_state="probable_match", resolver_stage="cid",
            method="cid", confidence=0.8,
            namespace="google", identifier_type="cid", identifier_value=item.cid,
            entity_type_code="business_location",
        )
    if item.domain_raw:
        return ResolutionDecision(
            resolution_state="probable_match", resolver_stage="domain",
            method="domain", confidence=0.5,
            namespace="web", identifier_type="domain", identifier_value=item.domain_raw.lower(),
            entity_type_code="business_location",
        )
    return ResolutionDecision(
        resolution_state="insufficient_information", resolver_stage="none",
        method=None, confidence=None,
        namespace=None, identifier_type=None, identifier_value=None,
        entity_type_code=None,
    )


def resolve_aio_business(ref: AioReference) -> ResolutionDecision:
    """Resolve one AIO business appearance (a GBP/SearchViewer reference) to a
    canonical business_location, keyed on its Google Knowledge-Graph MID decoded from
    the SearchViewer ``svid`` (ADR-0008; joinable to the Maps place_id graph later).

    KG-MID is a strong Google identifier -> ``resolved``. Absent/undecodable MID (a
    Maps destination without an svid, a malformed token) is preserved as
    ``insufficient_information``, never silently merged onto a website (ADR-0003).
    """
    if ref.kg_mid:
        return ResolutionDecision(
            resolution_state="resolved", resolver_stage="google_kg_mid",
            method="google_kg_mid", confidence=1.0,
            namespace="google", identifier_type="google_kg_mid", identifier_value=ref.kg_mid,
            entity_type_code="business_location",
        )
    return ResolutionDecision(
        resolution_state="insufficient_information", resolver_stage="none",
        method=None, confidence=None,
        namespace=None, identifier_type=None, identifier_value=None,
        entity_type_code=None,
    )


def resolve_organic_item(item: OrganicItem) -> ResolutionDecision:
    """Web destinations only (contract section 14): organic surfacing creates a
    normalized web object, never a canonical-business truth. URL-first (a URL
    exactly identifies a page), then domain; both key a `web` external
    identifier. Ambiguous/insufficient cases are preserved, never merged.
    """
    normalized_url = normalize_url(item.url_raw)
    normalized_domain = normalize_domain(item.domain_raw) or normalize_domain(normalized_url)
    if normalized_url and normalized_domain:
        return ResolutionDecision(
            resolution_state="resolved", resolver_stage="url",
            method="url", confidence=1.0,
            namespace="web", identifier_type="url", identifier_value=normalized_url,
            entity_type_code="url", link_domain_value=normalized_domain,
        )
    if normalized_domain:
        return ResolutionDecision(
            resolution_state="probable_match", resolver_stage="domain",
            method="domain", confidence=0.6,
            namespace="web", identifier_type="domain", identifier_value=normalized_domain,
            entity_type_code="domain", link_domain_value=normalized_domain,
        )
    return ResolutionDecision(
        resolution_state="insufficient_information", resolver_stage="none",
        method=None, confidence=None,
        namespace=None, identifier_type=None, identifier_value=None,
        entity_type_code=None,
    )
