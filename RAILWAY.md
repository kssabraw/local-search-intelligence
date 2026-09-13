# Running the Stage-1 spike on Railway

The collector is a **one-off job**, not a web service. This config lets a Railway
service (built from this repo) apply the migrations to the target Supabase DB and
run the vertical-slice spike, with the paid call gated behind a flag.

## What the service does (`scripts/railway_run.sh`, via `Dockerfile`)

1. Apply migrations `001`–`021` to `$SUPABASE_DB_URL` (idempotent: schema DDL only
   if absent; seeds always).
2. Print the coordinate reconciliation (expect **1100 → 1000 / 91 / 9**).
3. **Dry-run** the spike — builds/prints the request, **no provider call, no writes**.
4. **Only if `RUN_PAID_SPIKE=1`** → run the single **paid** Maps spike.

It exits 0 after the safe steps; `restartPolicyType: NEVER` keeps it from re-running.

## One-time setup

1. **Create the service** in the Railway `local-search-intelligence` project →
   **Deploy from GitHub repo** → `kssabraw/local-search-intelligence`.
   (Not "Database" — we use Supabase, not a Railway Postgres. Not "Docker image".)
2. **Deploy branch:** this scaffolding lives on `claude/lsi-platform-setup-bxe6p1`
   until PR #4 merges. Either merge PR #4 to `main`, or set the service's deploy
   branch to `claude/lsi-platform-setup-bxe6p1`, so Railway builds a commit that
   actually contains the `Dockerfile`.
3. **Set service variables** (Railway → service → Variables). Secrets never live in
   the repo:

   | Variable | Value |
   |---|---|
   | `SUPABASE_DB_URL` | `lsi-dev` branch **direct** connection URI (port 5432), password included |
   | `SUPABASE_URL` | `https://ygzoqxrkjtzqbcglodkg.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | `lsi-dev` → Settings → API → service_role |
   | `DATAFORSEO_LOGIN` | DataForSEO account |
   | `DATAFORSEO_PASSWORD` | DataForSEO account |

   Optional overrides: `SPIKE_INDUSTRY` (IND010), `SPIKE_MARKET` (MKT008),
   `SPIKE_POINT` (C), `SPIKE_SURFACE` (maps), `SPIKE_TREATMENT` (Q1).

## Running

- **First deploy** (leave `RUN_PAID_SPIKE` unset): applies migrations, reconciles,
  dry-runs. Safe — no paid call. Check the deploy logs for the reconciliation table
  and the printed request.
- **The paid spike** (after confirming): set `RUN_PAID_SPIKE=1` on the service and
  redeploy. It runs exactly one Maps `task_post` for the pilot coordinate, stores
  immutable raw, parses, normalizes, resolves the entity, and writes the cost event.
  The collector is idempotent — a repeat deploy won't re-issue the paid call for the
  same job.

If `SUPABASE_DB_URL` uses the branch's **direct** connection and your network blocks
it, use the **Session pooler** connection string from the same Supabase **Connect**
dialog instead (same password).
