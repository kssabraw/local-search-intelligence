#!/usr/bin/env bash
# Railway one-off entrypoint for the Stage-1 collector.
#
# Steps (in order):
#   1. Apply migrations 001-NNN to $SUPABASE_DB_URL (idempotently).
#   2. Reconcile: print coordinate counts (expect 1100 -> 1000 / 91 / 9).
#   3. Dry-run the single-coordinate spike + the 3x5 pilot plan (NO calls, NO writes).
#   4. ONLY if RUN_PAID_SPIKE=1: run the single PAID Maps/Organic spike.
#   5. ONLY if RUN_PAID_PILOT=1: run the bounded 3x5 Maps+Organic PILOT (MANY paid
#      DataForSEO calls) + evaluate it under QA/Wave-Acceptance v0.1.
#
# The spike gate (RUN_PAID_SPIKE) and the pilot gate (RUN_PAID_PILOT) are SEPARATE
# and both default OFF; set exactly one for a paid run.
#
# Secrets come from Railway service variables (never the repo):
#   SUPABASE_DB_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
#   DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
#
# Spike cell defaults (override with SPIKE_* vars): IND010 x MKT008, point C, maps/Q1.
# Pilot narrows with PILOT_* vars (default = the full frozen 3x5 matrix).
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

echo "==> [1/5] Applying migrations to target database"
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

echo "==> [2/5] Reconciling coordinate counts (expect 1100 / 1000 / 91 / 9)"
psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -c \
  "select eligibility, count(*) from manifest.market_coordinate group by rollup (eligibility) order by 1 nulls last;"

# Optional pilot-scope narrowing (default = the full frozen 3x5 matrix).
PILOT_ARGS=()
[ -n "${PILOT_INDUSTRIES:-}" ] && PILOT_ARGS+=(--industries "$PILOT_INDUSTRIES")
[ -n "${PILOT_MARKETS:-}" ]    && PILOT_ARGS+=(--markets "$PILOT_MARKETS")
[ -n "${PILOT_SURFACES:-}" ]   && PILOT_ARGS+=(--surfaces "$PILOT_SURFACES")
[ -n "${PILOT_TREATMENTS:-}" ] && PILOT_ARGS+=(--treatments "$PILOT_TREATMENTS")
[ -n "${PILOT_POINTS:-}" ]     && PILOT_ARGS+=(--points "$PILOT_POINTS")
[ -n "${PILOT_WAVE_CODE:-}" ]  && PILOT_ARGS+=(--wave-code "$PILOT_WAVE_CODE")

# PILOT_RESUME=1 continues the most recent pilot wave (idempotency is per wave;
# completed jobs are not re-collected/re-paid). Only meaningful for --execute.
PILOT_EXEC_ARGS=()
[ "${PILOT_RESUME:-0}" = "1" ] && PILOT_EXEC_ARGS+=(--resume)
# PILOT_WORKERS parallelizes the live run (default 1 = sequential). Work is
# partitioned by (industry, market, surface) so entity resolution stays correct;
# capped at the number of such groups (<=30 for the full 3x5x2 matrix).
[ -n "${PILOT_WORKERS:-}" ] && PILOT_EXEC_ARGS+=(--workers "$PILOT_WORKERS")

echo "==> [3/5] Dry-run spike (no provider call, no writes)"
python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
  --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" --dry-run
echo "==> [3/5] Dry-run 3x5 pilot plan (water gate + accounting; no call, no writes)"
python -m collector.pilot "${PILOT_ARGS[@]}" --dry-run

if [ "${RUN_PAID_SPIKE:-0}" = "1" ]; then
  echo "==> [4/5] RUN_PAID_SPIKE=1 -> running the single PAID ${SURFACE} spike${PROBE_ARG:+ (probe-only)}"
  python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
    --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" "${PROBE_ARG[@]}"
else
  echo "==> [4/5] RUN_PAID_SPIKE not set -> stopping before the single paid spike (gated)."
fi

if [ "${RUN_PAID_PILOT:-0}" = "1" ]; then
  echo "==> [5/5] RUN_PAID_PILOT=1 -> running the bounded 3x5 PAID pilot (MANY calls) + QA evaluation"
  python -m collector.pilot "${PILOT_ARGS[@]}" "${PILOT_EXEC_ARGS[@]}" --execute --persist-evaluation
else
  echo "==> [5/5] RUN_PAID_PILOT not set -> stopping before the paid pilot (gated)."
  echo "    To run the paid 3x5 pilot: set RUN_PAID_PILOT=1 on the service and redeploy."
  echo "    To RESUME an interrupted paid pilot without re-paying for completed jobs,"
  echo "    set PILOT_RESUME=1 (continues the latest pilot wave) or PILOT_WAVE_CODE to a"
  echo "    specific wave (idempotency is per wave)."
fi

echo "==> done."
