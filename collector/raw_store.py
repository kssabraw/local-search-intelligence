"""Immutable, content-addressed raw storage (ADR-0002).

Bytes are gzipped and stored at a deterministic content address; writes are
FAIL-ON-EXISTS (upsert=false). A colliding hash is a no-op, never an overwrite.
`RawStore` is the seam offline tests replace with an in-memory fake.
"""
from __future__ import annotations
import gzip
from dataclasses import dataclass
from typing import Protocol

from .config import StorageConfig
from .idempotency import sha256_hex


class RawStoreError(RuntimeError):
    """A raw-storage upload failed for a reason other than fail-on-exists."""


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    bucket: str
    path: str
    byte_size: int          # size of the stored (gzipped) object
    mime_type: str          # media type of the ORIGINAL payload
    content_encoding: str    # 'gzip'
    already_existed: bool


def content_path(surface_code: str, payload_kind: str, sha: str) -> str:
    """Deterministic content address: <surface>/<kind>/<aa>/<sha>.json.gz."""
    return f"{surface_code}/{payload_kind}/{sha[:2]}/{sha}.json.gz"


class RawStore(Protocol):
    def put(self, *, surface_code: str, payload_kind: str, raw_bytes: bytes,
            mime_type: str = "application/json") -> StoredBlob: ...


class InMemoryRawStore:
    """Offline fake: content-addressed dict with fail-on-exists semantics."""

    def __init__(self, bucket: str = "raw-observations"):
        self.bucket = bucket
        self._objects: dict[str, bytes] = {}

    def put(self, *, surface_code: str, payload_kind: str, raw_bytes: bytes,
            mime_type: str = "application/json") -> StoredBlob:
        sha = sha256_hex(raw_bytes)  # hash the ORIGINAL bytes (the content address)
        gz = gzip.compress(raw_bytes)
        path = content_path(surface_code, payload_kind, sha)
        existed = path in self._objects
        if not existed:
            self._objects[path] = gz
        return StoredBlob(sha, self.bucket, path, len(gz), mime_type, "gzip", existed)


class SupabaseStorageRawStore:
    """Real Supabase Storage client (private bucket). Requires network + service key."""

    def __init__(self, cfg: StorageConfig):
        self._cfg = cfg

    def put(self, *, surface_code: str, payload_kind: str, raw_bytes: bytes,
            mime_type: str = "application/json") -> StoredBlob:
        import httpx  # lazy import
        sha = sha256_hex(raw_bytes)
        gz = gzip.compress(raw_bytes)
        path = content_path(surface_code, payload_kind, sha)
        url = f"{self._cfg.supabase_url}/storage/v1/object/{self._cfg.bucket}/{path}"
        headers = {
            "authorization": f"Bearer {self._cfg.service_role_key}",
            "content-type": "application/gzip",
            "content-encoding": "gzip",
            "x-upsert": "false",  # FAIL-ON-EXISTS
            "cache-control": "max-age=31536000, immutable",
        }
        resp = httpx.post(url, content=gz, headers=headers, timeout=120.0)
        body_lc = resp.text.lower()
        already = False
        if resp.status_code in (400, 409) and ("already exists" in body_lc or "duplicate" in body_lc):
            # Content address already present -> immutable no-op (fail-on-exists).
            # Match Supabase's duplicate signature ("Duplicate" / "The resource
            # already exists"), not a bare "exists" substring that an unrelated
            # error body could also contain.
            already = True
        elif not 200 <= resp.status_code < 300:
            # Only a 2xx is a successful store. Anything else that is not the
            # duplicate no-op above (a 4xx/5xx, or a stray 3xx redirect that
            # stored nothing) is an error. Surface the Storage body, not just the
            # status: e.g. a "signature verification failed" (wrong/stale
            # service-role key) is reported as HTTP 400 with the real cause only
            # in the body. The body carries no secret (never echo Authorization).
            raise RawStoreError(
                f"Supabase Storage upload failed ({resp.status_code}) for "
                f"{self._cfg.bucket}/{path}: {resp.text[:500]}"
            )
        return StoredBlob(sha, self._cfg.bucket, path, len(gz), mime_type, "gzip", already)
