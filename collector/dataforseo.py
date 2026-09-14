"""DataForSEO Maps provider behind an interface.

`MapsProvider` is the seam tests and offline validation replace with a fake, so
no test ever hits the live provider. `HttpMapsProvider` is the real client
(standard async: task_post -> poll task_get/advanced). The live call is the
first PAID DataForSEO call and is gated on owner confirmation + verified secrets.
"""
from __future__ import annotations
import time
from typing import Any, Optional, Protocol

from .config import ProviderCreds


class MapsProvider(Protocol):
    def task_post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bytes, Optional[str]]:
        """Submit one Maps task. Returns (parsed_json, raw_bytes, provider_task_id)."""

    def task_get_advanced(self, task_id: str) -> tuple[dict[str, Any], bytes]:
        """Fetch the advanced result for a task. Returns (parsed_json, raw_bytes)."""


class ProviderError(RuntimeError):
    pass


class HttpMapsProvider:
    """Real DataForSEO client. Requires network + credentials (paid)."""

    BASE = "https://api.dataforseo.com"

    def __init__(self, creds: ProviderCreds, post_endpoint: str, get_endpoint: str,
                 *, poll_interval_s: float = 5.0, poll_timeout_s: float = 300.0):
        self._creds = creds
        self._post_endpoint = post_endpoint
        self._get_endpoint = get_endpoint
        self._poll_interval_s = poll_interval_s
        self._poll_timeout_s = poll_timeout_s

    def _client(self):
        import httpx  # imported lazily so offline tests need no dependency
        return httpx.Client(base_url=self.BASE, auth=(self._creds.login, self._creds.password), timeout=60.0)

    def task_post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bytes, Optional[str]]:
        with self._client() as client:
            resp = client.post(self._post_endpoint, json=[payload])
            resp.raise_for_status()
            data = resp.json()
        tasks = data.get("tasks") or []
        if not tasks:
            # Surface the provider-level status so a terminal_failure is diagnosable
            # (e.g. auth/quota/malformed-request) rather than an opaque "no tasks".
            raise ProviderError(
                f"task_post returned no tasks "
                f"(provider status {data.get('status_code')}: {data.get('status_message')})")
        t0 = tasks[0]
        # 20100 = "Task Created". A non-created task (e.g. 40xxx) means the task was
        # rejected at submission; report its status instead of a later opaque timeout.
        if t0.get("status_code") not in (20100, None) and not t0.get("id"):
            raise ProviderError(
                f"task_post did not create a task "
                f"(task status {t0.get('status_code')}: {t0.get('status_message')})")
        return data, resp.content, t0.get("id")

    def task_get_advanced(self, task_id: str) -> tuple[dict[str, Any], bytes]:
        endpoint = self._get_endpoint.replace("{id}", task_id)
        deadline = time.monotonic() + self._poll_timeout_s
        last_status = None
        with self._client() as client:
            while True:
                resp = client.get(endpoint)
                resp.raise_for_status()
                data = resp.json()
                task = (data.get("tasks") or [{}])[0]
                last_status = (task.get("status_code"), task.get("status_message"))
                # 40602 = "Task In Queue"; 40601 = "Task Handed"; keep polling those.
                if task.get("status_code") not in (40601, 40602):
                    return data, resp.content
                if time.monotonic() >= deadline:
                    # Include the last observed provider status so a poll-timeout is
                    # distinguishable from other failures in the captured detail.
                    raise ProviderError(
                        f"task {task_id} not ready within {self._poll_timeout_s}s "
                        f"(last provider status {last_status[0]}: {last_status[1]})")
                time.sleep(self._poll_interval_s)
