"""Tests for AIO destination classification + SearchViewer MID resolution.

The svid tokens below are REAL values captured on the 2026-09-16 production AIO
probe (wave AIOPROBE-AIOPROBE_V0-20260916); their decoded MIDs were verified out
of band. DB-free, network-free, no LLM.
"""
from collector.aio_destination import (DEST_CALL, DEST_DIRECTIONS, DEST_MAPS,
                                       DEST_NONE, DEST_OTHER_GOOGLE, DEST_OTHER_WEB,
                                       DEST_SEARCHVIEWER, DEST_UNKNOWN,
                                       classify_destination, decode_searchviewer_svid)

# Real captured SearchViewer URLs -> their (verified) KG MID.
SV_URL_1 = "https://www.google.com/searchviewer/10?svid=CAwSHBIaCgNwdnESE0Nnd3ZaeTh4Y1RZeVp6RmtPWEUYCg"
SV_URL_2 = "https://www.google.com/searchviewer/10?svid=CAwSHRIbCgNwdnESFENnMHZaeTh4TVdjd2FESXlhRjlyGAo"


def test_classify_searchviewer():
    assert classify_destination(SV_URL_1) == DEST_SEARCHVIEWER
    assert classify_destination("https://www.google.com/searchviewer/10?svid=abc") == DEST_SEARCHVIEWER


def test_classify_maps_and_other_google():
    assert classify_destination("https://www.google.com/maps") == DEST_MAPS
    assert classify_destination("https://www.google.com/maps/place/Foo/@45,-122,17z") == DEST_MAPS
    assert classify_destination("https://maps.google.com/?cid=123") == DEST_MAPS
    assert classify_destination("https://www.google.com/search?q=foo") == DEST_OTHER_GOOGLE


def test_classify_directions_and_call():
    assert classify_destination("https://www.google.com/maps/dir/?daddr=x") == DEST_DIRECTIONS
    assert classify_destination("tel:+13605550100") == DEST_CALL


def test_classify_external_web_is_other_web_not_website():
    # A URL alone never proves it is the business's OWN site, so it is other_web,
    # never "website" (that requires matching the resolved business domain).
    assert classify_destination("https://www.example-locksmith.com/about") == DEST_OTHER_WEB


def test_classify_none_and_unknown():
    assert classify_destination(None) == DEST_NONE
    assert classify_destination("") == DEST_NONE
    assert classify_destination("   ") == DEST_NONE


def test_decode_svid_from_url():
    assert decode_searchviewer_svid(SV_URL_1) == "/g/1q62g1d9q"
    assert decode_searchviewer_svid(SV_URL_2) == "/g/11g0h22h_k"


def test_decode_svid_from_bare_token():
    tok = "CAwSHBIaCgNwdnESE0Nnd3ZaeTh4Y1RZeVp6RmtPWEUYCg"
    assert decode_searchviewer_svid(tok) == "/g/1q62g1d9q"


def test_decode_svid_negative_cases():
    assert decode_searchviewer_svid(None) is None
    assert decode_searchviewer_svid("") is None
    assert decode_searchviewer_svid("https://www.google.com/maps") is None  # no svid
    assert decode_searchviewer_svid("not-base64-$$$") is None
