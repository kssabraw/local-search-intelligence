"""Unit tests for the pure AIO (organic AI Overview) parser (ADR-0008).

No DB, no provider — a pure function over synthetic organic SERP responses.
"""
from collector.parse_aio import parse_aio
from collector.resolve import resolve_aio_business


def test_loaded_standalone_aio(aio_loaded_response):
    p = parse_aio(aio_loaded_response)
    assert p.observation_state == "returned"
    assert p.aio_triggered is True
    assert p.aio_presentation_form == "standalone"
    assert p.async_ai_overview_loaded is True
    assert p.response_markdown_raw.startswith("Here are some well-reviewed")


def test_loaded_serp_placement_top(aio_loaded_response):
    p = parse_aio(aio_loaded_response)
    # AIO block is the first SERP item -> top of page
    assert p.serp_rank_absolute == 1
    assert p.serp_position == "left"
    assert p.serp_preceding_block_count == 0
    assert p.serp_preceding_block_types == []
    assert p.serp_rectangle == {"x": 0, "y": 180, "width": 652, "height": 420}


def test_loaded_presentation_units_and_links(aio_loaded_response):
    p = parse_aio(aio_loaded_response)
    assert len(p.presentation_units) == 2
    u1 = p.presentation_units[0]
    assert u1.unit_type == "ai_overview_element"
    assert u1.heading_raw == "Choosing a locksmith"
    assert u1.rectangle == {"x": 0, "y": 210, "width": 652, "height": 160}
    assert len(u1.links) == 1
    assert u1.links[0].url_raw == "https://www.consumer-guides.example.com/locksmith-tips"
    assert p.presentation_units[1].links == []


def test_loaded_references_website_vs_business(aio_loaded_response):
    p = parse_aio(aio_loaded_response)
    assert len(p.references) == 2
    website = next(r for r in p.references if not r.is_business)
    business = next(r for r in p.references if r.is_business)
    # website source card carries the rich sidebar fields (Sec.18 reference)
    assert website.domain_raw == "consumer-guides.example.com"
    assert website.is_reference is True
    assert website.snippet_raw and website.image_url_raw and website.datetime_raw
    assert website.destination_type == "other_web"
    assert website.kg_mid is None
    # business appears as a SearchViewer deep link -> KG-MID decoded (Sec.69)
    assert business.destination_type == "google_searchviewer"
    assert business.kg_mid == "/g/1q62g1d9q"


def test_business_resolves_by_kg_mid(aio_loaded_response):
    p = parse_aio(aio_loaded_response)
    business = next(r for r in p.references if r.is_business)
    decision = resolve_aio_business(business)
    assert decision.resolution_state == "resolved"
    assert decision.identifier_type == "google_kg_mid"
    assert decision.identifier_value == "/g/1q62g1d9q"
    assert decision.entity_type_code == "business_location"


def test_async_stub_is_triggered_but_not_loaded(aio_stub_response):
    p = parse_aio(aio_stub_response)
    assert p.aio_triggered is True                 # an AIO block is present on the SERP
    assert p.aio_presentation_form == "async_stub"
    assert p.async_ai_overview_loaded is False
    assert p.presentation_units == []
    assert p.references == []
    # preceded by the local_pack -> middle of page, not top
    assert p.serp_preceding_block_count == 1
    assert p.serp_preceding_block_types == ["local_pack"]


def test_absent_aio_is_valid_negative(aio_absent_response):
    p = parse_aio(aio_absent_response)
    assert p.observation_state == "returned"        # a real observation, missing != zero
    assert p.aio_triggered is False                 # the prevalence negative (denominator)
    assert p.aio_presentation_form == "absent"
    assert p.async_ai_overview_loaded is False
    assert p.serp_rank_absolute is None
    assert p.presentation_units == []
    assert p.references == []


def test_provider_error_maps_to_provider_failure():
    resp = {"tasks": [{"id": "x", "status_code": 40501, "status_message": "boom"}]}
    p = parse_aio(resp)
    assert p.observation_state == "provider_failure"
    assert p.aio_triggered is False
    assert p.aio_presentation_form == "absent"


def test_40102_no_results_is_valid_empty_negative():
    resp = {"cost": 0.0, "tasks": [{"id": "x", "status_code": 40102,
                                     "status_message": "No Search Results."}]}
    p = parse_aio(resp)
    assert p.observation_state == "returned"
    assert p.aio_triggered is False                 # valid empty SERP, no AIO
    assert p.aio_presentation_form == "absent"


def test_no_tasks_is_parser_failure():
    p = parse_aio({})
    assert p.observation_state == "parser_failure"
    assert p.aio_triggered is False


def _aio_resp(aio_block, extra_items=None):
    items = [aio_block] + (extra_items or [])
    return {"tasks": [{"id": "t", "status_code": 20000, "cost": 0.0012,
                       "result": [{"keyword": "k", "items": items}]}]}


def test_non_string_position_coerced_to_none():
    # a malformed provider 'position' (not a str) must not reach the text column
    p = parse_aio(_aio_resp({"type": "ai_overview", "rank_absolute": 1,
                             "position": 3, "markdown": "hi"}))
    assert p.aio_triggered is True
    assert p.serp_position is None


def test_non_dict_element_items_skipped_contiguously():
    # junk (non-dict) entries in items[] are skipped; unit_sequence stays contiguous
    block = {"type": "ai_overview", "rank_absolute": 1, "markdown": "hi",
             "items": [{"type": "ai_overview_element", "title": "A"},
                       "junk",
                       {"type": "ai_overview_element", "title": "B"}]}
    p = parse_aio(_aio_resp(block))
    assert [u.unit_sequence for u in p.presentation_units] == [1, 2]
    assert [u.heading_raw for u in p.presentation_units] == ["A", "B"]


def test_maps_destination_reference_is_business_without_svid():
    # a Google Maps destination (no svid) is a business appearance but has no KG-MID
    block = {"type": "ai_overview", "rank_absolute": 1, "markdown": "hi",
             "references": [{"type": "ai_overview_reference", "source": "Shop",
                             "url": "https://www.google.com/maps/place/Shop", "is_reference": True}]}
    p = parse_aio(_aio_resp(block))
    ref = p.references[0]
    assert ref.is_business is True
    assert ref.destination_type == "google_maps"
    assert ref.kg_mid is None
    # resolve_aio_business preserves this as insufficient_information (never merged)
    assert resolve_aio_business(ref).resolution_state == "insufficient_information"
