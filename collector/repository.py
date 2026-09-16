"""All database writes for the vertical slice, via psycopg.

Every write is an INSERT (the raw/observation/resolution/cost tables are
append-only; their triggers reject UPDATE/DELETE, so get-or-create uses
`ON CONFLICT DO NOTHING` + `SELECT`, never `DO UPDATE`). Entity identity lives in
the external-identifier + assertion tables (ADR-0003), not on core.entity.
"""
from __future__ import annotations
import json
import zlib
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg import errors
from psycopg.types.json import Jsonb

from .idempotency import job_key
from .models import (ManifestContext, OrganicItem, ParsedAio, ParsedMaps, ParsedOrganic)
from .normalize import normalize_domain, normalize_url
from .resolve import resolve_aio_business, resolve_organic_item, resolve_maps_item


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Web-entity CREATION is serialized per registered-domain shard so parallel
# collectors racing to mint the SAME directory domain/url (e.g. yelp.com recurring
# across cells) do not churn on unique violations, WITHOUT serializing unrelated
# domains behind one global lock (the pilot's single-key lock was correct but caps
# throughput at Full-Panel scale). Two-int advisory key (classid, shard) namespaces
# it away from any other advisory lock.
#
# Deadlock-freedom is NOT left to luck: an observation that resolves several
# destinations with DIFFERENT domains would, with lazily-acquired per-domain locks,
# be able to grab shard locks in conflicting orders across workers (and, worse,
# deadlock on the underlying UNIQUE indexes when two txns insert the same two
# domains in opposite order). So `prelock_web_domains` acquires ALL of an
# observation's distinct shard locks up front in a single global order (ascending
# shard number), xact-scoped. A consistent acquisition order across every worker
# makes an advisory-lock cycle impossible, and holding all needed shards before any
# insert makes a same-domain index cycle impossible. Correctness never depends on
# the lock anyway: the UNIQUE(normalized_domain/url) index + SAVEPOINT recovery
# below already guarantee a single canonical entity; the lock only removes churn.
_WEB_ENTITY_LOCK_CLASSID = 0x4C534957  # "LSIW"
_WEB_ENTITY_LOCK_SHARDS = 1024


def _web_create_shard(shard_key: str) -> int:
    """Deterministic shard in [0, _WEB_ENTITY_LOCK_SHARDS) for a registered domain.
    CRC32 is stable across processes/containers, so every worker maps a given domain
    to the same shard (cross-process serialization on that domain)."""
    return zlib.crc32(shard_key.encode("utf-8")) % _WEB_ENTITY_LOCK_SHARDS


