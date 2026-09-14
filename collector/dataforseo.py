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


class BatchProvider(Protocol):
    """The DataForSEO Standard *decoupled* method used at panel scale (ADR-0007).

    Submission and collection are separated: post many tasks at once, then poll a
    ``tasks_ready`` roster and pull each ready task with ``task_get_advanced``. The
    provider queue processes tasks in parallel, so wall-clock is bounded by
    provider throughput + a small collector, not by ``n_jobs x 30 s``.
    """

    def task_post_batch(
        self, payloads: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], bytes, list[Optional[str]]]:
        """POST up to 100 tasks in one request. Returns (parsed_json, raw_bytes,
        provider_task_ids) with one task id per input payload IN SUBMISSION ORDER."""

    def tasks_ready(self) -> tuple[dict[str, Any], bytes, list[str]]:
        """Poll the ready roster. Returns (parsed_json, raw_bytes, ready_task_ids)."""

    def task_get_advanced(self, task_id: str) -> tuple[dict[str, Any], bytes]:
        """Fetch the advanced result for a ready task. Returns (parsed_json, raw_bytes)."""


MAX_TASKS_PER_POST = 100  # DataForSEO hard cap for a single task_post request


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

    # ---- Standard decoupled method (batched submit + ready roster) ----
    def _ready_endpoint(self) -> str:
        """Derive the ``tasks_ready`` endpoint from the surface's task_post endpoint
        (e.g. .../maps/task_post -> .../maps/tasks_ready)."""
        if self._post_endpoint.endswith("/task_post"):
            return self._post_endpoint[: -len("/task_post")] + "/tasks_ready"
        raise ProviderError(
            f"cannot derive tasks_ready endpoint from post_endpoint {self._post_endpoint!r}")

    def task_post_batch(
        self, payloads: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], bytes, list[Optional[str]]]:
        if not payloads:
            raise ValueError("task_post_batch requires at least one payload")
        if len(payloads) > MAX_TASKS_PER_POST:
            raise ValueError(
                f"task_post_batch got {len(payloads)} payloads; the DataForSEO cap is "
                f"{MAX_TASKS_PER_POST} per request")
        with self._client() as client:
            resp = client.post(self._post_endpoint, json=list(payloads))
            resp.raise_for_status()
            data = resp.json()
        tasks = data.get("tasks") or []
        if len(tasks) != len(payloads):
            # The response MUST carry one task per submitted payload, in order; a
            # mismatch means we cannot attribute task ids to jobs safely.
            raise ProviderError(
                f"task_post_batch submitted {len(payloads)} tasks but the provider "
                f"returned {len(tasks)} (status {data.get('status_code')}: "
                f"{data.get('status_message')})")
        task_ids: list[Optional[str]] = []
        for t in tasks:
            # A per-task rejection (e.g. 40xxx with no id) is surfaced as a None so
            # the caller records that job as a terminal_failure without a task id.
            task_ids.append(t.get("id"))
        return data, resp.content, task_ids

    def tasks_ready(self) -> tuple[dict[str, Any], bytes, list[str]]:
        with self._client() as client:
            resp = client.get(self._ready_endpoint())
            resp.raise_for_status()
            data = resp.json()
        ready: list[str] = []
        for task in data.get("tasks") or []:
            for res in task.get("result") or []:
                tid = res.get("id")
                if tid:
                    ready.append(tid)
        return data, resp.content, ready

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
