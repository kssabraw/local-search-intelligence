"""Unit tests for the AIO capture-feasibility structural inspector (ADR-0005).

DB-free and network-free: pure inspection of synthetic fixtures. These assert the
inspector's VERDICT LOGIC (present / absent / uncertain), not real provider
fidelity -- that is exactly what the live probe confirms.
"""
import json
import pathlib

from collector.inspect_aio import CAPABILITY_KEYS, inspect_aio_capture

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _verdict(cap: dict, key: str) -> str:
    return cap["capabilities"][key]["verdict"]


def test_rich_response_all_capabilities_present():
    cap = inspect_aio_capture(_load("aio_ai_mode_rich.json"))
    assert cap["aio_present"] is True
    assert cap["returned"] is True
    assert cap["provider_cost_usd"] == 0.002
    for key in CAPABILITY_KEYS:
        assert _verdict(cap, key) == "present", (key, cap["capabilities"][key])
    # rectangles actually detected with evidence + count
    assert cap["capabilities"]["element_rectangles"]["count"] >= 1
    # citations counted from the references array
    assert cap["capabilities"]["source_citations"]["count"] == 2
    # a Google Maps destination URL surfaced for searchviewer/GBP detection
    assert cap["capabilities"]["destination_searchviewer"]["count"] >= 1


def test_text_only_response_marks_rich_fields_absent():
    cap = inspect_aio_capture(_load("aio_ai_mode_textonly.json"))
    assert cap["aio_present"] is True
    # the answer + element structure are present ...
    assert _verdict(cap, "aio_answer_text") == "present"
    assert _verdict(cap, "element_level_structure") == "present"
    # ... but the placement/citation/local-surface fields are ABSENT (not uncertain):
    # a valid AIO came back and simply did not carry them => provider_not_observable.
    for key in ("element_rectangles", "source_citations", "reference_vs_link",
                "local_business_cards", "embedded_gbp", "destination_searchviewer"):
        assert _verdict(cap, key) == "absent", (key, cap["capabilities"][key])


def test_not_triggered_response_is_all_uncertain():
    cap = inspect_aio_capture(_load("aio_not_triggered.json"))
    assert cap["aio_present"] is False
    assert cap["returned"] is True  # 20000 is still a returned response
    for key in CAPABILITY_KEYS:
        assert _verdict(cap, key) == "uncertain", (key, cap["capabilities"][key])


def test_provider_failure_status_is_not_returned():
    cap = inspect_aio_capture({"tasks": [{"status_code": 40501, "status_message": "err", "result": []}]})
    assert cap["returned"] is False
    assert cap["aio_present"] is False


def test_empty_or_malformed_response_does_not_raise():
    for bad in ({}, {"tasks": []}, {"tasks": [{}]}, {"tasks": [{"result": [None]}]}):
        cap = inspect_aio_capture(bad)
        assert cap["aio_present"] is False
        assert set(cap["capabilities"]) == set(CAPABILITY_KEYS)


def test_unscoped_organic_conflates_local_pack_as_local_card():
    # DEFAULT scope walks the whole SERP, so the ever-present local_pack looks like a
    # "local card" -- the conflation the scoped inspector fixes (see next test).
    cap = inspect_aio_capture(_load("aio_overview_in_organic.json"))  # scope="response"
    assert cap["aio_present"] is True
    assert _verdict(cap, "local_business_cards") == "present"  # conflated (local_pack)


def test_scoped_organic_excludes_local_pack_from_aio_card():
    # scope='ai_overview' restricts detection to the ai_overview element subtree, so the
    # SERP local_pack is NOT counted as an AIO local card, while the ai_overview's own
    # rectangles / citations / answer ARE captured.
    cap = inspect_aio_capture(_load("aio_overview_in_organic.json"), scope="ai_overview")
    assert cap["scope"] == "ai_overview"
    assert cap["aio_present"] is True
    assert _verdict(cap, "local_business_cards") == "absent"       # local_pack excluded -> the fix
    assert _verdict(cap, "embedded_gbp") == "absent"
    assert _verdict(cap, "element_rectangles") == "present"        # inside the ai_overview element
    assert _verdict(cap, "source_citations") == "present"
    assert _verdict(cap, "aio_answer_text") == "present"


def test_scoped_organic_async_stub_uses_paa_content_not_local_pack():
    # Realistic production shape: local_pack + an async ai_overview STUB + AIO content
    # only inside people_also_ask. Scoped -> AIO present from the PAA-AIO content, the
    # async stub is flagged, and the local_pack is NOT an AIO card.
    cap = inspect_aio_capture(_load("aio_overview_organic_async_stub.json"), scope="ai_overview")
    assert cap["aio_present"] is True
    assert cap["async_stub_present"] is True
    assert _verdict(cap, "aio_answer_text") == "present"           # PAA-embedded AIO markdown
    assert _verdict(cap, "source_citations") == "present"          # PAA-embedded AIO references
    assert _verdict(cap, "local_business_cards") == "absent"       # local_pack excluded


def test_organic_without_ai_overview_is_not_aio_present():
    # A local_pack alone (no ai_overview element) is NOT an AIO trigger: aio_present
    # must be false even though the SERP returned items.
    cap = inspect_aio_capture(_load("organic_no_aio.json"))
    assert cap["aio_present"] is False
    for key in CAPABILITY_KEYS:
        assert _verdict(cap, key) == "uncertain"


def test_fingerprint_dumps_observed_structure_for_verification():
    cap = inspect_aio_capture(_load("aio_ai_mode_rich.json"))
    fp = cap["structure_fingerprint"]
    assert "ai_overview" in fp["item_types"]
    assert "local_pack" in fp["item_types"]
    assert any("maps" in u for u in fp["url_sample"])
