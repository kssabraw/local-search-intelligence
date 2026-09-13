"""Single-coordinate vertical-slice orchestrator + CLI.

one Maps task_post -> immutable raw -> parse -> normalize -> resolve -> cost.

Dependencies (provider, raw store, DB connection) are injected so the pipeline
runs with fakes offline (tests / scripts/validate_spike.py) and with real clients
in production. The LIVE run makes the first PAID DataForSEO call and is gated on
owner confirmation + verified secrets (see collector/README.md).
"""
from __future__ import annotations
import argparse
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .dataforseo import MapsProvider
from .models import ManifestContext
from .parse_maps import parse_maps
from .raw_store import RawStore
from .repository import Repo, utcnow

COLLECTOR_VERSION = "0.1.0"
PARSER_VERSION = "maps-parser-0.1.0"
RESOLVER_VERSION = "place-id-resolver-0.1.0"

_SURFACE_GEOMETRY_TAG = {"maps": "MAPORG", "organic": "MAPORG", "aio": "AIO"}
_TREATMENT_SET = {"maps": "GOOGLE_QUERY_V1", "organic": "GOOGLE_QUERY_V1",
                  "aio": "AIO_QUERY_V1", "chatgpt": "CHATGPT_PROMPT_V1"}


def render_keyword(ctx: ManifestContext) -> str:
    kw = ctx.exact_template
    if ctx.city_slot_required or "[CITY]" in kw:
        kw = kw.replace("[CITY]", ctx.market_city)
    return kw


def build_request(ctx: ManifestContext, zoom_override: Optional[str] = None) -> dict[str, Any]:
    location_coordinate = (ctx.location_template
                           .replace("{lat}", f"{ctx.latitude:.7f}")
                           .replace("{lon}", f"{ctx.longitude:.7f}"))
    if zoom_override:
        # DIAGNOSTIC ONLY: override the locked coordinate zoom (e.g. "12z") to test
        # whether the frozen 17z suppresses local results. Never used for panel collection.
        z = zoom_override if zoom_override.endswith("z") else f"{zoom_override}z"
        location_coordinate = re.sub(r",\s*\d+z\s*$", f",{z}", location_coordinate)
    req: dict[str, Any] = {
        "keyword": render_keyword(ctx),
        "location_coordinate": location_coordinate,
    }
    if ctx.language_code:
        req["language_code"] = ctx.language_code
    if ctx.device:
        req["device"] = ctx.device
    if ctx.operating_system:
        req["os"] = ctx.operating_system
    if ctx.result_depth:
        req["depth"] = ctx.result_depth
    return req


def usd_to_microusd(usd: Optional[float]) -> int:
    return int(round((usd or 0.0) * 1_000_000))


