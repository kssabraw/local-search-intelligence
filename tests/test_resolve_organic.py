from collector.models import OrganicItem
from collector.normalize import normalize_domain, normalize_url
from collector.resolve import resolve_organic_item


def _item(**kw):
    base = dict(result_sequence=1, rank_absolute=1, rank_group=1, result_type="organic",
                title_raw="X", snippet_raw=None, url_raw=None, domain_raw=None,
                page_number=None, position_on_page=None, is_destination=True, provider_fields={})
    base.update(kw)
    return OrganicItem(**base)


def test_normalize_domain_strips_www_scheme_port():
    assert normalize_domain("https://WWW.Example.com:443/path") == "example.com"
    assert normalize_domain("Example-Locks.com") == "example-locks.com"
    assert normalize_domain(None) is None


def test_normalize_url_lowercases_host_drops_fragment_trims_slash():
    assert normalize_url("https://WWW.Example.com/Vancouver/#top") == "https://example.com/Vancouver"
    assert normalize_url("example.com") == "https://example.com/"      # bare host -> root kept
    assert normalize_url("https://example.com/a/?q=1") == "https://example.com/a?q=1"


def test_resolve_url_first():
    d = resolve_organic_item(_item(url_raw="https://www.example-locks.com/vancouver/",
                                   domain_raw="www.example-locks.com"))
    assert d.resolution_state == "resolved"
    assert (d.namespace, d.identifier_type) == ("web", "url")
    assert d.identifier_value == "https://example-locks.com/vancouver"
    assert d.link_domain_value == "example-locks.com"
    assert d.entity_type_code == "url"
    assert d.confidence == 1.0


def test_resolve_falls_back_to_domain_when_no_url():
    d = resolve_organic_item(_item(url_raw=None, domain_raw="Yellowpages.Example"))
    assert d.resolution_state == "probable_match"
    assert (d.identifier_type, d.identifier_value, d.entity_type_code) == (
        "domain", "yellowpages.example", "domain")


def test_resolve_never_mints_business_location():
    # organic surfacing creates a web object, never a canonical-business truth (contract 14)
    for d in (resolve_organic_item(_item(url_raw="https://x.example/a", domain_raw="x.example")),
              resolve_organic_item(_item(url_raw=None, domain_raw="x.example"))):
        assert d.entity_type_code in ("url", "domain")


def test_resolve_insufficient_when_no_destination():
    d = resolve_organic_item(_item(url_raw=None, domain_raw=None))
    assert d.resolution_state == "insufficient_information"
    assert d.identifier_value is None
    assert d.entity_type_code is None