class Repo:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # ---- lookups --------------------------------------------------------
    def load_manifest_context(self, *, methodology_code: str, surface_code: str,
                              industry_code: str, market_code: str, point_code: str,
                              treatment_set_code: str, treatment_code: str) -> ManifestContext:
        row = self.conn.execute(
            """
            select mv.methodology_version_id, mv.methodology_code, s.surface_id, s.surface_code,
                   i.industry_id, mk.market_id, mk.city,
                   st.surface_treatment_id, t.treatment_id, t.treatment_code, t.treatment_kind,
                   t.exact_template, t.city_slot_required,
                   mc.coordinate_id, mc.latitude, mc.longitude, mc.eligibility::text,
                   pp.provider_profile_id, pp.provider_id, pp.post_endpoint, pp.get_endpoint,
                   pp.location_template, pp.language_code, pp.device, pp.operating_system, pp.result_depth
            from manifest.methodology_version mv
            join manifest.surface s on s.surface_code = %(surface_code)s
            join manifest.industry i on i.industry_code = %(industry_code)s
            join manifest.market mk on mk.market_code = %(market_code)s
            join manifest.surface_config sc
              on sc.methodology_version_id = mv.methodology_version_id and sc.surface_id = s.surface_id
            join manifest.provider_profile pp on pp.provider_profile_id = sc.provider_profile_id
            join manifest.geometry_version gv on gv.geometry_version_id = sc.geometry_version_id
            join manifest.geometry_point gp
              on gp.geometry_version_id = gv.geometry_version_id and gp.point_code = %(point_code)s
            join manifest.market_coordinate mc
              on mc.methodology_version_id = mv.methodology_version_id
             and mc.market_id = mk.market_id and mc.geometry_point_id = gp.geometry_point_id
            join manifest.treatment t
              on t.methodology_version_id = mv.methodology_version_id and t.industry_id = i.industry_id
             and t.treatment_set_code = %(treatment_set_code)s and t.treatment_code = %(treatment_code)s
            join manifest.surface_treatment st
              on st.methodology_version_id = mv.methodology_version_id
             and st.surface_id = s.surface_id and st.treatment_id = t.treatment_id
            where mv.methodology_code = %(methodology_code)s
            """,
            dict(methodology_code=methodology_code, surface_code=surface_code,
                 industry_code=industry_code, market_code=market_code, point_code=point_code,
                 treatment_set_code=treatment_set_code, treatment_code=treatment_code),
        ).fetchone()
        if row is None:
            raise LookupError(
                f"no manifest context for {methodology_code}/{surface_code}/{industry_code}/"
                f"{market_code}/{point_code}/{treatment_set_code}:{treatment_code}"
            )
        cols = ["methodology_version_id", "methodology_code", "surface_id", "surface_code",
                "industry_id", "market_id", "market_city", "surface_treatment_id", "treatment_id",
                "treatment_code", "treatment_kind", "exact_template", "city_slot_required",
                "coordinate_id", "latitude", "longitude", "eligibility", "provider_profile_id",
                "provider_id", "post_endpoint", "get_endpoint", "location_template", "language_code",
                "device", "operating_system", "result_depth"]
        d = dict(zip(cols, row))
        return ManifestContext(
            coordinate_code=f"{market_code}_{'MAPORG' if surface_code in ('maps', 'organic') else 'AIO'}_{point_code}",
            latitude=float(d.pop("latitude")), longitude=float(d.pop("longitude")),
            **d,
        )

    # ---- version registries --------------------------------------------
    def component_version(self, kind: str, name: str, version_code: str, *, git_sha: Optional[str] = None) -> str:
        self.conn.execute(
            """insert into ops.component_version (component_kind, component_name, version_code, git_sha)
               values (%s,%s,%s,%s) on conflict (component_kind, component_name, version_code) do nothing""",
            (kind, name, version_code, git_sha),
        )
        return self.conn.execute(
            """select component_version_id from ops.component_version
               where component_kind=%s and component_name=%s and version_code=%s""",
            (kind, name, version_code),
        ).fetchone()[0]

    def entity_graph_release(self, release_code: str, methodology_version_id: str) -> str:
        self.conn.execute(
            """insert into core.entity_graph_release (release_code, methodology_version_id, status)
               values (%s,%s,'draft') on conflict (release_code) do nothing""",
            (release_code, methodology_version_id),
        )
        return self.conn.execute(
            "select entity_graph_release_id from core.entity_graph_release where release_code=%s",
            (release_code,),
        ).fetchone()[0]

    # ---- wave / job ----------------------------------------------------
    def get_or_create_wave(self, *, methodology_version_id: str, wave_code: str,
                           wave_kind: str, scheduled_for: datetime,
                           panel_subset_id: Optional[str] = None) -> str:
        self.conn.execute(
            """insert into ops.collection_wave
                 (methodology_version_id, wave_code, wave_kind, scheduled_for, panel_subset_id)
               values (%s,%s,%s,%s,%s) on conflict (wave_code) do nothing""",
            (methodology_version_id, wave_code, wave_kind, scheduled_for, panel_subset_id),
        )
        return self.conn.execute(
            "select wave_id from ops.collection_wave where wave_code=%s", (wave_code,)
        ).fetchone()[0]

    def panel_subset_id(self, *, methodology_version_id: str, subset_code: str) -> Optional[str]:
        row = self.conn.execute(
            "select panel_subset_id from manifest.panel_subset "
            "where methodology_version_id=%s and subset_code=%s",
            (methodology_version_id, subset_code),
        ).fetchone()
        return row[0] if row else None

    def plan_job(self, *, ctx: ManifestContext, wave_id: str, replicate_no: int,
                 rendered_input_text: str, rendered_request: dict[str, Any],
                 generated_by: Optional[str]) -> tuple[str, str, bool]:
        """Returns (job_id, job_key, observation_exists)."""
        jkey = job_key(
            methodology_version_id=ctx.methodology_version_id, wave_id=wave_id,
            surface_id=ctx.surface_id, industry_id=ctx.industry_id, market_id=ctx.market_id,
            surface_treatment_id=ctx.surface_treatment_id, coordinate_id=ctx.coordinate_id,
            replicate_no=replicate_no,
        )
        req_json = json.dumps(rendered_request, sort_keys=True)
        import hashlib
        req_sha = hashlib.sha256(req_json.encode()).hexdigest()
        self.conn.execute(
            """insert into ops.collection_job
                 (job_key, wave_id, methodology_version_id, surface_id, industry_id, market_id,
                  surface_treatment_id, coordinate_id, provider_profile_id, replicate_no,
                  rendered_input_text, rendered_request, rendered_request_sha256,
                  planned_eligibility, generated_by_component_version_id)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::manifest.coordinate_eligibility,%s)
               on conflict (job_key) do nothing""",
            (jkey, wave_id, ctx.methodology_version_id, ctx.surface_id, ctx.industry_id,
             ctx.market_id, ctx.surface_treatment_id, ctx.coordinate_id, ctx.provider_profile_id,
             replicate_no, rendered_input_text, Jsonb(rendered_request), req_sha,
             ctx.eligibility, generated_by),
        )
        job_id = self.conn.execute(
            "select job_id from ops.collection_job where job_key=%s", (jkey,)
        ).fetchone()[0]
        exists = self.conn.execute(
            "select 1 from ops.observation where job_id=%s", (job_id,)
        ).fetchone() is not None
        return job_id, jkey, exists

    def job_event(self, job_id: str, status: str, *, attempt_no: Optional[int] = None,
                  reason_code: Optional[str] = None, actor: str = "collector.spike",
                  details: Optional[dict[str, Any]] = None) -> None:
        self.conn.execute(
            """insert into ops.job_event (job_id, status, attempt_no, actor, reason_code, details)
               values (%s,%s::ops.job_status,%s,%s,%s,%s)""",
            (job_id, status, attempt_no, actor, reason_code, Jsonb(details or {})),
        )

    # ---- raw + attempts ------------------------------------------------
    def raw_blob(self, *, sha256: str, bucket: str, path: str, byte_size: int,
                 mime_type: str, content_encoding: Optional[str]) -> str:
        self.conn.execute(
            """insert into ops.raw_blob (sha256, storage_bucket, storage_path, byte_size, mime_type, content_encoding)
               values (%s,%s,%s,%s,%s,%s) on conflict (sha256) do nothing""",
            (sha256, bucket, path, byte_size, mime_type, content_encoding),
        )
        return self.conn.execute(
            "select blob_id from ops.raw_blob where sha256=%s", (sha256,)
        ).fetchone()[0]

    def provider_payload(self, *, provider_id: str, blob_id: str, payload_kind: str,
                         provider_task_id: Optional[str], captured_at: datetime) -> str:
        return self.conn.execute(
            """insert into ops.provider_payload (provider_id, blob_id, payload_kind, provider_task_id, captured_at)
               values (%s,%s,%s::ops.payload_kind,%s,%s) returning payload_id""",
            (provider_id, blob_id, payload_kind, provider_task_id, captured_at),
        ).fetchone()[0]

    def attempt(self, *, job_id: str, attempt_no: int, provider_id: str, provider_task_id: Optional[str],
                request_payload_id: Optional[str], submitted_at: datetime, collector_cv: Optional[str]) -> str:
        return self.conn.execute(
            """insert into ops.collection_attempt
                 (job_id, attempt_no, provider_id, provider_task_id, request_payload_id,
                  submitted_at, collector_component_version_id)
               values (%s,%s,%s,%s,%s,%s,%s) returning attempt_id""",
            (job_id, attempt_no, provider_id, provider_task_id, request_payload_id, submitted_at, collector_cv),
        ).fetchone()[0]

    def attempt_event(self, *, attempt_id: str, event_type: str, response_payload_id: Optional[str] = None,
                      provider_status_code: Optional[str] = None, error_code: Optional[str] = None) -> None:
        self.conn.execute(
            """insert into ops.collection_attempt_event
                 (attempt_id, event_type, response_payload_id, provider_status_code, error_code)
               values (%s,%s::ops.attempt_event_type,%s,%s,%s)""",
            (attempt_id, event_type, response_payload_id, provider_status_code, error_code),
        )

    # ---- observation + normalization -----------------------------------
    def observation(self, *, job_id: str, accepted_attempt_id: Optional[str], state: str,
                    observed_at: datetime, received_at: Optional[datetime], raw_payload_id: Optional[str],
                    parser_cv: Optional[str], parser_metadata: Optional[dict[str, Any]] = None) -> str:
        return self.conn.execute(
            """insert into ops.observation
                 (job_id, accepted_attempt_id, observation_state, observed_at, received_at,
                  raw_payload_id, parser_version_id, parser_metadata)
               values (%s,%s,%s::ops.observation_state,%s,%s,%s,%s,%s) returning observation_id""",
            (job_id, accepted_attempt_id, state, observed_at, received_at, raw_payload_id, parser_cv,
             Jsonb(parser_metadata or {})),
        ).fetchone()[0]

    def write_maps(self, *, observation_id: str, surface_id: str, parsed: ParsedMaps,
                   parser_cv: Optional[str]) -> list[tuple[str, Any]]:
        """Insert maps.observation + per-item observed_object + maps.result.

        Returns [(observed_object_id, MapsItem)] for the resolution stage.
        """
        self.conn.execute(
            """insert into maps.observation (observation_id, returned_result_count, provider_depth, search_metadata)
               values (%s,%s,%s,%s)""",
            (observation_id, parsed.returned_result_count, parsed.provider_depth, Jsonb(parsed.search_metadata)),
        )
        out = []
        for item in parsed.items:
            obj_id = self.conn.execute(
                """insert into core.observed_object
                     (observation_id, surface_id, object_kind, local_sequence, raw_name, raw_url,
                      raw_domain, raw_phone, raw_address, raw_external_ids, raw_attributes, parser_version_id)
                   values (%s,%s,'business',%s,%s,%s,%s,%s,%s,%s,%s,%s) returning observed_object_id""",
                (observation_id, surface_id, item.result_sequence, item.title_raw, item.url_raw,
                 item.domain_raw, item.phone_raw, item.address_raw,
                 Jsonb({k: v for k, v in {"place_id": item.place_id, "cid": item.cid}.items() if v}),
                 Jsonb(item.provider_fields), parser_cv),
            ).fetchone()[0]
            self.conn.execute(
                """insert into maps.result
                     (observation_id, result_sequence, rank_absolute, rank_group, provider_item_type,
                      title_raw, category_raw, rating, review_count, address_raw, phone_raw,
                      latitude, longitude, url_raw, observed_object_id, provider_fields)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (observation_id, item.result_sequence, item.rank_absolute, item.rank_group,
                 item.provider_item_type, item.title_raw, item.category_raw, item.rating,
                 item.review_count, item.address_raw, item.phone_raw, item.latitude, item.longitude,
                 item.url_raw, obj_id, Jsonb(item.provider_fields)),
            )
            out.append((obj_id, item))
        return out

    def write_organic(self, *, observation_id: str, surface_id: str, parsed: ParsedOrganic,
                      parser_cv: Optional[str]) -> list[tuple[str, Any]]:
        """Insert organic.observation + one organic.result per SERP block.

        Every block (organic, local_pack, people_also_ask, ...) becomes an
        organic.result row with its result_type preserved. Only an organic web
        destination (`is_destination`) also becomes a core.observed_object and is
        returned for the resolution stage; other blocks carry a NULL
        observed_object_id.

        Returns [(observed_object_id, OrganicItem)] for the destinations.
        """
        self.conn.execute(
            """insert into organic.observation (observation_id, returned_result_count, provider_depth, serp_metadata)
               values (%s,%s,%s,%s)""",
            (observation_id, parsed.returned_result_count, parsed.provider_depth, Jsonb(parsed.serp_metadata)),
        )
        out = []
        for item in parsed.items:
            obj_id = None
            if item.is_destination:
                obj_id = self.conn.execute(
                    """insert into core.observed_object
                         (observation_id, surface_id, object_kind, local_sequence, raw_name, raw_url,
                          raw_domain, raw_attributes, parser_version_id)
                       values (%s,%s,'organic_result',%s,%s,%s,%s,%s,%s) returning observed_object_id""",
                    (observation_id, surface_id, item.result_sequence, item.title_raw, item.url_raw,
                     item.domain_raw, Jsonb(item.provider_fields), parser_cv),
                ).fetchone()[0]
            self.conn.execute(
                """insert into organic.result
                     (observation_id, result_sequence, rank_absolute, page_number, position_on_page,
                      result_type, title_raw, snippet_raw, url_raw, domain_raw, observed_object_id, provider_fields)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (observation_id, item.result_sequence, item.rank_absolute, item.page_number,
                 item.position_on_page, item.result_type, item.title_raw, item.snippet_raw,
                 item.url_raw, item.domain_raw, obj_id, Jsonb(item.provider_fields)),
            )
            if obj_id:
                out.append((obj_id, item))
        return out

    # ---- entity resolution (place_id-first) ----------------------------
    def _find_entity_by_identifier(self, namespace: str, id_type: str, id_value: str) -> Optional[str]:
        row = self.conn.execute(
            """select eia.entity_id
               from core.external_identifier ei
               join core.external_identifier_assertion eia on eia.external_identifier_id = ei.external_identifier_id
               where ei.namespace=%s and ei.identifier_type=%s and ei.identifier_value=%s
               order by eia.created_at desc limit 1""",
            (namespace, id_type, id_value),
        ).fetchone()
        return row[0] if row else None

    def _external_identifier(self, namespace: str, id_type: str, id_value: str) -> str:
        self.conn.execute(
            """insert into core.external_identifier (namespace, identifier_type, identifier_value, normalized_value)
               values (%s,%s,%s,%s) on conflict (namespace, identifier_type, identifier_value) do nothing""",
            (namespace, id_type, id_value, id_value.lower()),
        )
        return self.conn.execute(
            """select external_identifier_id from core.external_identifier
               where namespace=%s and identifier_type=%s and identifier_value=%s""",
            (namespace, id_type, id_value),
        ).fetchone()[0]

    def _create_entity(self, entity_type_code: str, label: Optional[str]) -> str:
        eid = self.conn.execute(
            """insert into core.entity (entity_type_code, operational_label) values (%s,%s) returning entity_id""",
            (entity_type_code, label),
        ).fetchone()[0]
        if entity_type_code == "business_location":
            self.conn.execute("insert into core.business_location (entity_id) values (%s)", (eid,))
        return eid

    def _assert_identifier(self, *, graph_release_id: str, external_identifier_id: str,
                           entity_id: str, resolution_state: str) -> None:
        self.conn.execute(
            """insert into core.external_identifier_assertion
                 (entity_graph_release_id, external_identifier_id, entity_id, resolution_state)
               values (%s,%s,%s,%s::core.resolution_state)""",
            (graph_release_id, external_identifier_id, entity_id, resolution_state),
        )

    def _ensure_web_identifier(self, id_type: str, value: str, entity_id: str,
                               graph_release_id: str) -> None:
        """Idempotently bind a `web/<id_type>` external identifier to its entity.
        A repeat call (or a concurrent worker that lost the create race and reused
        the winner's entity) finds the existing 'resolved' assertion and no-ops,
        so an identifier is never bound to two different entities."""
        ext_id = self._external_identifier("web", id_type, value)
        already = self.conn.execute(
            """select 1 from core.external_identifier_assertion
               where external_identifier_id=%s and entity_id=%s and resolution_state='resolved' limit 1""",
            (ext_id, entity_id),
        ).fetchone()
        if not already:
            self._assert_identifier(graph_release_id=graph_release_id, external_identifier_id=ext_id,
                                    entity_id=entity_id, resolution_state="resolved")

    def _lock_web_create(self, shard_key: str) -> None:
        """Transaction-scoped advisory lock on ONE registered-domain shard. Held to
        commit (auto-released), and reentrant: when `prelock_web_domains` has already
        taken this shard for the observation, re-acquiring here is a cheap no-op. A
        lone caller (the single-coordinate spike / sequential run) still gets correct
        per-domain serialization; concurrency safety is provided by the ordered
        pre-lock, never by acquisition order here."""
        self.conn.execute(
            "select pg_advisory_xact_lock(%s,%s)",
            (_WEB_ENTITY_LOCK_CLASSID, _web_create_shard(shard_key)),
        )

    def prelock_web_domains(self, domains: list[str]) -> None:
        """Acquire the web-create shard locks for all DISTINCT registered domains an
        observation will mint, in ASCENDING SHARD ORDER (xact-scoped). A single global
        acquisition order across every worker makes an advisory-lock cycle impossible;
        holding every needed shard before any insert makes a same-domain UNIQUE-index
        cycle impossible. Distinct domains that collide onto one shard simply share a
        lock (reduced parallelism, never incorrectness). A no-op for an observation
        with no web destinations."""
        shards = sorted({_web_create_shard(d) for d in domains if d})
        for shard in shards:
            self.conn.execute(
                "select pg_advisory_xact_lock(%s,%s)", (_WEB_ENTITY_LOCK_CLASSID, shard))

    def prelock_organic_domains(self, obj_items: list[tuple[str, Any]]) -> None:
        """Ordered pre-lock (see prelock_web_domains) for the registered domains of an
        organic observation's destinations, derived with the same pure resolver the
        per-item resolve uses, so the shards match exactly and the per-item
        `_lock_web_create` calls become reentrant no-ops."""
        domains: list[str] = []
        for _obj_id, item in obj_items:
            decision = resolve_organic_item(item)
            dom = decision.link_domain_value or (
                decision.identifier_value if decision.entity_type_code == "domain" else None)
            if dom:
                domains.append(dom)
        self.prelock_web_domains(domains)

    def _get_or_create_web_domain(self, *, normalized_domain: str, label: Optional[str],
                                  graph_release_id: str) -> str:
        """Canonical web_domain entity keyed on its UNIQUE `normalized_domain`.

        Concurrency-safe. A domain (e.g. a directory like Yelp) legitimately recurs
        across markets/cells, so parallel workers race to create it. We first look
        up the UNIQUE `core.web_domain.normalized_domain`; on a miss we take the
        global web-create advisory lock, re-check (a peer may have created it while
        we waited), then insert. The insert is wrapped in a SAVEPOINT so that a
        cross-process unique violation rolls back the orphan `core.entity` row and
        we reuse the winner's entity."""
        existing = self.conn.execute(
            "select entity_id from core.web_domain where normalized_domain=%s", (normalized_domain,)
        ).fetchone()
        if existing:
            return existing[0]
        self._lock_web_create(normalized_domain)
        existing = self.conn.execute(
            "select entity_id from core.web_domain where normalized_domain=%s", (normalized_domain,)
        ).fetchone()
        if existing:
            eid = existing[0]
        else:
            try:
                with self.conn.transaction():  # SAVEPOINT
                    eid = self.conn.execute(
                        """insert into core.entity (entity_type_code, operational_label)
                           values ('domain',%s) returning entity_id""", (label,)).fetchone()[0]
                    self.conn.execute(
                        """insert into core.web_domain (entity_id, normalized_domain, registered_domain)
                           values (%s,%s,%s)""", (eid, normalized_domain, normalized_domain))
            except errors.UniqueViolation:
                eid = self.conn.execute(
                    "select entity_id from core.web_domain where normalized_domain=%s", (normalized_domain,)
                ).fetchone()[0]
        self._ensure_web_identifier("domain", normalized_domain, eid, graph_release_id)
        return eid

    def _get_or_create_web_url(self, *, normalized_url: str, domain_entity_id: str,
                               label: Optional[str], graph_release_id: str,
                               shard_domain: str) -> str:
        """Canonical web_url entity keyed on its UNIQUE `normalized_url`.
        Concurrency-safe via the same advisory-lock + re-check + SAVEPOINT recovery
        as `_get_or_create_web_domain` (see that method). Locked on the URL's
        REGISTERED DOMAIN (`shard_domain`), the same shard as its parent domain, so a
        single organic resolve only ever touches one shard."""
        existing = self.conn.execute(
            "select entity_id from core.web_url where normalized_url=%s", (normalized_url,)
        ).fetchone()
        if existing:
            return existing[0]
        self._lock_web_create(shard_domain)
        existing = self.conn.execute(
            "select entity_id from core.web_url where normalized_url=%s", (normalized_url,)
        ).fetchone()
        if existing:
            eid = existing[0]
        else:
            try:
                with self.conn.transaction():  # SAVEPOINT
                    eid = self.conn.execute(
                        """insert into core.entity (entity_type_code, operational_label)
                           values ('url',%s) returning entity_id""", (label,)).fetchone()[0]
                    self.conn.execute(
                        """insert into core.web_url (entity_id, normalized_url, domain_entity_id)
                           values (%s,%s,%s)""", (eid, normalized_url, domain_entity_id))
            except errors.UniqueViolation:
                eid = self.conn.execute(
                    "select entity_id from core.web_url where normalized_url=%s", (normalized_url,)
                ).fetchone()[0]
        self._ensure_web_identifier("url", normalized_url, eid, graph_release_id)
        return eid

    def resolve_and_assert(self, *, observed_object_id: str, item, resolver_cv: str,
                           graph_release_id: str) -> dict[str, Any]:
        decision = resolve_maps_item(item)
        run_id = self.conn.execute(
            """insert into core.resolution_run
                 (observed_object_id, entity_graph_release_id, resolver_version_id, resolver_stage)
               values (%s,%s,%s,%s) returning resolution_run_id""",
            (observed_object_id, graph_release_id, resolver_cv, decision.resolver_stage),
        ).fetchone()[0]

        resolved_entity_id: Optional[str] = None
        if decision.identifier_value and decision.entity_type_code:
            existing = self._find_entity_by_identifier(
                decision.namespace, decision.identifier_type, decision.identifier_value)
            resolved_entity_id = existing or self._create_entity(decision.entity_type_code, item.title_raw)
            ext_id = self._external_identifier(
                decision.namespace, decision.identifier_type, decision.identifier_value)
            if decision.resolution_state in ("resolved", "probable_match"):
                self.conn.execute(
                    """insert into core.external_identifier_assertion
                         (entity_graph_release_id, external_identifier_id, entity_id, resolution_state)
                       values (%s,%s,%s,%s::core.resolution_state)""",
                    (graph_release_id, ext_id, resolved_entity_id, decision.resolution_state),
                )
            self.conn.execute(
                """insert into core.resolution_candidate
                     (resolution_run_id, candidate_entity_id, candidate_rank, match_score, score_semantics)
                   values (%s,%s,1,%s,'rule_based')""",
                (run_id, resolved_entity_id, decision.confidence),
            )

        assertion_entity = resolved_entity_id if decision.resolution_state in ("resolved", "probable_match") else None
        self.conn.execute(
            """insert into core.resolution_assertion
                 (resolution_run_id, entity_graph_release_id, resolved_entity_id, resolution_state,
                  confidence_value, confidence_semantics, supporting_evidence)
               values (%s,%s,%s,%s::core.resolution_state,%s,%s,%s)""",
            (run_id, graph_release_id, assertion_entity, decision.resolution_state,
             decision.confidence, decision.method,
             Jsonb({"method": decision.method, "identifier": decision.identifier_value})),
        )
        return {"observed_object_id": observed_object_id, "state": decision.resolution_state,
                "entity_id": assertion_entity, "method": decision.method}

    def resolve_and_assert_organic(self, *, observed_object_id: str, item, resolver_cv: str,
                                   graph_release_id: str) -> dict[str, Any]:
        """Resolve one organic web destination to a canonical web entity
        (URL-first, then domain). URL resolution mints/links a core.web_url under
        its core.web_domain; the resolution assertion targets the most-specific
        entity (the URL when present, else the domain)."""
        decision = resolve_organic_item(item)
        run_id = self.conn.execute(
            """insert into core.resolution_run
                 (observed_object_id, entity_graph_release_id, resolver_version_id, resolver_stage)
               values (%s,%s,%s,%s) returning resolution_run_id""",
            (observed_object_id, graph_release_id, resolver_cv, decision.resolver_stage),
        ).fetchone()[0]

        # Identity-graph bindings (external_identifier -> entity) are asserted once
        # at mint inside the get-or-create helpers. Per-observation provenance
        # lives in resolution_run + resolution_candidate + resolution_assertion below.
        resolved_entity_id: Optional[str] = None
        if decision.entity_type_code == "url" and decision.identifier_value and decision.link_domain_value:
            domain_entity_id = self._get_or_create_web_domain(
                normalized_domain=decision.link_domain_value, label=decision.link_domain_value,
                graph_release_id=graph_release_id)
            resolved_entity_id = self._get_or_create_web_url(
                normalized_url=decision.identifier_value, domain_entity_id=domain_entity_id,
                label=item.title_raw, graph_release_id=graph_release_id,
                shard_domain=decision.link_domain_value)
        elif decision.entity_type_code == "domain" and decision.identifier_value:
            resolved_entity_id = self._get_or_create_web_domain(
                normalized_domain=decision.identifier_value, label=item.title_raw,
                graph_release_id=graph_release_id)

        if resolved_entity_id is not None:
            self.conn.execute(
                """insert into core.resolution_candidate
                     (resolution_run_id, candidate_entity_id, candidate_rank, match_score, score_semantics)
                   values (%s,%s,1,%s,'rule_based')""",
                (run_id, resolved_entity_id, decision.confidence),
            )

        assertion_entity = resolved_entity_id if decision.resolution_state in ("resolved", "probable_match") else None
        self.conn.execute(
            """insert into core.resolution_assertion
                 (resolution_run_id, entity_graph_release_id, resolved_entity_id, resolution_state,
                  confidence_value, confidence_semantics, supporting_evidence)
               values (%s,%s,%s,%s::core.resolution_state,%s,%s,%s)""",
            (run_id, graph_release_id, assertion_entity, decision.resolution_state,
             decision.confidence, decision.method,
             Jsonb({"method": decision.method, "identifier": decision.identifier_value,
                    "domain": decision.link_domain_value})),
        )
        return {"observed_object_id": observed_object_id, "state": decision.resolution_state,
                "entity_id": assertion_entity, "method": decision.method}

    # ---- AIO (organic AI Overview) -------------------------------------
    def write_aio(self, *, observation_id: str, surface_id: str, aio: ParsedAio,
                  parser_cv: Optional[str], resolver_cv: Optional[str],
                  graph_release_id: str) -> dict[str, Any]:
        """Normalize one parsed AI Overview into aio.* + the shared entity graph.

        Always writes ``aio.observation`` (an absent AIO is written as
        ``aio_triggered=false`` — the prevalence negative, never missingness). When a
        body is present: each ``ai_overview_element`` -> ``aio.presentation_unit``;
        each website reference -> ``aio.source_occurrence`` (resolved URL-first to a
        ``core.web_url``/``web_domain``) + a ``reference_card`` citation; each inline
        answer link -> an ``inline_link`` citation (Sec.18) tied to its element and
        its source; each GBP/SearchViewer reference -> ``aio.business_appearance`` +
        ``aio.destination`` with the business resolved by Knowledge-Graph MID. The
        local-business-card MODULE stays unwritten (provider_not_observable, ADR-0008).

        Assumes it runs inside the caller's transaction. Returns a counts summary.
        """
        r = aio.serp_rectangle or {}
        self.conn.execute(
            """insert into aio.observation
                 (observation_id, aio_triggered, response_text_raw, response_markdown_raw,
                  response_metadata, aio_presentation_form, async_ai_overview_loaded,
                  serp_rank_absolute, serp_rank_group, serp_position,
                  serp_rectangle_x, serp_rectangle_y, serp_rectangle_width, serp_rectangle_height,
                  serp_preceding_block_count, serp_preceding_block_types)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (observation_id, aio.aio_triggered, aio.response_text_raw, aio.response_markdown_raw,
             Jsonb(aio.response_metadata), aio.aio_presentation_form, aio.async_ai_overview_loaded,
             aio.serp_rank_absolute, aio.serp_rank_group, aio.serp_position,
             r.get("x"), r.get("y"), r.get("width"), r.get("height"),
             aio.serp_preceding_block_count,
             Jsonb(aio.serp_preceding_block_types) if aio.serp_preceding_block_types is not None else None),
        )

        # presentation units (unit_sequence -> presentation_unit_id)
        unit_ids: dict[int, str] = {}
        for u in aio.presentation_units:
            ur = u.rectangle or {}
            pu_id = self.conn.execute(
                """insert into aio.presentation_unit
                     (observation_id, unit_sequence, unit_type, heading_raw, text_raw,
                      rectangle_x, rectangle_y, rectangle_width, rectangle_height, provider_fields)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning presentation_unit_id""",
                (observation_id, u.unit_sequence, u.unit_type, u.heading_raw, u.text_raw,
                 ur.get("x"), ur.get("y"), ur.get("width"), ur.get("height"), Jsonb(u.provider_fields)),
            ).fetchone()[0]
            unit_ids[u.unit_sequence] = pu_id

        # Ordered pre-lock of every distinct web-source domain this observation mints,
        # so parallel AIO collectors minting overlapping directory domains cannot
        # deadlock (see prelock_web_domains). No-op under a single worker.
        source_refs = [ref for ref in aio.references if not ref.is_business]
        link_domains = [normalize_domain(lk.url_raw)
                        for u in aio.presentation_units for lk in u.links]
        source_domains = [normalize_domain(ref.domain_raw) or normalize_domain(ref.url_raw)
                          for ref in source_refs]
        self.prelock_web_domains([d for d in (source_domains + link_domains) if d])

        resolutions: list[dict[str, Any]] = []
        # source_occurrence dedupe within the observation, keyed by normalized url|domain.
        source_by_key: dict[str, str] = {}
        counters = {"source": 0, "citation": 0, "obj_source": 0,
                    "business": 0, "obj_business": 0}

        def ensure_source(*, url_raw, domain_raw, title_raw, publisher, snippet, image,
                          dt, rank_abs, rank_grp, rect, provider_fields,
                          presentation_unit_id) -> str:
            key = normalize_url(url_raw) or normalize_domain(domain_raw) or normalize_domain(url_raw)
            key = key or f"__anon_{counters['source']}"
            if key in source_by_key:
                return source_by_key[key]
            counters["obj_source"] += 1
            obj_id = self.conn.execute(
                """insert into core.observed_object
                     (observation_id, surface_id, object_kind, local_sequence, raw_name, raw_url,
                      raw_domain, raw_attributes, parser_version_id)
                   values (%s,%s,'aio_source',%s,%s,%s,%s,%s,%s) returning observed_object_id""",
                (observation_id, surface_id, counters["obj_source"], publisher or title_raw,
                 url_raw, domain_raw, Jsonb(provider_fields), parser_cv),
            ).fetchone()[0]
            counters["source"] += 1
            rr = rect or {}
            so_id = self.conn.execute(
                """insert into aio.source_occurrence
                     (observation_id, presentation_unit_id, source_sequence, observed_object_id,
                      source_url_raw, source_title_raw, publisher_raw, retrieval_position,
                      source_domain_raw, source_snippet_raw, source_image_url, source_datetime_raw,
                      rank_group, rectangle_x, rectangle_y, rectangle_width, rectangle_height,
                      provider_fields)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   returning source_occurrence_id""",
                (observation_id, presentation_unit_id, counters["source"], obj_id,
                 url_raw, title_raw, publisher, rank_abs, domain_raw, snippet, image, dt,
                 rank_grp, rr.get("x"), rr.get("y"), rr.get("width"), rr.get("height"),
                 Jsonb(provider_fields)),
            ).fetchone()[0]
            source_by_key[key] = so_id
            # URL-first -> domain resolution into the canonical web graph (reuses the
            # organic resolver: an AIO source is a web destination, never a business).
            item = OrganicItem(
                result_sequence=counters["source"], rank_absolute=rank_abs, rank_group=rank_grp,
                result_type="aio_source", title_raw=title_raw, snippet_raw=snippet,
                url_raw=url_raw, domain_raw=domain_raw, page_number=None, position_on_page=None,
                is_destination=True, provider_fields=provider_fields)
            resolutions.append(self.resolve_and_assert_organic(
                observed_object_id=obj_id, item=item, resolver_cv=resolver_cv,
                graph_release_id=graph_release_id))
            return so_id

        def add_citation(*, source_occurrence_id, presentation_unit_id, citation_kind,
                         is_reference, rect, cited_span, marker) -> None:
            counters["citation"] += 1
            cr = rect or {}
            self.conn.execute(
                """insert into aio.citation
                     (observation_id, source_occurrence_id, presentation_unit_id, citation_sequence,
                      marker_raw, cited_span_raw, citation_kind, is_reference,
                      rectangle_x, rectangle_y, rectangle_width, rectangle_height)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (observation_id, source_occurrence_id, presentation_unit_id, counters["citation"],
                 marker, cited_span, citation_kind, is_reference,
                 cr.get("x"), cr.get("y"), cr.get("width"), cr.get("height")),
            )

        # website reference cards -> source_occurrence + reference_card citation (Sec.18)
        for ref in source_refs:
            so_id = ensure_source(
                url_raw=ref.url_raw, domain_raw=ref.domain_raw, title_raw=ref.title_raw,
                publisher=ref.source_raw, snippet=ref.snippet_raw, image=ref.image_url_raw,
                dt=ref.datetime_raw, rank_abs=ref.rank_absolute, rank_grp=ref.rank_group,
                rect=ref.rectangle, provider_fields=ref.provider_fields, presentation_unit_id=None)
            add_citation(source_occurrence_id=so_id, presentation_unit_id=None,
                         citation_kind="reference_card",
                         is_reference=(ref.is_reference if ref.is_reference is not None else True),
                         rect=ref.rectangle, cited_span=None, marker=ref.title_raw)

        # inline answer-text links -> inline_link citation (Sec.18), tied to its element
        for u in aio.presentation_units:
            pu_id = unit_ids.get(u.unit_sequence)
            for lk in u.links:
                so_id = ensure_source(
                    url_raw=lk.url_raw, domain_raw=None, title_raw=lk.title_raw,
                    publisher=None, snippet=None, image=None, dt=None, rank_abs=None,
                    rank_grp=None, rect=None, provider_fields={"type": "ai_overview_link",
                    "title": lk.title_raw, "url": lk.url_raw}, presentation_unit_id=pu_id)
                add_citation(source_occurrence_id=so_id, presentation_unit_id=pu_id,
                             citation_kind="inline_link", is_reference=False,
                             rect=None, cited_span=u.text_raw, marker=lk.title_raw)

        # GBP / SearchViewer references -> business_appearance + destination (KG-MID)
        business_refs = [ref for ref in aio.references if ref.is_business]
        for ref in business_refs:
            counters["obj_business"] += 1
            obj_id = self.conn.execute(
                """insert into core.observed_object
                     (observation_id, surface_id, object_kind, local_sequence, raw_name, raw_url,
                      raw_domain, raw_external_ids, raw_attributes, parser_version_id)
                   values (%s,%s,'aio_business',%s,%s,%s,%s,%s,%s,%s) returning observed_object_id""",
                (observation_id, surface_id, counters["obj_business"], ref.source_raw or ref.title_raw,
                 ref.url_raw, ref.domain_raw,
                 Jsonb({"google_kg_mid": ref.kg_mid} if ref.kg_mid else {}),
                 Jsonb(ref.provider_fields), parser_cv),
            ).fetchone()[0]
            counters["business"] += 1
            ba_id = self.conn.execute(
                """insert into aio.business_appearance
                     (observation_id, presentation_unit_id, appearance_sequence, observed_object_id,
                      appearance_type, local_business_card, embedded_gbp, selected, raw_label, provider_fields)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning business_appearance_id""",
                (observation_id, None, counters["business"], obj_id, "reference",
                 False, True, None, ref.title_raw or ref.source_raw, Jsonb(ref.provider_fields)),
            ).fetchone()[0]
            self.conn.execute(
                """insert into aio.destination
                     (business_appearance_id, destination_sequence, observed_object_id,
                      destination_url_raw, destination_type, direct_business_link, third_party_business_link)
                   values (%s,1,%s,%s,%s,%s,%s)""",
                (ba_id, obj_id, ref.url_raw, ref.destination_type, True, False),
            )
            resolutions.append(self.resolve_and_assert_aio_business(
                observed_object_id=obj_id, ref=ref, resolver_cv=resolver_cv,
                graph_release_id=graph_release_id))

        return {
            "aio_triggered": aio.aio_triggered,
            "presentation_units": len(aio.presentation_units),
            "sources": counters["source"], "citations": counters["citation"],
            "business_appearances": counters["business"],
            "resolved": sum(1 for r in resolutions if r["entity_id"]),
            "resolutions": len(resolutions),
        }

    def resolve_and_assert_aio_business(self, *, observed_object_id: str, ref, resolver_cv: str,
                                        graph_release_id: str) -> dict[str, Any]:
        """Resolve one AIO business appearance to a canonical business_location by its
        Google Knowledge-Graph MID (mirrors resolve_and_assert; place_id-graph-joinable)."""
        decision = resolve_aio_business(ref)
        run_id = self.conn.execute(
            """insert into core.resolution_run
                 (observed_object_id, entity_graph_release_id, resolver_version_id, resolver_stage)
               values (%s,%s,%s,%s) returning resolution_run_id""",
            (observed_object_id, graph_release_id, resolver_cv, decision.resolver_stage),
        ).fetchone()[0]

        resolved_entity_id: Optional[str] = None
        label = ref.source_raw or ref.title_raw
        if decision.identifier_value and decision.entity_type_code:
            existing = self._find_entity_by_identifier(
                decision.namespace, decision.identifier_type, decision.identifier_value)
            resolved_entity_id = existing or self._create_entity(decision.entity_type_code, label)
            ext_id = self._external_identifier(
                decision.namespace, decision.identifier_type, decision.identifier_value)
            if decision.resolution_state in ("resolved", "probable_match"):
                self.conn.execute(
                    """insert into core.external_identifier_assertion
                         (entity_graph_release_id, external_identifier_id, entity_id, resolution_state)
                       values (%s,%s,%s,%s::core.resolution_state)""",
                    (graph_release_id, ext_id, resolved_entity_id, decision.resolution_state),
                )
            self.conn.execute(
                """insert into core.resolution_candidate
                     (resolution_run_id, candidate_entity_id, candidate_rank, match_score, score_semantics)
                   values (%s,%s,1,%s,'rule_based')""",
                (run_id, resolved_entity_id, decision.confidence),
            )

        assertion_entity = resolved_entity_id if decision.resolution_state in ("resolved", "probable_match") else None
        self.conn.execute(
            """insert into core.resolution_assertion
                 (resolution_run_id, entity_graph_release_id, resolved_entity_id, resolution_state,
                  confidence_value, confidence_semantics, supporting_evidence)
               values (%s,%s,%s,%s::core.resolution_state,%s,%s,%s)""",
            (run_id, graph_release_id, assertion_entity, decision.resolution_state,
             decision.confidence, decision.method,
             Jsonb({"method": decision.method, "identifier": decision.identifier_value,
                    "destination_type": ref.destination_type})),
        )
        return {"observed_object_id": observed_object_id, "state": decision.resolution_state,
                "entity_id": assertion_entity, "method": decision.method}

    # ---- cost ----------------------------------------------------------
    def cost_event(self, *, provider_id: str, wave_id: str, job_id: str, attempt_id: Optional[str],
                   amount_microusd: int, purpose: str, occurred_at: datetime,
                   billed_units: Optional[float] = None, provider_reference: Optional[str] = None) -> str:
        return self.conn.execute(
            """insert into ops.cost_event
                 (provider_id, wave_id, job_id, attempt_id, purpose, billing_unit, billed_units,
                  amount_microusd, provider_reference, occurred_at)
               values (%s,%s,%s,%s,%s,'task',%s,%s,%s,%s) returning cost_event_id""",
            (provider_id, wave_id, job_id, attempt_id, purpose, billed_units, amount_microusd,
             provider_reference, occurred_at),
        ).fetchone()[0]
