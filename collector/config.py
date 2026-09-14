"""Runtime configuration for the collector — sourced only from the environment.

Secrets (DataForSEO credentials, Supabase keys) are injected by Railway/Supabase
secret management. They are NEVER read from the repo, and this module never logs
their values.
"""
from __future__ import annotations
import dataclasses
import os


class ConfigError(RuntimeError):
    """A required environment variable is missing."""


def _require(name: str) -> str:
    # Strip BEFORE the emptiness check: a value that is only whitespace (e.g. a
    # secret pasted as a bare newline) is treated as missing and raises a clear
    # error, rather than passing through as a blank string that later corrupts a
    # URL/host or Bearer token. Surrounding whitespace on a real value (a trailing
    # newline is a common paste foot-gun) is removed here for every required var.
    val = os.environ.get(name)
    if val is not None:
        val = val.strip()
    if not val:
        raise ConfigError(
            f"missing required env var {name}; set it in Railway/Supabase secret "
            f"management (never in the repo or in chat)"
        )
    return val


@dataclasses.dataclass(frozen=True)
class ProviderCreds:
    login: str
    password: str

    @classmethod
    def from_env(cls) -> "ProviderCreds":
        return cls(login=_require("DATAFORSEO_LOGIN"), password=_require("DATAFORSEO_PASSWORD"))

    def __repr__(self) -> str:  # never leak secrets in logs/tracebacks
        return "ProviderCreds(login='***', password='***')"


@dataclasses.dataclass(frozen=True)
class StorageConfig:
    supabase_url: str
    service_role_key: str
    bucket: str = "raw-observations"

    @classmethod
    def from_env(cls) -> "StorageConfig":
        # `_require` already strips surrounding whitespace and rejects blank values
        # (a trailing newline pasted into a secret is a common foot-gun: on the URL
        # it yields an unresolvable host, on the key it corrupts the Bearer token so
        # signature verification fails and Storage downgrades to `anon`). Here we
        # additionally strip any trailing slash from the URL so "<url>/" cannot make
        # a "//storage" path, and fall back to the default bucket when LSI_RAW_BUCKET
        # is present-but-empty (os.environ.get's default only applies when unset).
        # (A well-formed but wrong-project key still fails — an owner action, not
        # something normalization can fix.)
        bucket = (os.environ.get("LSI_RAW_BUCKET") or "").strip() or "raw-observations"
        return cls(
            supabase_url=_require("SUPABASE_URL").rstrip("/"),
            service_role_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
            bucket=bucket,
        )

    def __repr__(self) -> str:
        return f"StorageConfig(supabase_url={self.supabase_url!r}, service_role_key='***', bucket={self.bucket!r})"


@dataclasses.dataclass(frozen=True)
class Settings:
    methodology_code: str = os.environ.get("LSI_METHODOLOGY_CODE", "MANIFEST_V1_0")
    db_url_env: str = "SUPABASE_DB_URL"

    def db_url(self) -> str:
        return _require(self.db_url_env)
