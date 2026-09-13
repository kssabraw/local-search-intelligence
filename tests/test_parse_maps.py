from collector.parse_maps import parse_maps


def test_parse_returns_items(maps_advanced_response):
    parsed = parse_maps(maps_advanced_response)
    assert parsed.observation_state == "returned"
    assert parsed.returned_result_count == 2
    assert parsed.provider_cost_usd == 0.002
    assert parsed.provider_task_id == "09131234-5678-0216-0000-abcdef123456"
    first = parsed.items[0]
    assert first.result_sequence == 1
    assert first.rank_absolute == 1
    assert first.title_raw == "Acme Locksmith"
    assert first.rating == 4.8
    assert first.review_count == 321          # from rating.votes_count
    assert first.place_id == "ChIJAcmeLocksmithPlaceId000001"
    assert first.cid == "1112223334445556667"


def test_provider_error_maps_to_provider_failure():
    resp = {"tasks": [{"id": "x", "status_code": 40501, "status_message": "boom"}]}
    parsed = parse_maps(resp)
    assert parsed.observation_state == "provider_failure"
    assert parsed.items == []


def test_empty_result_is_valid_observation():
    resp = {"cost": 0.001, "tasks": [{"id": "x", "status_code": 20000, "result_count": 0, "result": []}]}
    parsed = parse_maps(resp)
    assert parsed.observation_state == "returned"   # valid empty observation, never an error
    assert parsed.returned_result_count == 0
    assert parsed.items == []


def test_no_tasks_is_parser_failure():
    assert parse_maps({}).observation_state == "parser_failure"


def test_40102_no_search_results_is_valid_empty_not_failure():
    resp = {"cost": 0.0, "tasks": [{"id": "x", "status_code": 40102,
                                     "status_message": "No Search Results."}]}
    parsed = parse_maps(resp)
    assert parsed.observation_state == "returned"        # valid empty, NOT provider_failure
    assert parsed.returned_result_count == 0
    assert parsed.items == []
    assert parsed.search_metadata["status_code"] == 40102


def test_build_request_zoom_override():
    from collector.models import ManifestContext
    from collector.spike import build_request
    ctx = ManifestContext(
        methodology_version_id="m", methodology_code="MANIFEST_V1_0", surface_id="s",
        surface_code="maps", industry_id="i", market_id="mk", market_city="Vancouver",
        surface_treatment_id="st", treatment_id="t", treatment_code="Q1", treatment_kind="query",
        exact_template="locksmith near me", city_slot_required=False, coordinate_id="c",
        coordinate_code="MKT008_MAPORG_C", latitude=45.625655, longitude=-122.6754998,
        eligibility="eligible_land", provider_profile_id="pp", provider_id="p",
        post_endpoint="/x", get_endpoint="/y", location_template="{lat},{lon},17z",
        language_code="en", device="desktop", operating_system="windows", result_depth=10)
    assert build_request(ctx)["location_coordinate"].endswith(",17z")
    assert build_request(ctx, zoom_override="12z")["location_coordinate"].endswith(",12z")
    assert build_request(ctx, zoom_override="12")["location_coordinate"].endswith(",12z")
