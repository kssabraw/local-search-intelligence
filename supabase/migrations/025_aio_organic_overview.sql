-- Migration 025_aio_organic_overview
-- SED Local Search Intelligence Platform -- Stage-2 (AIO) methodology amendment
--
-- ADR-0008: the AIO surface of record is the AI Overview embedded in the ORGANIC
-- Google SERP (not AI Mode). This migration (1) reconciles the aio.* schema to the
-- fields the ADR-0005 probes proved the provider returns -- sidebar source cards,
-- inline-vs-reference citations, element + block rectangles, SERP placement, KG-MID
-- destinations -- and (2) repoints the AIO provider profile from DFS_AIO_V1 (the
-- ai_mode endpoint) to a new versioned DFS_AIO_V2 (the organic ai_overview capture:
-- organic endpoint + load_async_ai_overview + calculate_rectangles). DFS_AIO_V1 is
-- retained as history. Universe/geometry (AIO9_V1, 9 points) and the 10 AIO
-- conditions are UNCHANGED; only the AIO provider profile is versioned.
--
-- NOTE: core.external_identifier.identifier_type is free text, so the new
-- 'google_kg_mid' identifier value needs no DDL. All ALTERs are ADD COLUMN IF NOT
-- EXISTS and all seeds are ON CONFLICT DO NOTHING / idempotent UPDATEs, so this file
-- is safe to re-apply (the Railway entrypoint re-runs 019+ every deploy).

-- ============================================================================
-- 1) aio.* schema reconciliation (additive)
-- ============================================================================

-- aio.observation: prevalence + presentation form + SERP placement of the AIO block.
-- (aio_triggered already exists -- the prevalence signal; false is a valid negative.)
alter table aio.observation
  add column if not exists aio_presentation_form text,        -- 'standalone' | 'async_stub' | 'absent'
  add column if not exists async_ai_overview_loaded boolean,
  add column if not exists serp_rank_absolute integer,        -- AIO block position among ALL SERP items (1 = top)
  add column if not exists serp_rank_group integer,
  add column if not exists serp_position text,                -- 'left' | 'right'
  add column if not exists serp_rectangle_x integer,
  add column if not exists serp_rectangle_y integer,
  add column if not exists serp_rectangle_width integer,
  add column if not exists serp_rectangle_height integer,
  add column if not exists serp_preceding_block_count integer,     -- 0 = top of page
  add column if not exists serp_preceding_block_types jsonb;       -- ordered item-types before the AIO block

-- aio.presentation_unit: element pixel geometry.
alter table aio.presentation_unit
  add column if not exists rectangle_x integer,
  add column if not exists rectangle_y integer,
  add column if not exists rectangle_width integer,
  add column if not exists rectangle_height integer;

-- aio.source_occurrence: the sidebar source cards (publisher/domain/snippet/thumbnail/date/order/placement).
alter table aio.source_occurrence
  add column if not exists source_domain_raw text,
  add column if not exists source_snippet_raw text,
  add column if not exists source_image_url text,
  add column if not exists source_datetime_raw text,
  add column if not exists rank_group integer,
  add column if not exists rectangle_x integer,
  add column if not exists rectangle_y integer,
  add column if not exists rectangle_width integer,
  add column if not exists rectangle_height integer;

-- aio.citation: distinguish an inline clickable link from a sidebar reference (AIO PRD Sec.18).
alter table aio.citation
  add column if not exists citation_kind text,        -- 'inline_link' | 'reference_card'
  add column if not exists is_reference boolean,
  add column if not exists rectangle_x integer,
  add column if not exists rectangle_y integer,
  add column if not exists rectangle_width integer,
  add column if not exists rectangle_height integer;

-- ============================================================================
-- 2) DFS_AIO_V2 provider profile (organic ai_overview capture) + repoint
-- ============================================================================

-- New AIO provider profile: the organic endpoint with load_async_ai_overview +
-- calculate_rectangles, tied to the aio surface. DFS_AIO_V1 (ai_mode) kept as history.
insert into manifest.provider_profile
  (methodology_version_id, surface_id, provider_id, profile_code, method, post_endpoint,
   get_endpoint, language_code, device, operating_system, location_mode, location_template,
   result_depth, priority, max_tasks_per_post, settings, settings_sha256)
select pp.methodology_version_id, pp.surface_id, pp.provider_id, 'DFS_AIO_V2', 'standard_async',
       '/v3/serp/google/organic/task_post', '/v3/serp/google/organic/task_get/advanced/{id}',
       'en', 'desktop', 'windows', 'location_coordinate', '{lat},{lon},200',
       10, 1, 100,
       '{"calculate_rectangles": true, "depth": 10, "device": "desktop", "get_endpoint": "/v3/serp/google/organic/task_get/advanced/{id}", "language_code": "en", "load_async_ai_overview": true, "location_coordinate": "{lat},{lon},200", "max_tasks_per_post": 100, "method": "standard_async", "os": "windows", "post_endpoint": "/v3/serp/google/organic/task_post", "priority": 1}'::jsonb,
       '1e8a8559ec27a1f7f46a8e9a606f438e2987620ae78e077e028f67f01662c0e0'
from manifest.provider_profile pp
join manifest.methodology_version mv on mv.methodology_version_id = pp.methodology_version_id
  and mv.methodology_code = 'MANIFEST_V1_0'
where pp.profile_code = 'DFS_AIO_V1'
on conflict (methodology_version_id, profile_code) do nothing;

-- Repoint the AIO surface config to DFS_AIO_V2 (organic ai_overview).
update manifest.surface_config sc
set provider_profile_id = pp2.provider_profile_id
from manifest.surface s, manifest.methodology_version mv, manifest.provider_profile pp2
where sc.surface_id = s.surface_id and s.surface_code = 'aio'
  and mv.methodology_code = 'MANIFEST_V1_0' and sc.methodology_version_id = mv.methodology_version_id
  and pp2.methodology_version_id = mv.methodology_version_id and pp2.profile_code = 'DFS_AIO_V2';

-- Record the amendment (append-only manifest table; update allowed).
update manifest.methodology_version
set notes = coalesce(notes,'') || ' | AMENDMENT 2026-09-16 (ADR-0008): AIO surface of record = AI Overview in the organic SERP; provider profile repointed DFS_AIO_V1 (ai_mode) -> DFS_AIO_V2 (organic ai_overview + load_async_ai_overview + calculate_rectangles); AI Mode deferred.'
where methodology_code = 'MANIFEST_V1_0'
  and notes not like '%ADR-0008%';
