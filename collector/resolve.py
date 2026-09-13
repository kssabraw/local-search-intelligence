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

from .models import MapsItem


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
