from collector.parse_organic import parse_organic


def test_parse_returns_all_blocks_but_counts_only_organic(organic_advanced_response):
    parsed = parse_organic(organic_advanced_response)
    assert parsed.observation_state == "returned"
    # every SERP block is preserved as an item; only organic-type items are counted
    assert len(parsed.items) == 5
    assert parsed.returned_result_count == 2                 # two type=='organic' items
    assert parsed.provider_depth == 5                        # items_count (all blocks)
    assert parsed.provider_cost_usd == 0.0025
    assert parsed.provider_task_id == "09131234-5678-0117-0000-abcdef654321"
    assert parsed.serp_metadata["organic_result_count"] == 2
    assert parsed.serp_metadata["total_block_count"] == 5


def test_only_organic_items_are_destinations(organic_advanced_response):
    parsed = parse_organic(organic_advanced_response)
    destinations = [i for i in parsed.items if i.is_destination]
    assert len(destinations) == 2
    # the local_pack block carries a domain but is NOT an organic web destination
    local_pack = next(i for i in parsed.items if i.result_type == "local_pack")
    assert local_pack.is_destination is False
    assert local_pack.domain_raw == "acme-locksmith.example"
    # people_also_ask / related_searches have no destination
    assert all(not i.is_destination for i in parsed.items if i.result_type in
               ("people_also_ask", "related_searches"))


def test_organic_item_fields(organic_advanced_response):
    parsed = parse_organic(organic_advanced_response)
    first = next(i for i in parsed.items if i.is_destination)
    assert first.result_sequence == 2                        # sequence spans ALL blocks
    assert first.rank_absolute == 2
    assert first.result_type == "organic"
    assert first.domain_raw == "www.example-locks.com"
    assert first.url_raw == "https://www.example-locks.com/vancouver/"
    assert first.snippet_raw.startswith("24/7 emergency")     # from `description`


def test_provider_error_maps_to_provider_failure():
    resp = {"tasks": [{"id": "x", "status_code": 40501, "status_message": "boom"}]}
    parsed = parse_organic(resp)
    assert parsed.observation_state == "provider_failure"
    assert parsed.items == []


def test_empty_result_is_valid_observation():
    resp = {"cost": 0.001, "tasks": [{"id": "x", "status_code": 20000, "result_count": 0, "result": []}]}
    parsed = parse_organic(resp)
    assert parsed.observation_state == "returned"            # valid empty observation, never an error
    assert parsed.returned_result_count == 0
    assert parsed.items == []


def test_40102_no_search_results_is_valid_empty_not_failure():
    resp = {"cost": 0.0, "tasks": [{"id": "x", "status_code": 40102,
                                     "status_message": "No Search Results."}]}
    parsed = parse_organic(resp)
    assert parsed.observation_state == "returned"            # valid empty, NOT provider_failure
    assert parsed.returned_result_count == 0
    assert parsed.items == []
    assert parsed.serp_metadata["status_code"] == 40102


def test_no_tasks_is_parser_failure():
    assert parse_organic({}).observation_state == "parser_failure"
