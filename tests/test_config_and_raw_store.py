"""Config normalization + raw-store error surfacing (offline; no network)."""
from __future__ import annotations

import sys
import types

import pytest

from collector.config import ConfigError, StorageConfig
from collector.raw_store import RawStoreError, SupabaseStorageRawStore, content_path


def test_storage_config_strips_whitespace_and_trailing_slash(monkeypatch):
    # A trailing newline pasted into a secret must not corrupt the host or the key.
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co/\n")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "  the.jwt.token\n")
    monkeypatch.delenv("LSI_RAW_BUCKET", raising=False)
    cfg = StorageConfig.from_env()
    assert cfg.supabase_url == "https://ref.supabase.co"
    assert cfg.service_role_key == "the.jwt.token"
    assert cfg.bucket == "raw-observations"


def test_storage_config_rejects_whitespace_only_required_var(monkeypatch):
    # A whitespace-only secret must be treated as missing (clear ConfigError),
    # not pass through and normalize to an empty string.
    monkeypatch.setenv("SUPABASE_URL", "   \n")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "the.jwt.token")
    monkeypatch.delenv("LSI_RAW_BUCKET", raising=False)
    with pytest.raises(ConfigError):
        StorageConfig.from_env()


def test_storage_config_bucket_falls_back_when_env_present_but_empty(monkeypatch):
    # LSI_RAW_BUCKET set to "" (present-but-empty) must fall back to the default,
    # not yield an empty bucket (which would produce a "//" storage path).
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "the.jwt.token")
    monkeypatch.setenv("LSI_RAW_BUCKET", "  ")
    cfg = StorageConfig.from_env()
    assert cfg.bucket == "raw-observations"


def test_storage_config_repr_hides_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "super-secret")
    cfg = StorageConfig.from_env()
    assert "super-secret" not in repr(cfg)
    assert "***" in repr(cfg)


class _FakeResp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def _install_fake_httpx(monkeypatch, resp: _FakeResp):
    calls: dict = {}

    def _post(url, content=None, headers=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        return resp

    fake = types.ModuleType("httpx")
    fake.post = _post  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return calls


def _cfg() -> StorageConfig:
    return StorageConfig(supabase_url="https://ref.supabase.co",
                         service_role_key="k", bucket="raw-observations")


def test_put_raises_with_body_on_access_denied(monkeypatch):
    # The real incident: HTTP 400 whose body carries the true cause.
    body = '{"statusCode":"403","error":"AccessDenied","message":"signature verification failed"}'
    _install_fake_httpx(monkeypatch, _FakeResp(400, body))
    store = SupabaseStorageRawStore(_cfg())
    with pytest.raises(RawStoreError) as ei:
        store.put(surface_code="maps", payload_kind="request", raw_bytes=b"{}")
    msg = str(ei.value)
    assert "400" in msg
    assert "signature verification failed" in msg  # body is surfaced, not swallowed


def test_put_treats_exists_as_immutable_noop(monkeypatch):
    body = '{"statusCode":"409","error":"Duplicate","message":"The resource already exists"}'
    _install_fake_httpx(monkeypatch, _FakeResp(409, body))
    store = SupabaseStorageRawStore(_cfg())
    blob = store.put(surface_code="maps", payload_kind="request", raw_bytes=b"{}")
    assert blob.already_existed is True


def test_put_400_with_unrelated_exists_substring_still_raises(monkeypatch):
    # A 4xx whose body merely contains "exists" (but is not the duplicate
    # signature) must raise, not be mistaken for the fail-on-exists no-op.
    body = '{"statusCode":"400","error":"InvalidRequest","message":"bucket exists check failed"}'
    _install_fake_httpx(monkeypatch, _FakeResp(400, body))
    store = SupabaseStorageRawStore(_cfg())
    with pytest.raises(RawStoreError):
        store.put(surface_code="maps", payload_kind="request", raw_bytes=b"{}")


def test_put_3xx_is_not_treated_as_success(monkeypatch):
    # Only a 2xx stores the object; a stray redirect stored nothing and must raise.
    _install_fake_httpx(monkeypatch, _FakeResp(302, ""))
    store = SupabaseStorageRawStore(_cfg())
    with pytest.raises(RawStoreError):
        store.put(surface_code="maps", payload_kind="request", raw_bytes=b"{}")


def test_put_success_builds_content_addressed_path(monkeypatch):
    calls = _install_fake_httpx(monkeypatch, _FakeResp(200, "{}"))
    store = SupabaseStorageRawStore(_cfg())
    raw = b'{"hello":"world"}'
    blob = store.put(surface_code="maps", payload_kind="request", raw_bytes=raw)
    assert blob.already_existed is False
    assert blob.path == content_path("maps", "request", blob.sha256)
    assert calls["url"].endswith(blob.path)
    assert calls["headers"]["x-upsert"] == "false"  # fail-on-exists
