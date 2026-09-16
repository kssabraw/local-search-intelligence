#!/usr/bin/env python3
"""End-to-end OFFLINE validation of the AIO (organic AI Overview) normalizer (ADR-0008).

Applies migrations 001-026 to an ephemeral pgvector Postgres, then drives
``collector.spike.run_spike`` for the ``aio`` surface over three synthetic organic
SERP responses with a FAKE DataForSEO provider and an in-memory raw store. NO paid
call, NO network.

Asserts the two-track normalizer lands correctly:
  * a LOADED standalone AIO (+ local_pack + organic): aio.observation prevalence +
    SERP placement (top), presentation units + rectangles, sidebar source cards
    (URL-first resolution) + inline-vs-reference citations (Sec.18), a SearchViewer
    business appearance + destination resolved by Knowledge-Graph MID, AND the
    co-returned organic context (H3) under the SAME observation, with a clean
    entity graph (the website cited both as a reference AND an organic result +
    inline link dedupes to ONE canonical web_url);
  * an ASYNC STUB: aio_triggered true, form 'async_stub', not loaded, placement in
    the middle (preceded by local_pack), no body rows, organic context still lands;
  * NO AIO: aio_triggered=false (a VALID prevalence negative, never
    provider_not_observable), form 'absent', organic context still lands;
  * idempotent resume re-collects nothing / re-pays nothing.
"""
from __future__ import annotations
import copy
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
LOADED = FIX / "aio_overview_organic_loaded.json"
STUB = FIX / "aio_overview_organic_async_stub.json"
NO_AIO = FIX / "organic_no_aio.json"


class FakeAioProvider:
    """task_post -> task_get_advanced returning the given fixture with a unique task
    id + the job's keyword (so each job's raw bytes are distinct)."""

    def __init__(self, base: dict):
        self._base = base
        self._tid = None
        self._kw = None

    def task_post(self, payload):
        self._kw = payload["keyword"]
        self._tid = "aio-" + hashlib.sha256(self._kw.encode()).hexdigest()[:12]
        post = {"status_code": 20000, "tasks": [{"id": self._tid, "status_code": 20100}]}
        return post, json.dumps(post).encode(), self._tid

    def task_get_advanced(self, task_id):
        assert task_id == self._tid
        resp = copy.deepcopy(self._base)
        resp["tasks"][0]["id"] = task_id
        if resp["tasks"][0].get("result"):
            resp["tasks"][0]["result"][0]["keyword"] = self._kw
        return resp, json.dumps(resp, sort_keys=True).encode()


