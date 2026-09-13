from collector.idempotency import job_key, sha256_hex
from collector.models import MapsItem
from collector.raw_store import InMemoryRawStore, content_path
from collector.resolve import resolve_maps_item


def _item(**kw):
    base = dict(result_sequence=1, rank_absolute=1, rank_group=1, provider_item_type="maps_search",
                title_raw="X", category_raw=None, rating=None, review_count=None, address_raw=None,
                phone_raw=None, latitude=None, longitude=None, url_raw=None, domain_raw=None,
                place_id=None, cid=None, provider_fields={})
    base.update(kw)
    return MapsItem(**base)


def test_resolve_place_id_first():
    d = resolve_maps_item(_item(place_id="ChIJabc", domain_raw="x.example"))
    assert d.resolution_state == "resolved"
    assert (d.namespace, d.identifier_type, d.identifier_value) == ("google", "place_id", "ChIJabc")
    assert d.confidence == 1.0


def test_resolve_falls_back_to_cid_then_domain():
    assert resolve_maps_item(_item(cid="123")).identifier_type == "cid"
    assert resolve_maps_item(_item(domain_raw="X.Example")).identifier_value == "x.example"


def test_resolve_insufficient_when_no_identifiers():
    d = resolve_maps_item(_item())
    assert d.resolution_state == "insufficient_information"
    assert d.identifier_value is None


def test_job_key_deterministic_and_sensitive():
    kw = dict(methodology_version_id="m", wave_id="w", surface_id="s", industry_id="i",
              market_id="mk", surface_treatment_id="st", coordinate_id="c", replicate_no=1)
    assert job_key(**kw) == job_key(**kw)
    assert job_key(**{**kw, "replicate_no": 2}) != job_key(**kw)


def test_raw_store_content_addressed_fail_on_exists():
    store = InMemoryRawStore()
    b = b'{"hello":"world"}'
    first = store.put(surface_code="maps", payload_kind="task_get_response", raw_bytes=b)
    assert first.already_existed is False
    assert first.sha256 == sha256_hex(b)
    assert first.path == content_path("maps", "task_get_response", first.sha256)
    assert first.content_encoding == "gzip"
    second = store.put(surface_code="maps", payload_kind="task_get_response", raw_bytes=b)
    assert second.already_existed is True   # same content -> immutable no-op
    assert second.sha256 == first.sha256
