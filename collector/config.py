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
        return cls(
            supabase_url=_require("SUPABASE_URL"),
            service_role_key=_require("SUPABASE_SERVICE_ROLE_KEY"),
            bucket=os.environ.get("LSI_RAW_BUCKET", "raw-observations"),
        )

    def __repr__(self) -> str:
        return f"StorageConfig(supabase_url={self.supabase_url!r}, service_role_key='***', bucket={self.bucket!r})"


@dataclasses.dataclass(frozen=True)
class Settings:
    methodology_code: str = os.environ.get("LSI_METHODOLOGY_CODE", "MANIFEST_V1_0")
    db_url_env: str = "SUPABASE_DB_URL"

    def db_url(self) -> str:
        return _require(self.db_url_env)
