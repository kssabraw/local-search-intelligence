"""AIO destination classification + SearchViewer entity resolution.

Grounded in what the Stage-2 capture probe proved DataForSEO's **AI Mode** surface
actually returns (wave AIOPROBE-AIOPROBE_V0-20260916): there is NO local-pack /
local-business-card module. Businesses/GBPs appear as ``ai_overview_reference``
items whose destination is a Google **SearchViewer** deep link, e.g.

    https://www.google.com/searchviewer/10?svid=CAwSHBIaCgNwdnESE0Nnd3ZaeTh4Y1RZeVp6RmtPWEUYCg

The ``svid`` is a nested base64/protobuf that packs a Google **Knowledge Graph
entity MID** (``/g/1q62g1d9q``). So the AIO normalizer detects a GBP surface by
CLASSIFYING the reference destination URL, and resolves its identity by decoding
the MID out of the ``svid`` — no local-card module required.

Both functions here are pure, deterministic, offline (no LLM, no network) — the
Python-before-LLM building blocks the future ``aio.*`` normalizer will use to fill
``destination_type`` (AIO PRD Sec.69 enum) and a ``google_kg_mid`` external
identifier. Wiring them into ``aio.*`` writes awaits the schema-decision sign-off;
this module ships the verified mechanics on their own.
"""
from __future__ import annotations

import base64
import re
from typing import Optional
from urllib.parse import parse_qs, urlsplit

# AIO PRD Sec.69 destination_type values this URL-only classifier can assert
# deterministically. NOTE: it never emits "website" — distinguishing the business's
# OWN site from any other external site ("other_web") requires matching the host
# against the resolved business entity, which is the normalizer/enrichment's job,
# not something a URL alone proves. So external hosts return "other_web".
DEST_SEARCHVIEWER = "google_searchviewer"
DEST_MAPS = "google_maps"
DEST_OTHER_GOOGLE = "other_google"
DEST_OTHER_WEB = "other_web"
DEST_CALL = "call"
DEST_DIRECTIONS = "directions"
DEST_NONE = "none"
DEST_UNKNOWN = "unknown"

_MID_RE = re.compile(r"/[gm]/[0-9a-z_]{4,}")           # KG MID (/g/...) or legacy /m/...
_B64_RUN_RE = re.compile(rb"[A-Za-z0-9_\-]{8,}")        # base64url-ish run inside decoded svid


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def classify_destination(url: Optional[str]) -> str:
    """Classify one reference/link/action destination URL into the AIO PRD Sec.69
    ``destination_type`` enum, deterministically, from the URL alone.

    Returns ``none`` for an empty URL and ``unknown`` for something unparseable.
    Google SearchViewer (the AI-Mode GBP surface) and Maps are recognised
    explicitly; any other Google host is ``other_google``; any other external host
    is ``other_web`` (never ``website`` — see module note).
    """
    if not url or not str(url).strip():
        return DEST_NONE
    raw = str(url).strip()
    low = raw.lower()
    if low.startswith("tel:"):
        return DEST_CALL
    try:
        parts = urlsplit(raw)
    except ValueError:
        return DEST_UNKNOWN
    host = (parts.netloc or "").lower()
    path = (parts.path or "").lower()
    if not host and not parts.scheme:
        # A bare "/searchviewer/..."-style path with no host is still classifiable.
        host = ""
    is_google = host == "google.com" or host.endswith(".google.com") or ".google." in f"{host}."
    if is_google or (not host and path.startswith("/searchviewer")):
        if "/searchviewer" in path:
            return DEST_SEARCHVIEWER
        if path.startswith("/maps/dir") or "daddr=" in low or "/dir/" in path:
            return DEST_DIRECTIONS
        if host.startswith("maps.") or "/maps" in path or "/local" in path:
            return DEST_MAPS
        return DEST_OTHER_GOOGLE
    if host:
        return DEST_OTHER_WEB
    return DEST_UNKNOWN


def decode_searchviewer_svid(value: Optional[str]) -> Optional[str]:
    """Extract the Google Knowledge Graph MID (e.g. ``/g/1q62g1d9q``) packed inside a
    SearchViewer ``svid``. Accepts a full SearchViewer URL or a bare ``svid`` token;
    returns the MID string, or ``None`` if none is present/decodable.

    The svid is base64url(protobuf) whose inner field is itself base64url of the MID.
    We decode defensively: pull ``svid`` from the URL query if given a URL, base64url-
    decode, then scan the bytes (and any inner base64 runs) for a ``/g/`` or ``/m/``
    MID. Never raises on malformed input.
    """
    if not value or not str(value).strip():
        return None
    token = str(value).strip()
    if "svid=" in token or token.startswith(("http://", "https://", "/")):
        try:
            qs = parse_qs(urlsplit(token).query)
            token = (qs.get("svid") or [""])[0]
        except ValueError:
            return None
    if not token:
        return None
    try:
        outer = _b64url_decode(token)
    except Exception:
        return None
    # Direct hit: the MID text sometimes survives in the outer decode.
    m = _MID_RE.search(outer.decode("latin-1").lower())
    if m:
        return m.group(0)
    # Otherwise the MID is inside a nested base64url run.
    for run in _B64_RUN_RE.findall(outer):
        try:
            inner = _b64url_decode(run.decode())
        except Exception:
            continue
        m = _MID_RE.search(inner.decode("latin-1").lower())
        if m:
            return m.group(0)
    return None