def main() -> int:
    import psycopg
    from collector.raw_store import InMemoryRawStore
    from collector.repository import Repo
    from collector.spike import run_spike

    pg = LocalPG()
    checks = []

    def check(label, got, exp):
        checks.append((label, f"{got} (exp {exp})", "PASS" if got == exp else "FAIL"))

    try:
        print("initdb + apply migrations ...")
        pg.start()
        pg.apply_migrations(ROOT / "supabase" / "migrations")
        store = InMemoryRawStore()

        with psycopg.connect(pg.dsn()) as conn:
            repo = Repo(conn)

            def scalar(sql, *p):
                return conn.execute(sql, p).fetchone()[0]

            def aio_ctx(treatment):
                return repo.load_manifest_context(
                    methodology_code="MANIFEST_V1_0", surface_code="aio",
                    industry_code="IND010", market_code="MKT008", point_code="C",
                    treatment_set_code="AIO_QUERY_V1", treatment_code=treatment)

            # ---- Case 1: LOADED standalone AIO + organic context (AIO_C01) ----
            ctx1 = aio_ctx("AIO_C01")
            check("aio coordinate eligible_land", ctx1.eligibility, "eligible_land")
            check("aio surface uses DFS_AIO_V2", ctx1.post_endpoint, "/v3/serp/google/organic/task_post")
            r1 = run_spike(conn, ctx=ctx1, provider=FakeAioProvider(json.loads(LOADED.read_text())),
                           raw_store=store, wave_code="AIO-NORM-LOADED")
            conn.commit()
            print("loaded:", json.dumps(r1, default=str))
            check("loaded status", r1["status"], "collected")
            check("loaded observation returned", r1["observation_state"], "returned")
            check("loaded aio_triggered", r1["aio_triggered"], True)
            check("loaded presentation form standalone", r1["aio_presentation_form"], "standalone")
            check("loaded async body loaded", r1["async_ai_overview_loaded"], True)

            check("1 ops.observation", scalar("select count(*) from ops.observation"), 1)
            check("1 aio.observation", scalar("select count(*) from aio.observation"), 1)
            check("aio_triggered true in db", scalar("select aio_triggered from aio.observation"), True)
            check("presentation form", scalar("select aio_presentation_form from aio.observation"), "standalone")
            check("async_ai_overview_loaded", scalar("select async_ai_overview_loaded from aio.observation"), True)
            # SERP placement: block rank 1, left, top of page (0 preceding blocks)
            check("serp_rank_absolute 1", scalar("select serp_rank_absolute from aio.observation"), 1)
            check("serp_position left", scalar("select serp_position from aio.observation"), "left")
            check("serp_preceding_block_count 0 (top)",
                  scalar("select serp_preceding_block_count from aio.observation"), 0)
            check("serp_rectangle captured (width 652)",
                  scalar("select serp_rectangle_width from aio.observation"), 652)

            check("2 presentation units", scalar("select count(*) from aio.presentation_unit"), 2)
            check("presentation unit rectangles captured",
                  scalar("select count(*) from aio.presentation_unit where rectangle_width is not null"), 2)

            # sidebar website source (consumer-guides) is ALSO the inline-link target ->
            # dedupes to ONE source_occurrence carrying two citations (Sec.18).
            check("1 source_occurrence (website, deduped)",
                  scalar("select count(*) from aio.source_occurrence"), 1)
            check("source snippet + image + datetime captured",
                  scalar("select count(*) from aio.source_occurrence where source_snippet_raw is not null "
                         "and source_image_url is not null and source_datetime_raw is not null"), 1)
            check("2 citations", scalar("select count(*) from aio.citation"), 2)
            check("1 reference_card citation",
                  scalar("select count(*) from aio.citation where citation_kind='reference_card'"), 1)
            check("1 inline_link citation",
                  scalar("select count(*) from aio.citation where citation_kind='inline_link'"), 1)
            check("reference_card is_reference true",
                  scalar("select is_reference from aio.citation where citation_kind='reference_card'"), True)
            check("inline_link is_reference false",
                  scalar("select is_reference from aio.citation where citation_kind='inline_link'"), False)
            check("inline_link tied to a presentation unit",
                  scalar("select count(*) from aio.citation where citation_kind='inline_link' "
                         "and presentation_unit_id is not null"), 1)

            # SearchViewer business appearance + destination resolved by KG-MID
            check("1 business_appearance", scalar("select count(*) from aio.business_appearance"), 1)
            check("business is embedded_gbp, not a local card",
                  scalar("select count(*) from aio.business_appearance where embedded_gbp and not local_business_card"), 1)
            check("1 destination", scalar("select count(*) from aio.destination"), 1)
            check("destination_type searchviewer",
                  scalar("select destination_type from aio.destination"), "google_searchviewer")
            check("KG-MID external identifier minted",
                  scalar("select count(*) from core.external_identifier where identifier_type='google_kg_mid'"), 1)
            check("KG-MID value decoded",
                  scalar("select identifier_value from core.external_identifier where identifier_type='google_kg_mid'"),
                  "/g/1q62g1d9q")
            check("AIO business -> business_location entity",
                  scalar("select count(*) from core.entity where entity_type_code='business_location'"), 1)

            # observed objects: 2 organic destinations + 1 aio_source + 1 aio_business
            check("aio_source observed_object", scalar(
                "select count(*) from core.observed_object where object_kind='aio_source'"), 1)
            check("aio_business observed_object", scalar(
                "select count(*) from core.observed_object where object_kind='aio_business'"), 1)
            check("organic_result observed_objects (co-returned context)", scalar(
                "select count(*) from core.observed_object where object_kind='organic_result'"), 2)

            # entity-graph cleanliness: the consumer-guides page is cited (AIO source +
            # inline link) AND an organic result -> ONE canonical web_url, no split.
            check("web_url entities (consumer-guides + directory, deduped)",
                  scalar("select count(*) from core.web_url"), 2)
            check("web_domain entities", scalar("select count(*) from core.web_domain"), 2)
            check("0 duplicate normalized_url", scalar(
                "select count(*) from (select normalized_url from core.web_url group by 1 having count(*)>1) t"), 0)
            check("0 duplicate normalized_domain", scalar(
                "select count(*) from (select normalized_domain from core.web_domain group by 1 having count(*)>1) t"), 0)

            # co-returned organic context landed under the SAME observation (H3 join)
            check("1 organic.observation (same obs)", scalar("select count(*) from organic.observation"), 1)
            check("organic.result rows (all 5 SERP blocks)", scalar("select count(*) from organic.result"), 5)
            check("aio + organic share one ops.observation", scalar(
                "select count(*) from aio.observation a join organic.observation o "
                "on a.observation_id=o.observation_id"), 1)
            check("1 cost_event", scalar("select count(*) from ops.cost_event"), 1)

            # idempotent resume
            r1b = run_spike(conn, ctx=ctx1, provider=FakeAioProvider(json.loads(LOADED.read_text())),
                            raw_store=store, wave_code="AIO-NORM-LOADED")
            conn.commit()
            check("resume idempotent", r1b["status"], "already_observed")
            check("still 1 aio.observation", scalar("select count(*) from aio.observation"), 1)
            check("still 1 cost_event", scalar("select count(*) from ops.cost_event"), 1)

            # ---- Case 2: ASYNC STUB (AIO_C02) ----
            ctx2 = aio_ctx("AIO_C02")
            r2 = run_spike(conn, ctx=ctx2, provider=FakeAioProvider(json.loads(STUB.read_text())),
                           raw_store=store, wave_code="AIO-NORM-STUB")
            conn.commit()
            print("stub:", json.dumps(r2, default=str))
            check("stub aio_triggered", r2["aio_triggered"], True)
            check("stub form async_stub", r2["aio_presentation_form"], "async_stub")
            check("stub not loaded", r2["async_ai_overview_loaded"], False)
            check("stub aio.observation form", scalar(
                "select aio_presentation_form from aio.observation a join ops.observation o "
                "on o.observation_id=a.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-STUB'"),
                  "async_stub")
            check("stub placement middle (preceded by local_pack)", scalar(
                "select serp_preceding_block_count from aio.observation a join ops.observation o "
                "on o.observation_id=a.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-STUB'"), 1)
            check("stub: no body rows (units)", scalar(
                "select count(*) from aio.presentation_unit pu join ops.observation o "
                "on o.observation_id=pu.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-STUB'"), 0)
            check("stub: organic context still lands", scalar(
                "select count(*) from organic.observation o2 join ops.observation o "
                "on o.observation_id=o2.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-STUB'"), 1)

            # ---- Case 3: NO AIO -> valid prevalence negative (AIO_C04) ----
            ctx3 = aio_ctx("AIO_C04")
            r3 = run_spike(conn, ctx=ctx3, provider=FakeAioProvider(json.loads(NO_AIO.read_text())),
                           raw_store=store, wave_code="AIO-NORM-NONE")
            conn.commit()
            print("no-aio:", json.dumps(r3, default=str))
            check("no-aio observation returned (NOT missingness)", r3["observation_state"], "returned")
            check("no-aio aio_triggered false (valid negative)", r3["aio_triggered"], False)
            check("no-aio form absent", r3["aio_presentation_form"], "absent")
            check("no-aio aio.observation written with triggered=false", scalar(
                "select aio_triggered from aio.observation a join ops.observation o "
                "on o.observation_id=a.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-NONE'"), False)
            check("no-aio: no aio.* body rows", scalar(
                "select (select count(*) from aio.source_occurrence so join ops.observation o "
                " on o.observation_id=so.observation_id join ops.collection_job j on j.job_id=o.job_id "
                " join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-NONE')"), 0)
            check("no-aio: organic context still lands", scalar(
                "select count(*) from organic.observation o2 join ops.observation o "
                "on o.observation_id=o2.observation_id join ops.collection_job j on j.job_id=o.job_id "
                "join ops.collection_wave w on w.wave_id=j.wave_id where w.wave_code='AIO-NORM-NONE'"), 1)

            check("3 aio.observation total (1 per obs incl. negative)",
                  scalar("select count(*) from aio.observation"), 3)

        print(f"\n{'check':<52} {'result':<26} status")
        print("-" * 90)
        failed = 0
        for label, resl, status in checks:
            failed += status == "FAIL"
            print(f"{label:<52} {resl:<26} {status}")
        print("\nRESULT:", "ALL PASS" if not failed else f"{failed} FAILED")
        return 1 if failed else 0
    finally:
        pg.stop()


if __name__ == "__main__":
    sys.exit(main())