def run_spike(conn, *, ctx: ManifestContext, provider: MapsProvider, raw_store: RawStore,
              replicate_no: int = 1, wave_code: Optional[str] = None,
              zoom_override: Optional[str] = None, probe_only: bool = False) -> dict[str, Any]:
    if ctx.eligibility != "eligible_land":
        raise ValueError(
            f"coordinate {ctx.coordinate_code} is '{ctx.eligibility}', not eligible_land; "
            f"structural missingness is never submitted (CLAUDE.md)"
        )
    repo = Repo(conn)
    now = utcnow()
    wave_code = wave_code or (
        f"PROBE-{ctx.surface_code}-{now:%Y%m%dT%H%M%S}" if probe_only
        else f"DIAG-ZOOM-{now:%Y%m%dT%H%M%S}" if zoom_override
        else f"SPIKE-{now:%Y%m%dT%H%M%S}")
    collector_cv = repo.component_version("collector", "maps-spike", COLLECTOR_VERSION)
    parser_cv = repo.component_version("parser", "maps-advanced", PARSER_VERSION)
    resolver_cv = repo.component_version("resolver", "place-id-first", RESOLVER_VERSION)
    graph_release = repo.entity_graph_release(f"spike-{ctx.methodology_code}", ctx.methodology_version_id)

    wave_id = repo.get_or_create_wave(
        methodology_version_id=ctx.methodology_version_id, wave_code=wave_code,
        wave_kind="validation", scheduled_for=now)

    request = build_request(ctx, zoom_override=zoom_override)
    job_id, jkey, observation_exists = repo.plan_job(
        ctx=ctx, wave_id=wave_id, replicate_no=replicate_no,
        rendered_input_text=request["keyword"], rendered_request=request, generated_by=collector_cv)

    if observation_exists:
        # Idempotent: a terminal observation already exists -> never re-call the paid provider.
        return {"job_id": job_id, "job_key": jkey, "status": "already_observed",
                "wave_code": wave_code, "coordinate": ctx.coordinate_code}

    repo.job_event(job_id, "planned")

    # request payload (immutable raw)
    req_bytes = json.dumps([request], sort_keys=True).encode()
    req_blob = raw_store.put(surface_code=ctx.surface_code, payload_kind="request", raw_bytes=req_bytes)
    req_blob_id = repo.raw_blob(sha256=req_blob.sha256, bucket=req_blob.bucket, path=req_blob.path,
                               byte_size=req_blob.byte_size, mime_type=req_blob.mime_type,
                               content_encoding=req_blob.content_encoding)
    req_payload_id = repo.provider_payload(provider_id=ctx.provider_id, blob_id=req_blob_id,
                                           payload_kind="request", provider_task_id=None, captured_at=now)

    attempt_id = repo.attempt(job_id=job_id, attempt_no=1, provider_id=ctx.provider_id,
                              provider_task_id=None, request_payload_id=req_payload_id,
                              submitted_at=now, collector_cv=collector_cv)
    repo.job_event(job_id, "submitted", attempt_no=1)
    repo.attempt_event(attempt_id=attempt_id, event_type="submitted")

    # ---- PAID CALL: task_post ----
    post_json, post_bytes, provider_task_id = provider.task_post(request)
    post_blob = raw_store.put(surface_code=ctx.surface_code, payload_kind="task_post_response", raw_bytes=post_bytes)
    post_blob_id = repo.raw_blob(sha256=post_blob.sha256, bucket=post_blob.bucket, path=post_blob.path,
                                byte_size=post_blob.byte_size, mime_type=post_blob.mime_type,
                                content_encoding=post_blob.content_encoding)
    post_payload_id = repo.provider_payload(provider_id=ctx.provider_id, blob_id=post_blob_id,
                                            payload_kind="task_post_response",
                                            provider_task_id=provider_task_id, captured_at=utcnow())
    repo.attempt_event(attempt_id=attempt_id, event_type="provider_acknowledged",
                       response_payload_id=post_payload_id,
                       provider_status_code=str((post_json.get("tasks") or [{}])[0].get("status_code")))

    # ---- task_get advanced ----
    get_json, get_bytes = provider.task_get_advanced(provider_task_id)
    received = utcnow()
    get_blob = raw_store.put(surface_code=ctx.surface_code, payload_kind="task_get_response", raw_bytes=get_bytes)
    get_blob_id = repo.raw_blob(sha256=get_blob.sha256, bucket=get_blob.bucket, path=get_blob.path,
                               byte_size=get_blob.byte_size, mime_type=get_blob.mime_type,
                               content_encoding=get_blob.content_encoding)
    get_payload_id = repo.provider_payload(provider_id=ctx.provider_id, blob_id=get_blob_id,
                                           payload_kind="task_get_response",
                                           provider_task_id=provider_task_id, captured_at=received)
    repo.attempt_event(attempt_id=attempt_id, event_type="response_received", response_payload_id=get_payload_id)

    if probe_only:
        # Surface-agnostic capture-feasibility probe (ADR-0005): record the provider
        # status + generic result-item count + check_url; store raw immutably; do NOT
        # run surface-specific normalization/resolution (which is Maps-only so far).
        tasks = get_json.get("tasks") or []
        t = tasks[0] if tasks else {}
        tsc = t.get("status_code")
        results = t.get("result") or []
        res0 = results[0] if results else {}
        item_count = len(res0.get("items") or [])
        state = "returned" if tsc in (20000, 40102) else "provider_failure"
        md = {"probe": True, "surface": ctx.surface_code, "status_code": tsc,
              "status_message": t.get("status_message"), "item_count": item_count,
              "check_url": res0.get("check_url"), "item_types": res0.get("item_types"),
              "se_results_count": res0.get("se_results_count")}
        observation_id = repo.observation(
            job_id=job_id, accepted_attempt_id=attempt_id, state=state, observed_at=received,
            received_at=received, raw_payload_id=get_payload_id, parser_cv=parser_cv, parser_metadata=md)
        ok = state == "returned"
        repo.attempt_event(attempt_id=attempt_id, event_type="succeeded" if ok else "terminal_failure",
                           provider_status_code=str(tsc) if tsc is not None else None,
                           error_code=None if ok else "provider_failure")
        repo.job_event(job_id, "succeeded" if ok else "terminal_failure", attempt_no=1)
        cost_id = repo.cost_event(
            provider_id=ctx.provider_id, wave_id=wave_id, job_id=job_id, attempt_id=attempt_id,
            amount_microusd=0, purpose=f"{ctx.surface_code}_capture_probe", occurred_at=received,
            billed_units=1.0, provider_reference=provider_task_id)
        return {"job_id": job_id, "job_key": jkey, "wave_code": wave_code, "coordinate": ctx.coordinate_code,
                "surface": ctx.surface_code, "status": "probed", "observation_state": state,
                "provider_status_code": tsc, "item_count": item_count,
                "check_url": res0.get("check_url"), "observation_id": observation_id, "cost_event_id": cost_id}

    # ---- parse ----
    parsed = parse_maps(get_json)

    # ---- observation ----
    observation_id = repo.observation(
        job_id=job_id, accepted_attempt_id=attempt_id, state=parsed.observation_state,
        observed_at=received, received_at=received, raw_payload_id=get_payload_id, parser_cv=parser_cv,
        parser_metadata=parsed.search_metadata)

    resolutions: list[dict[str, Any]] = []
    if parsed.observation_state == "returned":
        repo.attempt_event(attempt_id=attempt_id, event_type="succeeded")
        repo.job_event(job_id, "succeeded", attempt_no=1)
        # ---- normalize ----
        obj_items = repo.write_maps(observation_id=observation_id, surface_id=ctx.surface_id,
                                    parsed=parsed, parser_cv=parser_cv)
        # ---- resolve (place_id-first) ----
        for obj_id, item in obj_items:
            resolutions.append(repo.resolve_and_assert(
                observed_object_id=obj_id, item=item, resolver_cv=resolver_cv, graph_release_id=graph_release))
    else:
        repo.attempt_event(attempt_id=attempt_id, event_type="terminal_failure",
                           provider_status_code=str(parsed.search_metadata.get("status_code"))
                           if parsed.search_metadata.get("status_code") is not None else None,
                           error_code=parsed.observation_state)
        repo.job_event(job_id, "terminal_failure", attempt_no=1, reason_code=parsed.observation_state)

    # ---- cost ledger (every paid call attributed) ----
    cost_id = repo.cost_event(
        provider_id=ctx.provider_id, wave_id=wave_id, job_id=job_id, attempt_id=attempt_id,
        amount_microusd=usd_to_microusd(parsed.provider_cost_usd),
        purpose="maps_spike_task", occurred_at=received, billed_units=1.0,
        provider_reference=provider_task_id)

    return {
        "job_id": job_id, "job_key": jkey, "wave_code": wave_code, "coordinate": ctx.coordinate_code,
        "observation_id": observation_id, "observation_state": parsed.observation_state,
        "returned_result_count": parsed.returned_result_count,
        "resolved": sum(1 for r in resolutions if r["entity_id"]),
        "results": len(resolutions), "cost_event_id": cost_id,
        "provider_cost_usd": parsed.provider_cost_usd, "status": "collected",
    }


