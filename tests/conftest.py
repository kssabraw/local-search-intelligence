import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def maps_advanced_response() -> dict:
    return json.loads((FIXTURES / "maps_advanced_sample.json").read_text())


@pytest.fixture
def maps_advanced_bytes() -> bytes:
    return (FIXTURES / "maps_advanced_sample.json").read_bytes()


@pytest.fixture
def organic_advanced_response() -> dict:
    return json.loads((FIXTURES / "organic_advanced_sample.json").read_text())


@pytest.fixture
def organic_advanced_bytes() -> bytes:
    return (FIXTURES / "organic_advanced_sample.json").read_bytes()
