"""Pure, deterministic web-identifier normalization for Organic resolution.

No I/O. Used to key canonical `core.web_domain` / `core.web_url` entities off an
organic result's raw domain/URL. Deterministic so the same observed destination
always resolves to the same canonical identifier (ADR-0003). Registered-domain /
public-suffix logic is intentionally out of scope for the Stage-1 slice; the
normalized host doubles as the registered domain for now.
"""
from __future__ import annotations
from typing import Optional
from urllib.parse import urlsplit, urlunsplit


def _host(raw: str) -> str:
    """Extract a bare host from a domain-or-URL string."""
    s = raw.strip()
    parts = urlsplit(s if "://" in s else "//" + s)
    host = parts.netloc or parts.path.split("/", 1)[0]
    if "@" in host:
        host = host.rsplit("@", 1)[-1]
    host = host.split(":", 1)[0]  # strip port
    return host.strip().lower().strip(".")


def normalize_domain(raw: Optional[str]) -> Optional[str]:
    """Lower-case bare host with any leading 'www.' stripped."""
    if not raw:
        return None
    host = _host(raw)
    if host.startswith("www."):
        host = host[4:]
    return host or None


def normalize_url(raw: Optional[str]) -> Optional[str]:
    """Canonical URL: lower-case scheme+host (no leading 'www.'), fragment
    dropped, query preserved, trailing slash trimmed off non-root paths."""
    if not raw:
        return None
    s = raw.strip()
    parts = urlsplit(s if "://" in s else "https://" + s)
    scheme = (parts.scheme or "https").lower()
    host = parts.netloc.split("@")[-1].lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((scheme, host, path, parts.query, ""))
