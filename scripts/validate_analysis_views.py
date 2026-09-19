#!/usr/bin/env python3
"""Offline validation of the analysis layer (migrations 027 + 028) against the REAL schema.

Applies migrations 001-028 to an ephemeral pgvector Postgres, then builds a small,
fully hand-computable synthetic panel through the PRODUCTION write path
(collector.repository.Repo -> real entity resolution), and asserts every
analysis.* view returns the expected rollup. NO paid call, NO network.

Coverage:
  * norm_domain parity with collector/normalize.py
  * migration 027 is idempotent / re-run safe (re-applied twice; the Railway
    entrypoint re-runs 02[0-9]_* every deploy)
  * observation_dim, market_eligible_points
  * coverage_summary (eligible vs observed points, avg results/point)
  * maps_entity_dominance (canonical business grain, coverage_share, ranks)
  * organic_domain_dominance (result_type=organic only, normalized domain)
  * ring_profile (descriptive distance-decay)
  * maps_center_retention (set retention vs center, by ring)
  * maps_organic_overlap (Local-Pack website domains vs organic domains)
  * aio_overview_prevalence (ai_overview block present; absence = valid negative)
  * aio_organic_source_overlap (AIO sidebar sources vs co-returned organic;
    SearchViewer/GBP + inline-link sources excluded)
  * aio_prevalence_trend (028): cross-wave prevalence + wave-over-wave delta,
    cross-grid safe (delta within one geometry_code), query-family partitioned
"""
from __future__ import annotations
import pathlib, sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _localpg import LocalPG  # noqa: E402

MIG = ROOT / "supabase" / "migrations"
NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)


def _maps_item(seq, rank, place_id, name, url, rating, reviews):
    from collector.models import MapsItem
    return MapsItem(
        result_sequence=seq, rank_absolute=rank, rank_group=rank,
        provider_item_type="maps_search", title_raw=name, category_raw="Locksmith",
        rating=rating, review_count=reviews, address_raw=None, phone_raw=None,
        latitude=None, longitude=None, url_raw=url, domain_raw=None,
        place_id=place_id, cid=None, provider_fields={})


def _org_item(seq, rank, result_type, url, domain, *, is_dest):
    from collector.models import OrganicItem
    return OrganicItem(
        result_sequence=seq, rank_absolute=rank, rank_group=rank, result_type=result_type,
        title_raw=(domain or result_type), snippet_raw=None, url_raw=url, domain_raw=domain,
        page_number=1, position_on_page=seq, is_destination=is_dest, provider_fields={})


