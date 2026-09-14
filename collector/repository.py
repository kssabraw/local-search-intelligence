"""All database writes for the vertical slice, via psycopg.

Every write is an INSERT (the raw/observation/resolution/cost tables are
append-only; their triggers reject UPDATE/DELETE, so get-or-create uses
`ON CONFLICT DO NOTHING` + `SELECT`, never `DO UPDATE`). Entity identity lives in
the external-identifier + assertion tables (ADR-0003), not on core.entity.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from .idempotency import job_key
from .models import ManifestContext, ParsedMaps, ParsedOrganic
from .resolve import resolve_maps_item, resolve_organic_item


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
                           wave_kind: str, scheduled_for: datetime) -> str:
        self.conn.execute(
            """insert into ops.collection_wave (methodology_version_id, wave_code, wave_kind, scheduled_for)
               values (%s,%s,%s,%s) on conflict (wave_code) do nothing""",
            (methodology_version_id, wave_code, wave_kind, scheduled_for),
        )
        return self.conn.execute(
            "select wave_id from ops.collection_wave where wave_code=%s", (wave_code,)
        ).fetchone()[0]

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
                  reason_code: Optional[str] = None, actor: str = "collector.spike") -> None:
        self.conn.execute(
            """insert into ops.job_event (job_id, status, attempt_no, actor, reason_code)
               values (%s,%s::ops.job_status,%s,%s,%s)""",
            (job_id, status, attempt_no, actor, reason_code),
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

    def _get_or_create_web_domain(self, *, normalized_domain: str, label: Optional[str],
                                  graph_release_id: str) -> str:
        """Canonical web_domain entity keyed on its `web/domain` external
        identifier. On first mint the identifier binding is asserted 'resolved'
        (a normalized domain string unambiguously names its domain entity, like a
        place_id); repeat observations reuse the existing entity."""
        existing = self._find_entity_by_identifier("web", "domain", normalized_domain)
        if existing:
            return existing
        eid = self.conn.execute(
            """insert into core.entity (entity_type_code, operational_label) values ('domain',%s) returning entity_id""",
            (label,),
        ).fetchone()[0]
        self.conn.execute(
            """insert into core.web_domain (entity_id, normalized_domain, registered_domain) values (%s,%s,%s)""",
            (eid, normalized_domain, normalized_domain),
        )
        ext_id = self._external_identifier("web", "domain", normalized_domain)
        self._assert_identifier(graph_release_id=graph_release_id, external_identifier_id=ext_id,
                                entity_id=eid, resolution_state="resolved")
        return eid

    def _get_or_create_web_url(self, *, normalized_url: str, domain_entity_id: str,
                               label: Optional[str], graph_release_id: str) -> str:
        """Canonical web_url entity keyed on its `web/url` external identifier and
        linked to its web_domain. Identifier binding asserted 'resolved' on mint
        (a normalized URL definitionally names its URL entity)."""
        existing = self._find_entity_by_identifier("web", "url", normalized_url)
        if existing:
            return existing
        eid = self.conn.execute(
            """insert into core.entity (entity_type_code, operational_label) values ('url',%s) returning entity_id""",
            (label,),
        ).fetchone()[0]
        self.conn.execute(
            """insert into core.web_url (entity_id, normalized_url, domain_entity_id) values (%s,%s,%s)""",
            (eid, normalized_url, domain_entity_id),
        )
        ext_id = self._external_identifier("web", "url", normalized_url)
        self._assert_identifier(graph_release_id=graph_release_id, external_identifier_id=ext_id,
                                entity_id=eid, resolution_state="resolved")
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
                label=item.title_raw, graph_release_id=graph_release_id)
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
