# Railway image for the Stage-1 vertical-slice spike (one-off job, not a web service).
# Builds the collector, applies migrations to the target Supabase DB, runs the
# dry-run, and — only when RUN_PAID_SPIKE=1 — makes the single paid Maps call.
# See scripts/railway_run.sh and RAILWAY.md.
FROM python:3.11-slim

# psql applies the migration files; ca-certificates for TLS to Supabase.
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY collector/requirements.txt collector/requirements.txt
RUN pip install --no-cache-dir -r collector/requirements.txt

COPY . .
RUN chmod +x scripts/railway_run.sh

# Exits 0 after a safe migrate+dry-run; Railway's default ON_FAILURE restart
# policy then leaves it stopped (no crash loop). The paid run is gated by the
# RUN_PAID_SPIKE env var (see the script).
CMD ["bash", "scripts/railway_run.sh"]
