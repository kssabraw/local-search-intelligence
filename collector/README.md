# collector — Stage-1 vertical-slice spike (Maps)

Minimal, **single-coordinate** vertical slice for the Governing build sequence
step 7:

```
one DataForSEO Maps task_post
  -> immutable content-addressed raw (fail-on-exists, gzipped)
  -> parse
  -> normalize (maps.observation / maps.result / core.observed_object)
  -> resolve entity (place_id-first)
  -> cost ledger (ops.cost_event)
```

This is **not** the production scheduler/worker. It is the smallest end-to-end
path that proves the shared foundation on the cheapest, most-settled surface.

## Design

- External effects are behind interfaces so the pipeline is testable offline and
  validatable against the real schema without a paid call:
  - `MapsProvider` (`dataforseo.py`) — real `HttpMapsProvider` vs a fake fixture.
  - `RawStore` (`raw_store.py`) — real Supabase Storage vs an in-memory fake.
- `parse_maps.py` and `resolve.py` are **pure** (no I/O) → unit-tested directly.
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
python -m collector.spike --coordinate MKT008_MAPORG_C --treatment Q1 --surface maps
```

Add `--dry-run` to build and print the request + resolve the manifest context
without calling the provider (no paid call, no writes).

## Tests

`pytest` — provider and storage are mocked; no test hits an external provider.
`scripts/validate_spike.py` applies the migrations to an ephemeral pgvector
Postgres and runs the full parse→normalize→resolve→cost path against a synthetic
Maps fixture, asserting the rows land correctly (still no paid call).
