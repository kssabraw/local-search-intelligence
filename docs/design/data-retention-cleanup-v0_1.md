# Data Retention & DB Cleanup v0.1

Status: **DESIGN + tooling (offline-validated); execution is an owner step, after a wave completes.**
Governs: reclaiming Postgres disk by pruning the *derived/normalized* layer of superseded
collection waves, without ever losing recoverable data.

## Why

Each monthly Full Panel writes ~119k observations, and every observation fans out into
many normalized rows (per-rank `maps.result` / `organic.result`, one `core.observed_object`
appearance per result, plus `core.resolution_*` bookkeeping). Two full panels' worth of that
already put the production DB at ~10 GB, and it grows ~5–6 GB per future panel. The bulk is
recoverable derived data, so we prune it on a retention policy instead of paying to store every
panel's normalized layer forever.

## Principle (parent PRD)

- **Raw is immutable and is the source of truth.** Provider payloads live in Supabase Storage
  (gzipped, content-addressed) with their metadata in `ops.raw_blob` / `storage.objects`.
  **Raw is never pruned.**
- **Normalized is derived and rebuildable.** `maps.*`, `organic.*`, `aio.*`, `core.observed_object`,
  and `core.resolution_*` can be reconstructed by re-running the parser over a wave's raw. So a
  superseded wave's normalized rows are safe to delete and, if ever needed, rebuild.
- **Canonical entities are shared, not per-wave.** `core.entity` / `core.web_domain` /
  `core.web_url` / `core.external_identifier` are keyed independently of any single observation and
  are referenced across waves. They are **kept**; a pruned appearance never removes the
  business/domain it resolved to.

## What is pruned vs kept

| Kept (never pruned) | Pruned for a superseded wave |
|---|---|
| `ops.raw_blob`, `storage.objects` (raw payloads) | `maps.result`, `organic.result` (+ `aio.*`/`chatgpt.*` children if any) |
| `core.entity` / `web_domain` / `web_url` / `external_identifier` (canonical graph) | `core.observed_object` (per-observation appearances) |
| `ops.cost_event` (cost ledger — audit) | `core.resolution_run` / `resolution_candidate` / `resolution_assertion` |
| `ops.collection_wave` / `collection_job` (provenance) | `core.entity_alias_assertion` / `entity_relationship_assertion` (sourced from a pruned appearance) |
| all **active-grid** (`GEOGRID13E_V1`) waves | `maps.observation` / `organic.observation` / `aio.observation`, `ops.qa_event`, and finally `ops.observation` |

A pruned wave therefore still *exists* (its wave/job/cost rows remain for audit); it simply has no
normalized observations until rebuilt.

## Prune targets (superseded)

Selected by explicit wave code and/or by geometry. As of the GEOGRID13E_V1 cutover the superseded
set is the **old-grid `MAPORG13_V1`** waves — chiefly the old-grid `FULLPANEL-202609` (~118k
observations, the single biggest reclaim) plus the pre-cutover pilot / sentinel / spike waves — and
the **`AIO9_V1`** AI-Mode probe wave. The active-grid (`GEOGRID13E_V1`) waves are never candidates.

## Foreign keys / delete order

Every FK in the schema is `ON DELETE NO ACTION` (verified) — nothing cascades — so deletes are
issued explicitly **child → parent**, scoped to the target waves via
`collection_job.wave_id`. `scripts/prune_superseded_normalized.py` encodes that order
(`_DELETE_STEPS`) and runs the whole prune in one transaction. Because deletes are explicit and
scoped, the canonical entity tables are structurally out of reach — the script never issues a
delete against them.

### Append-only guard (why pruning is a privileged, deliberate act)

The normalized tables are **append-only at the database level**: a `USER` trigger
(`ops.reject_update_delete()`) raises on any `UPDATE`/`DELETE` — the immutable-observation rule
extends past raw into the derived layer. A prune therefore has to *consciously* lift that guard.
The tool disables the **USER** trigger on each target table **for the prune transaction only** and
re-enables it before commit, while leaving the **SYSTEM** triggers (foreign-key enforcement)
**active** — so a mis-scoped delete is still caught by an FK, and any accidental `DELETE` outside
this tool is still rejected. `ALTER TABLE ... TRIGGER` is transactional, so a rollback (dry-run, or
any error) restores every trigger automatically; the tool also re-enables explicitly before commit
and the validator asserts the guard is back on afterward. This bypass is exactly why pruning is an
owner action behind `CONFIRM_PRUNE=1`, not a routine query.

## Reclaiming physical disk

A `DELETE` returns space to Postgres's free map but **does not shrink the database file** — the
dashboard GB figure will not drop until the large tables are compacted. After a prune:

1. `VACUUM (ANALYZE)` the affected tables (planner health; returns space to the free map).
2. `pg_repack` (online, no long lock — preferred on Supabase) **or** `VACUUM FULL` (ACCESS
   EXCLUSIVE lock, needs free scratch ≈ the table's size) on the large tables
   (`core.observed_object`, `maps.result`, `organic.result`, `core.resolution_*`) to return space
   to the OS.

The prune script does **not** run `VACUUM FULL` / `pg_repack` itself — they need their own
maintenance window and are run manually after the prune is verified.

Estimated reclaim from pruning the old-grid full panel + pre-cutover waves: on the order of
**5–7 GB** (raw untouched in Storage).

## Retention policy (going forward)

Keep the **N most recent** monthly Full Panels' normalized data live (suggest **N = 2–3** for
longitudinal trend work). For panels older than N, prune the normalized layer and retain only raw +
the canonical graph. This bounds DB growth at ~N panels (~15–18 GB) instead of unbounded. The prune
can be promoted to a monthly scheduled step once the manual run is trusted.

## The tool

`scripts/prune_superseded_normalized.py` — read-only by default; deletes only with `--execute` **and**
the `CONFIRM_PRUNE=1` env gate (mirrors the paid-collection gates). Modes:

- `--list` — wave inventory: each wave's derived `geometry_code` + observation / observed-object
  footprint. Read-only.
- `--waves CODE[,CODE]` and/or `--geometry CODE` — select targets; **dry-run counts** unless
  `--execute` + `CONFIRM_PRUNE=1`.
- **Active-grid guard:** refuses to prune any wave on the active Maps/Organic grid
  (from `manifest.surface_config`) unless `--allow-active-grid` (tests only).

Offline validation: `scripts/validate_prune.py` seeds two real waves (one pruned, one kept) on an
ephemeral pgvector Postgres via the pilot runner with fake providers, then asserts the target's
normalized rows are gone with no FK violation, the kept wave is intact, and the canonical graph +
raw + cost ledger are unchanged. No paid call, no network.

## Runbook (execute AFTER a wave completes + is verified COMPLETE)

1. Confirm the current waves evaluated and are intact; note a PITR restore point.
2. `python -m scripts.prune_superseded_normalized --list` — confirm which waves are superseded.
3. Dry-run: `--waves FULLPANEL-202609,PILOT-3x5-20260914,SENTINEL-2026W38,...` (or
   `--geometry MAPORG13_V1`) with no `--execute`; eyeball the would-delete counts.
4. Execute: same args + `--execute` with `CONFIRM_PRUNE=1`. Verify canonical entity counts are
   unchanged and the active-grid waves are untouched.
5. `pg_repack` / `VACUUM FULL` the large tables; re-measure DB size.
6. Spot-check a rebuild-from-raw on a small sample to confirm reversibility.
