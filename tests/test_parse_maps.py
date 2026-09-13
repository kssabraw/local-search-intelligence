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