def _resolve_ctx(conn, args) -> ManifestContext:
    repo = Repo(conn)
    tag = _SURFACE_GEOMETRY_TAG.get(args.surface, "MAPORG")
    return repo.load_manifest_context(
        methodology_code=args.methodology, surface_code=args.surface,
        industry_code=args.industry, market_code=args.market, point_code=args.point,
        treatment_set_code=_TREATMENT_SET[args.surface], treatment_code=args.treatment,
    )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Single-coordinate Maps vertical-slice spike")
    p.add_argument("--methodology", default="MANIFEST_V1_0")
    p.add_argument("--surface", default="maps", choices=["maps", "organic"])
    p.add_argument("--industry", required=True, help="e.g. IND010 (Locksmith)")
    p.add_argument("--market", required=True, help="e.g. MKT008 (Vancouver WA)")
    p.add_argument("--point", default="C", help="geometry point code, e.g. C, N1")
    p.add_argument("--treatment", default="Q1", help="treatment code Q1..Q4")
    p.add_argument("--replicate", type=int, default=1)
    p.add_argument("--wave-code", default=None)
    p.add_argument("--zoom", default=None,
                   help="DIAGNOSTIC ONLY: override the locked coordinate zoom, e.g. '12z'. "
                        "Tags the wave DIAG-ZOOM-*; never used for panel collection.")
    p.add_argument("--probe-only", action="store_true",
                   help="capture-feasibility probe (ADR-0005): call provider, store raw, record "
                        "provider status + result-item count; NO surface-specific normalization")
    p.add_argument("--dry-run", action="store_true",
                   help="resolve manifest context + print the request; NO provider call, NO writes")
    args = p.parse_args(argv)

    import psycopg
    from .config import Settings
    settings = Settings()

    with psycopg.connect(settings.db_url()) as conn:
        ctx = _resolve_ctx(conn, args)
        if args.dry_run:
            print(json.dumps({
                "dry_run": True, "coordinate": ctx.coordinate_code, "eligibility": ctx.eligibility,
                "latitude": ctx.latitude, "longitude": ctx.longitude,
                "post_endpoint": ctx.post_endpoint, "zoom_override": args.zoom,
                "request": build_request(ctx, zoom_override=args.zoom),
            }, indent=2))
            conn.rollback()
            return 0

        # LIVE PAID PATH
        from .config import ProviderCreds, StorageConfig
        from .dataforseo import HttpMapsProvider
        from .raw_store import SupabaseStorageRawStore
        provider = HttpMapsProvider(ProviderCreds.from_env(), ctx.post_endpoint, ctx.get_endpoint)
        raw_store = SupabaseStorageRawStore(StorageConfig.from_env())
        result = run_spike(conn, ctx=ctx, provider=provider, raw_store=raw_store,
                           replicate_no=args.replicate, wave_code=args.wave_code,
                           zoom_override=args.zoom, probe_only=args.probe_only)
        conn.commit()
        print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
