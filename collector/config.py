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
    val = os.environ.get(name)
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
        # Normalize both values: a trailing newline/space pasted into a Railway/Supabase
        # secret is a common foot-gun. For the URL it yields an unresolvable host
        # ("Name or service not known"); for the key it corrupts the Bearer token so
        # JWT signature verification fails and Storage silently downgrades to `anon`
        # (403 AccessDenied). Strip surrounding whitespace and any trailing slash so
        # neither can happen. (A well-formed but wrong-project key still fails — that
        # is an owner action, not something normalization can fix.)
        return cls(
            supabase_url=_require("SUPABASE_URL").strip().rstrip("/"),
            service_role_key=_require("SUPABASE_SERVICE_ROLE_KEY").strip(),
            bucket=os.environ.get("LSI_RAW_BUCKET", "raw-observations").strip(),
        )

    def __repr__(self) -> str:
        return f"StorageConfig(supabase_url={self.supabase_url!r}, service_role_key='***', bucket={self.bucket!r})"


@dataclasses.dataclass(frozen=True)
class Settings:
    methodology_code: str = os.environ.get("LSI_METHODOLOGY_CODE", "MANIFEST_V1_0")
    db_url_env: str = "SUPABASE_DB_URL"

    def db_url(self) -> str:
        return _require(self.db_url_env)
