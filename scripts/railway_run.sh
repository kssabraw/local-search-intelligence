#!/usr/bin/env bash
# Railway one-off entrypoint for the Stage-1 vertical-slice spike.
#
# Steps (in order):
#   1. Apply migrations 001-021 to $SUPABASE_DB_URL (idempotently).
#   2. Reconcile: print coordinate counts (expect 1100 -> 1000 / 91 / 9).
#   3. Dry-run the spike (build/print the request; NO provider call, NO writes).
#   4. ONLY if RUN_PAID_SPIKE=1: run the single PAID Maps spike.
#
# Secrets come from Railway service variables (never the repo):
#   SUPABASE_DB_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
#   DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
#
# Pilot cell defaults (override with SPIKE_* vars): IND010 x MKT008, point C, maps/Q1.
set -euo pipefail

: "${SUPABASE_DB_URL:?set SUPABASE_DB_URL (lsi-dev branch direct connection) in Railway variables}"

INDUSTRY="${SPIKE_INDUSTRY:-IND010}"
MARKET="${SPIKE_MARKET:-MKT008}"
POINT="${SPIKE_POINT:-C}"
SURFACE="${SPIKE_SURFACE:-maps}"
TREATMENT="${SPIKE_TREATMENT:-Q1}"
MIG_DIR="supabase/migrations"

# DIAGNOSTIC ONLY: SPIKE_ZOOM overrides the locked coordinate zoom (e.g. "12z").
ZOOM_ARG=()
if [ -n "${SPIKE_ZOOM:-}" ]; then ZOOM_ARG=(--zoom "${SPIKE_ZOOM}"); fi

# Capture-feasibility probe (ADR-0005): provider call + raw, no surface normalization.
PROBE_ARG=()
if [ "${PROBE_ONLY:-0}" = "1" ]; then PROBE_ARG=(--probe-only); fi

echo "==> [1/4] Applying migrations to target database"
schema_present="$(psql "$SUPABASE_DB_URL" -tAc "select to_regclass('manifest.methodology_version') is not null" || echo 'f')"
if [ "$schema_present" != "t" ]; then
  echo "    schema absent -> applying DDL 001-018"
  for f in "$MIG_DIR"/0{01,02,03,04,05,06,07,08,09,10,11,12,13,14,15,16,17,18}_*.sql; do
    echo "    apply $(basename "$f")"
    psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -1 -f "$f" >/dev/null
  done
else
  echo "    schema already present -> skipping DDL 001-018"
fi
echo "    applying seeds/amendments 019+ (idempotent)"
for f in "$MIG_DIR"/019_*.sql "$MIG_DIR"/02[0-9]_*.sql; do
  echo "    apply $(basename "$f")"
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -1 -f "$f" >/dev/null
done

echo "==> [2/4] Reconciling coordinate counts (expect 1100 / 1000 / 91 / 9)"
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -c \
  "select eligibility, count(*) from manifest.market_coordinate group by rollup (eligibility) order by 1 nulls last;"

echo "==> [3/4] Dry-run (no provider call, no writes)"
python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
  --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" --dry-run

if [ "${RUN_PAID_SPIKE:-0}" = "1" ]; then
  echo "==> [4/4] RUN_PAID_SPIKE=1 -> running the single PAID ${SURFACE} spike${PROBE_ARG:+ (probe-only)}"
  python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
    --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" "${PROBE_ARG[@]}"
else
  echo "==> [4/4] RUN_PAID_SPIKE not set -> stopping before the paid call (gated)."
  echo "    To run the single paid spike: set RUN_PAID_SPIKE=1 on the service and redeploy."
fi

echo "==> done."
