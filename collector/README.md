# collector — Stage-1 vertical-slice spike (Maps + Organic)

Minimal, **single-coordinate** vertical slice for the Governing build sequence
step 7:

```
one DataForSEO Maps/Organic task_post
  -> immutable content-addressed raw (fail-on-exists, gzipped)
  -> parse
  -> normalize (<surface>.observation / <surface>.result / core.observed_object)
  -> resolve entity
  -> cost ledger (ops.cost_event)
```

This is **not** the production scheduler/worker. It is the smallest end-to-end
path that proves the shared foundation on the cheapest, most-settled surfaces.

Both Google surfaces ride the **one shared foundation** (ADR-0004); the spike
dispatches on `manifest.surface.surface_code`:

| surface | parser | normalizer | resolver | canonical entity |
|---|---|---|---|---|
| `maps` | `parse_maps.py` | `maps.observation` / `maps.result` | place_id-first (`resolve_maps_item`) | `business_location` |
| `organic` | `parse_organic.py` | `organic.observation` / `organic.result` | URL-first, then domain (`resolve_organic_item`) | `web_url` under `web_domain` |

**Organic specifics.** A DataForSEO organic *advanced* response is a
heterogeneous item list (`organic`, `local_pack`, `people_also_ask`,
`related_searches`, …). **Every** block is preserved as an `organic.result` row
with its `result_type` and `rank_absolute`; only an organic web destination
(`type == 'organic'` with a domain/URL) additionally becomes a
`core.observed_object` and is resolved. `returned_result_count` counts the
organic-type items (the Organic surface's result depth); the total block count
is preserved in `serp_metadata`. Per contract §14, organic surfacing creates a
normalized **web** object (`core.web_url` / `core.web_domain`) and **never** a
canonical-business truth — no `business_location` is ever minted from Organic.

## Design

- External effects are behind interfaces so the pipeline is testable offline and
  validatable against the real schema without a paid call:
  - `MapsProvider` (`dataforseo.py`) — real `HttpMapsProvider` vs a fake fixture.
    The same `task_post` → `task_get/advanced` protocol serves Organic (endpoints
    come from the resolved `provider_profile`).
  - `RawStore` (`raw_store.py`) — real Supabase Storage vs an in-memory fake.
- `parse_maps.py`, `parse_organic.py`, `resolve.py`, and `normalize.py` are
  **pure** (no I/O) → unit-tested directly.
- `repository.py` performs all DB writes via `psycopg`, honoring the schema's
  NOT NULL / FK / CHECK constraints and the append-only immutability triggers.
- Idempotency: `job_key = sha256(methodology|wave|surface|industry|market|treatment|coordinate|replicate)`
  (`idempotency.py`). A technical retry never duplicates a paid call; a valid
  short/empty result is a real observation, never retried for a "better" one.

## Configuration (env only — never committed)

Secrets come from the environment (injected by Railway/Supabase secret
management), never from the repo:

| var | purpose |
|---|---|
| `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD` | DataForSEO Basic auth |
| `SUPABASE_DB_URL` | Postgres connection (service-role / direct) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Storage REST for the raw bucket |
| `LSI_METHODOLOGY_CODE` | default `MANIFEST_V1_0` |

## Running the spike

**Gated: the live run makes the first paid DataForSEO call.** Only after the
owner confirms and the secrets above are set, and migrations `001`–`021` are
applied to the target database:

```bash
python -m collector.spike --industry IND010 --market MKT008 --point C --treatment Q1 --surface maps
python -m collector.spike --industry IND010 --market MKT008 --point C --treatment Q1 --surface organic
```

Add `--dry-run` to build and print the request + resolve the manifest context
without calling the provider (no paid call, no writes).

## Tests

`pytest` — provider and storage are mocked; no test hits an external provider.
`scripts/validate_spike.py` applies the migrations to an ephemeral pgvector
Postgres and runs the full parse→normalize→resolve→cost path for **both** the
Maps and Organic surfaces against synthetic fixtures, asserting the rows land
correctly and that a second run is idempotent (still no paid call).