def main() -> int:  # noqa: C901 - a linear fixture builder + assertions
    import psycopg
    from collector.models import (ParsedMaps, ParsedOrganic, ParsedAio,
                                   AioReference, AioPresentationUnit, AioLink)
    from collector.repository import Repo

    pg = LocalPG()
    checks: list[tuple[str, str, str]] = []

    def check(label, got, exp):
        ok = "PASS" if got == exp else "FAIL"
        checks.append((label, f"{got!r} (exp {exp!r})", ok))

    def check_close(label, got, exp, tol=0.0005):
        ok = "PASS" if got is not None and abs(float(got) - exp) <= tol else "FAIL"
        checks.append((label, f"{got} (exp ~{exp})", ok))

    try:
        print("initdb + apply migrations 001-027 ...")
        pg.start()
        pg.apply_migrations(MIG)

        with psycopg.connect(pg.dsn(), autocommit=False) as conn:
            # --- idempotency / re-run safety of 027 (Railway re-runs 02[0-9]_*) ---
            sql027 = (MIG / "027_analysis_layer_v0_1.sql").read_text()
            conn.execute(sql027)
            conn.execute(sql027)
            conn.commit()
            nviews = conn.execute(
                "select count(*) from information_schema.views where table_schema='analysis'"
            ).fetchone()[0]
            check("027 re-run safe; analysis views present (incl. 028 trend)", nviews >= 12, True)

            # --- norm_domain parity with collector/normalize.py ---
            from collector.normalize import normalize_domain
            for raw in ["https://www.CityMD.com/urgent-care-locations", "http://Example.com/",
                        "SUB.Host.co.uk:8080/x", "user@Foo.COM", "acme.com/", "  bravo.com  ",
                        "https://www.google.com/searchviewer/10?svid=abc"]:
                sqlv = conn.execute("select analysis.norm_domain(%s)", (raw,)).fetchone()[0]
                check(f"norm_domain parity {raw!r}", sqlv, normalize_domain(raw))

            repo = Repo(conn)
            cv = repo.component_version("parser", "validate_analysis", "v0")
            rv = repo.component_version("resolver", "validate_analysis", "v0")

            def ctx(surface, industry, market, point, tset, tcode):
                return repo.load_manifest_context(
                    methodology_code="MANIFEST_V1_0", surface_code=surface,
                    industry_code=industry, market_code=market, point_code=point,
                    treatment_set_code=tset, treatment_code=tcode)

            # ============================================================
            # Maps + Organic wave (IND010 x MKT008, points C/N3/N5, query Q1)
            # ============================================================
            mv_id = ctx("maps", "IND010", "MKT008", "C", "GOOGLE_QUERY_V1", "Q1").methodology_version_id
            gr = repo.entity_graph_release("REL_VALIDATE", mv_id)
            wave_mo = repo.get_or_create_wave(
                methodology_version_id=mv_id, wave_code="WV-VALIDATE-MAPORG",
                wave_kind="full_panel", scheduled_for=NOW)

            def add_maps(point, items):
                c = ctx("maps", "IND010", "MKT008", point, "GOOGLE_QUERY_V1", "Q1")
                job_id, _, _ = repo.plan_job(ctx=c, wave_id=wave_mo, replicate_no=1,
                    rendered_input_text="locksmith near me", rendered_request={"p": point},
                    generated_by=cv)
                obs = repo.observation(job_id=job_id, accepted_attempt_id=None, state="returned",
                    observed_at=NOW, received_at=NOW, raw_payload_id=None, parser_cv=cv)
                parsed = ParsedMaps(observation_state="returned", returned_result_count=len(items),
                    provider_depth=len(items), search_metadata={}, items=items,
                    provider_cost_usd=None, provider_task_id=None)
                for obj_id, item in repo.write_maps(observation_id=obs, surface_id=c.surface_id,
                                                    parsed=parsed, parser_cv=cv):
                    repo.resolve_and_assert(observed_object_id=obj_id, item=item,
                                            resolver_cv=rv, graph_release_id=gr)
                return obs

            def add_organic(point, items, wave=None):
                c = ctx("organic", "IND010", "MKT008", point, "GOOGLE_QUERY_V1", "Q1")
                job_id, _, _ = repo.plan_job(ctx=c, wave_id=(wave or wave_mo), replicate_no=1,
                    rendered_input_text="locksmith near me", rendered_request={"p": point},
                    generated_by=cv)
                obs = repo.observation(job_id=job_id, accepted_attempt_id=None, state="returned",
                    observed_at=NOW, received_at=NOW, raw_payload_id=None, parser_cv=cv)
                n_org = sum(1 for it in items if it.result_type == "organic")
                parsed = ParsedOrganic(observation_state="returned", returned_result_count=n_org,
                    provider_depth=len(items), serp_metadata={}, items=items,
                    provider_cost_usd=None, provider_task_id=None)
                for obj_id, item in repo.write_organic(observation_id=obs, surface_id=c.surface_id,
                                                       parsed=parsed, parser_cv=cv):
                    repo.resolve_and_assert_organic(observed_object_id=obj_id, item=item,
                                                    resolver_cv=rv, graph_release_id=gr)
                return obs

            # Maps businesses per point (place_id -> canonical business; url = GBP website)
            add_maps("C", [
                _maps_item(1, 1, "placeA", "Acme Lock", "https://acme.com/", 4.8, 200),
                _maps_item(2, 2, "placeB", "Bravo Lock", "https://www.bravo.com/", 4.5, 100),
                _maps_item(3, 3, "placeC", "Charlie Lock", "http://charlie.com", 4.0, 50)])
            add_maps("N3", [
                _maps_item(1, 1, "placeA", "Acme Lock", "https://acme.com/", 4.8, 200),
                _maps_item(2, 2, "placeB", "Bravo Lock", "https://www.bravo.com/", 4.5, 100),
                _maps_item(3, 3, "placeD", "Delta Lock", "https://delta.com/", 4.2, 70)])
            add_maps("N5", [
                _maps_item(1, 2, "placeA", "Acme Lock", "https://acme.com/", 4.8, 200),
                _maps_item(2, 5, "placeE", "Echo Lock", "https://echo.com/", 3.9, 30)])

            # Organic blocks per point (organic + a local_pack + an ai_overview at C only)
            add_organic("C", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True),
                _org_item(2, 2, "organic", "https://zeta.com/a", "zeta.com", is_dest=True),
                _org_item(3, 3, "organic", "https://www.bravo.com/b", "bravo.com", is_dest=True),
                _org_item(4, 4, "local_pack", None, None, is_dest=False),
                _org_item(5, 5, "ai_overview", None, None, is_dest=False)])
            add_organic("N3", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True),
                _org_item(2, 2, "organic", "https://yankee.com/y", "yankee.com", is_dest=True)])
            add_organic("N5", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True)])

            conn.commit()

            # ============================================================
            # A SECOND Maps+Organic wave (same grid + same Q1 query family),
            # scheduled one month later, with a HIGHER AIO-block presence rate
            # (2/3 vs 1/3). Exercises the cross-wave trend (delta) view.
            # ============================================================
            wave_mo2 = repo.get_or_create_wave(
                methodology_version_id=mv_id, wave_code="WV-VALIDATE-MAPORG2",
                wave_kind="full_panel",
                scheduled_for=datetime(2026, 10, 18, tzinfo=timezone.utc))
            add_organic("C", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True),
                _org_item(2, 2, "organic", "https://zeta.com/a", "zeta.com", is_dest=True),
                _org_item(3, 3, "ai_overview", None, None, is_dest=False)], wave=wave_mo2)
            add_organic("N3", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True),
                _org_item(2, 2, "ai_overview", None, None, is_dest=False)], wave=wave_mo2)
            add_organic("N5", [
                _org_item(1, 1, "organic", "https://acme.com/loc", "acme.com", is_dest=True)],
                wave=wave_mo2)
            conn.commit()

            # ============================================================
            # AIO wave (IND019 x MKT008, center; AIO_C01 triggered, AIO_C02 absent)
            # ============================================================
            wave_aio = repo.get_or_create_wave(
                methodology_version_id=mv_id, wave_code="WV-VALIDATE-AIO",
                wave_kind="ad_hoc", scheduled_for=NOW)

            def add_aio(tcode, *, triggered, aio_sources, business_refs, inline_links,
                        organic_blocks):
                c = ctx("aio", "IND019", "MKT008", "C", "AIO_QUERY_V1", tcode)
                job_id, _, _ = repo.plan_job(ctx=c, wave_id=wave_aio, replicate_no=1,
                    rendered_input_text="urgent care near me", rendered_request={"t": tcode},
                    generated_by=cv)
                obs = repo.observation(job_id=job_id, accepted_attempt_id=None, state="returned",
                    observed_at=NOW, received_at=NOW, raw_payload_id=None, parser_cv=cv)
                # co-returned organic context (write_organic under the same observation)
                n_org = sum(1 for it in organic_blocks if it.result_type == "organic")
                po = ParsedOrganic(observation_state="returned", returned_result_count=n_org,
                    provider_depth=len(organic_blocks), serp_metadata={}, items=organic_blocks,
                    provider_cost_usd=None, provider_task_id=None)
                for obj_id, item in repo.write_organic(observation_id=obs, surface_id=c.surface_id,
                                                       parsed=po, parser_cv=cv):
                    repo.resolve_and_assert_organic(observed_object_id=obj_id, item=item,
                                                    resolver_cv=rv, graph_release_id=gr)
                # AIO subtree
                units = [AioPresentationUnit(unit_sequence=1, unit_type="ai_overview_element",
                    heading_raw=None, text_raw="Answer body.", rectangle=None,
                    links=inline_links, provider_fields={})] if triggered else []
                aio = ParsedAio(
                    observation_state="returned", aio_triggered=triggered,
                    aio_presentation_form=("standalone" if triggered else "absent"),
                    async_ai_overview_loaded=triggered, response_text_raw=None,
                    response_markdown_raw=None, serp_rank_absolute=(1 if triggered else None),
                    serp_rank_group=None, serp_position=("left" if triggered else None),
                    serp_rectangle=None, serp_preceding_block_count=(0 if triggered else None),
                    serp_preceding_block_types=None, presentation_units=units,
                    references=(aio_sources + business_refs), response_metadata={},
                    provider_cost_usd=None, provider_task_id=None)
                repo.write_aio(observation_id=obs, surface_id=c.surface_id, aio=aio,
                               parser_cv=cv, resolver_cv=rv, graph_release_id=gr)
                return obs

            def src(seq, domain, url):
                return AioReference(ref_sequence=seq, source_raw=domain, domain_raw=domain,
                    url_raw=url, title_raw=domain, snippet_raw=None, image_url_raw=None,
                    datetime_raw=None, rank_absolute=seq, rank_group=seq, is_reference=True,
                    rectangle=None, destination_type="website", is_business=False, kg_mid=None,
                    provider_fields={})

            def biz(seq, kg_mid, url):
                return AioReference(ref_sequence=seq, source_raw="A Clinic", domain_raw=None,
                    url_raw=url, title_raw="A Clinic", snippet_raw=None, image_url_raw=None,
                    datetime_raw=None, rank_absolute=seq, rank_group=seq, is_reference=False,
                    rectangle=None, destination_type="gbp", is_business=True, kg_mid=kg_mid,
                    provider_fields={})

            # Obs1 triggered: sources citymd/mountsinai/thumbtack; +1 GBP business ref;
            # +1 inline SearchViewer link (both must be EXCLUDED from source overlap).
            add_aio("AIO_C01", triggered=True,
                aio_sources=[src(1, "www.citymd.com", "https://www.citymd.com/x"),
                             src(2, "mountsinai.org", "https://mountsinai.org/y"),
                             src(3, "www.thumbtack.com", "https://www.thumbtack.com/z")],
                business_refs=[biz(4, "/g/abc123", "https://www.google.com/searchviewer/10?svid=z")],
                inline_links=[AioLink(unit_sequence=1, title_raw="viewer",
                    url_raw="https://www.google.com/searchviewer/10?svid=q")],
                organic_blocks=[
                    _org_item(1, 1, "organic", "https://www.citymd.com/x", "citymd.com", is_dest=True),
                    _org_item(2, 2, "organic", "https://mountsinai.org/y", "mountsinai.org", is_dest=True),
                    _org_item(3, 3, "organic", "https://webmd.com/w", "webmd.com", is_dest=True),
                    _org_item(4, 4, "ai_overview", None, None, is_dest=False)])
            # Obs2 absent AIO: valid negative; organic present, no ai_overview block.
            add_aio("AIO_C02", triggered=False, aio_sources=[], business_refs=[], inline_links=[],
                organic_blocks=[
                    _org_item(1, 1, "organic", "https://webmd.com/w", "webmd.com", is_dest=True)])
            conn.commit()

            def rows(sql, params=None):
                return conn.execute(sql, params or {}).fetchall()

            # ---------- observation_dim + market_eligible_points ----------
            check("observation_dim maps/organic obs",
                  conn.execute("select count(*) from analysis.observation_dim where wave_code=%s",
                               ("WV-VALIDATE-MAPORG",)).fetchone()[0], 6)  # 3 pts x 2 surfaces
            check("market_eligible_points = 3 (C/N3/N5)",
                  conn.execute("""select eligible_points from analysis.market_eligible_points
                                  where wave_code=%s""", ("WV-VALIDATE-MAPORG",)).fetchone()[0], 3)
            check("observation_dim ring for N5 = 5",
                  conn.execute("""select distinct ring_miles from analysis.observation_dim
                                  where wave_code=%s and point_code='N5'""",
                               ("WV-VALIDATE-MAPORG",)).fetchone()[0], 5)

            # ---------- coverage_summary ----------
            cov = {r[0]: r for r in rows(
                """select surface_code, eligible_points, observed_points, coverage_rate,
                          avg_results_per_point
                   from analysis.coverage_summary where wave_code=%(w)s""",
                {"w": "WV-VALIDATE-MAPORG"})}
            check("coverage maps eligible/observed", (cov["maps"][1], cov["maps"][2]), (3, 3))
            check("coverage maps rate = 1.0", float(cov["maps"][3]), 1.0)
            check_close("coverage maps avg results/pt (3,3,2)->2.667", cov["maps"][4], 2.667)
            check_close("coverage organic avg results/pt (3,2,1)->2.0", cov["organic"][4], 2.0)

            # ---------- maps_entity_dominance ----------
            dom = {r[0]: r for r in rows(
                """select business_name, appearances, distinct_points, coverage_share, best_rank
                   from analysis.maps_entity_dominance where wave_code=%(w)s""",
                {"w": "WV-VALIDATE-MAPORG"})}
            check("dominance Acme: appears 3, pts 3", (dom["Acme Lock"][1], dom["Acme Lock"][2]), (3, 3))
            check("dominance Acme coverage_share 1.0", float(dom["Acme Lock"][3]), 1.0)
            check("dominance Acme best_rank 1", dom["Acme Lock"][4], 1)
            check("dominance Bravo pts 2", dom["Bravo Lock"][2], 2)
            check_close("dominance Bravo coverage_share 2/3", dom["Bravo Lock"][3], 0.6667)
            check("dominance Charlie pts 1", dom["Charlie Lock"][2], 1)
            check("dominance entity count = 5", len(dom), 5)

            # ---------- organic_domain_dominance ----------
            odom = {r[0]: r for r in rows(
                """select domain, distinct_points, coverage_share from analysis.organic_domain_dominance
                   where wave_code=%(w)s""", {"w": "WV-VALIDATE-MAPORG"})}
            check("organic dominance acme pts 3", odom["acme.com"][1], 3)
            check("organic dominance domains = {acme,zeta,bravo,yankee}", sorted(odom.keys()),
                  ["acme.com", "bravo.com", "yankee.com", "zeta.com"])
            check("organic dominance excludes local_pack/ai_overview (no null domain)",
                  all(k for k in odom.keys()), True)

            # ---------- ring_profile ----------
            rp = {(r[0], r[1]): r for r in rows(
                """select surface_code, ring_miles, avg_results_per_point
                   from analysis.ring_profile where wave_code=%(w)s""",
                {"w": "WV-VALIDATE-MAPORG"})}
            check_close("ring_profile maps ring0 results=3", rp[("maps", 0)][2], 3.0)
            check_close("ring_profile maps ring5 results=2", rp[("maps", 5)][2], 2.0)
            check_close("ring_profile organic ring3 results=2", rp[("organic", 3)][2], 2.0)

            # ---------- maps_center_retention ----------
            cr = {r[0]: r for r in rows(
                """select ring_miles, avg_center_retention, avg_center_entities
                   from analysis.maps_center_retention where wave_code=%(w)s""",
                {"w": "WV-VALIDATE-MAPORG"})}
            check("center_retention rings = {3,5}", sorted(cr.keys()), [3, 5])
            check_close("center_retention ring3 = 2/3 (A,B of A,B,C)", cr[3][1], 0.6667)
            check_close("center_retention ring5 = 1/3 (A of A,B,C)", cr[5][1], 0.3333)
            check_close("center_retention center size = 3", cr[3][2], 3.0)

            # ---------- maps_organic_overlap ----------
            mo = {}
            for r in rows("""select point_code, mor.maps_domains, mor.organic_domains, mor.overlap_domains,
                                    mor.overlap_share_of_maps
                             from analysis.maps_organic_overlap mor
                             join analysis.observation_dim od
                               on od.wave_code=mor.wave_code and od.coordinate_id=mor.coordinate_id
                              and od.surface_code='maps'
                             where mor.wave_code=%(w)s
                             group by point_code, mor.maps_domains, mor.organic_domains,
                                      mor.overlap_domains, mor.overlap_share_of_maps""",
                          {"w": "WV-VALIDATE-MAPORG"}):
                mo[r[0]] = r
            check("overlap C maps/organic/overlap = 3/3/2", (mo["C"][1], mo["C"][2], mo["C"][3]), (3, 3, 2))
            check_close("overlap C share_of_maps 2/3", mo["C"][4], 0.6667)
            check("overlap N3 overlap = 1 (acme)", mo["N3"][3], 1)
            check("overlap N5 maps/organic/overlap = 2/1/1", (mo["N5"][1], mo["N5"][2], mo["N5"][3]), (2, 1, 1))

            # ---------- aio_overview_prevalence ----------
            prev = conn.execute(
                """select sum(observations), sum(aio_present_observations)
                   from analysis.aio_overview_prevalence where wave_code=%s""",
                ("WV-VALIDATE-AIO",)).fetchone()
            check("aio prevalence obs/present = 2/1", (prev[0], prev[1]), (2, 1))

            # ---------- aio_organic_source_overlap ----------
            ov = {r[0]: r for r in rows(
                """select treatment_code, aio_triggered, aio_source_domains, organic_domains,
                          overlap_domains, share_of_aio_sources_in_organic
                   from analysis.aio_organic_source_overlap where wave_code=%(w)s""",
                {"w": "WV-VALIDATE-AIO"})}
            check("aio_overlap C01 triggered", ov["AIO_C01"][1], True)
            check("aio_overlap C01 source domains = 3 (SearchViewer+inline excluded)",
                  ov["AIO_C01"][2], 3)
            check("aio_overlap C01 organic domains = 3", ov["AIO_C01"][3], 3)
            check("aio_overlap C01 overlap = 2 (citymd,mountsinai)", ov["AIO_C01"][4], 2)
            check_close("aio_overlap C01 share 2/3", ov["AIO_C01"][5], 0.6667)
            check("aio_overlap C02 not triggered, 0 sources", (ov["AIO_C02"][1], ov["AIO_C02"][2]),
                  (False, 0))

            # ---------- aio_prevalence_trend (migration 028) ----------
            # Per-query-family rows for the two Maps+Organic waves (both Q1 family,
            # same GEOGRID13E grid). Wave1 = 1/3 AIO-present, wave2 = 2/3 -> delta +1/3.
            tr = {r[0]: r for r in rows(
                """select wave_code, observations, aio_present_observations, aio_prevalence,
                          prev_wave_prevalence, prevalence_delta, wave_ordinal,
                          all_query_families, geometry_code
                   from analysis.aio_prevalence_trend
                   where wave_code in ('WV-VALIDATE-MAPORG','WV-VALIDATE-MAPORG2')
                     and all_query_families = false""")}
            check("trend wave1 obs/present = 3/1",
                  (tr["WV-VALIDATE-MAPORG"][1], tr["WV-VALIDATE-MAPORG"][2]), (3, 1))
            check_close("trend wave1 prevalence 1/3", tr["WV-VALIDATE-MAPORG"][3], 0.3333)
            check("trend wave1 is first: ordinal 1, no prior delta",
                  (tr["WV-VALIDATE-MAPORG"][6], tr["WV-VALIDATE-MAPORG"][4],
                   tr["WV-VALIDATE-MAPORG"][5]), (1, None, None))
            check("trend wave2 obs/present = 3/2",
                  (tr["WV-VALIDATE-MAPORG2"][1], tr["WV-VALIDATE-MAPORG2"][2]), (3, 2))
            check_close("trend wave2 prevalence 2/3", tr["WV-VALIDATE-MAPORG2"][3], 0.6667)
            check_close("trend wave2 prev = wave1 prevalence 1/3",
                        tr["WV-VALIDATE-MAPORG2"][4], 0.3333)
            check_close("trend wave2 delta = +1/3", tr["WV-VALIDATE-MAPORG2"][5], 0.3333)
            check("trend wave2 ordinal 2 (chronological)", tr["WV-VALIDATE-MAPORG2"][6], 2)
            check("trend delta computed within one grid (geometry_code equal)",
                  tr["WV-VALIDATE-MAPORG"][8] == tr["WV-VALIDATE-MAPORG2"][8]
                  and tr["WV-VALIDATE-MAPORG"][8] is not None, True)

            # Overall family-rollup row per wave (query_family NULL): whole-wave prevalence.
            tr_all = {r[0]: r for r in rows(
                """select wave_code, query_family, observations, aio_prevalence
                   from analysis.aio_prevalence_trend
                   where wave_code = 'WV-VALIDATE-MAPORG2' and all_query_families = true""")}
            check("trend rollup row: query_family NULL, obs 3",
                  (tr_all["WV-VALIDATE-MAPORG2"][1], tr_all["WV-VALIDATE-MAPORG2"][2]), (None, 3))

            # Family-partition isolation: the AIO wave (distinct query families) does
            # NOT join the Maps/Organic Q1 family series -- each AIO family is first
            # in its own partition (ordinal 1, NULL delta), so the Q1 deltas above are
            # not contaminated by the same-day AIO wave.
            aio_tr = rows(
                """select wave_ordinal, prevalence_delta
                   from analysis.aio_prevalence_trend
                   where wave_code = 'WV-VALIDATE-AIO' and all_query_families = false""")
            check("trend AIO-wave families isolated (all ordinal 1, NULL delta)",
                  all(r[0] == 1 and r[1] is None for r in aio_tr) and len(aio_tr) >= 1, True)

            conn.rollback()  # read-only session; nothing to persist
    finally:
        pg.stop()

    width = max(len(c[0]) for c in checks)
    print("\n=== analysis-layer validation ===")
    for label, detail, status in checks:
        print(f"[{status}] {label.ljust(width)}  {detail}")
    failed = [c for c in checks if c[2] == "FAIL"]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    if failed:
        print("FAILURES:")
        for label, detail, _ in failed:
            print(f"  - {label}: {detail}")
        return 1
    print("ALL PASS (no paid call, no network)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
