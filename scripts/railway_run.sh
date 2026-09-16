#!/usr/bin/env bash
# Railway one-off entrypoint for the Stage-1 collector.
#
# Steps (in order):
#   1. Apply migrations 001-NNN to $SUPABASE_DB_URL (idempotently).
#   2. Reconcile: print coordinate counts (expect 1100 -> 1000 / 91 / 9).
#   3. Dry-run the single-coordinate spike + the 3x5 pilot plan + the Full Panel /
#      Sentinel cadence plan (NO calls, NO writes).
#   4. ONLY if RUN_PAID_SPIKE=1: run the single PAID Maps/Organic spike.
#   5. ONLY if RUN_PAID_PILOT=1: run the bounded 3x5 Maps+Organic PILOT (MANY paid
#      DataForSEO calls) + evaluate it under QA/Wave-Acceptance v0.1.
#   6. ONLY if RUN_PAID_PANEL=1: run the Full Panel / Sentinel cadence driver (step
#      10) -- MANY paid calls -- + evaluate under QA/Wave-Acceptance v0.1.
#   7. ONLY if RUN_AIO_PROBE=1: run the AIO capture-feasibility probe (Stage 2,
#      ADR-0005) over the 3x5 pilot cells -- a SMALL number of paid AI-Mode calls --
#      + print the capture report (no aio.* normalization).
#
# The paid gates (RUN_PAID_SPIKE / RUN_PAID_PILOT / RUN_PAID_PANEL / RUN_AIO_PROBE)
# are SEPARATE and ALL default OFF; set exactly one for a paid run.
#
# Secrets come from Railway service variables (never the repo):
#   SUPABASE_DB_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
#   DATAFORSEO_LOGIN, DATAFORSEO_PASSWORD
#
# Spike cell defaults (override with SPIKE_* vars): IND010 x MKT008, point C, maps/Q1.
# Pilot narrows with PILOT_* vars (default = the full frozen 3x5 matrix).
# Panel cadence knobs (PANEL_* vars): PANEL_KIND (auto|full_panel|sentinel),
#   PANEL_WAVE_CODE, PANEL_RESUME, PANEL_BATCH_SIZE, PANEL_POLL_INTERVAL,
#   PANEL_COLLECT_TIMEOUT, PANEL_WORKERS (parallel collect workers).
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

# Full Panel / Sentinel cadence driver (step 10). PANEL_KIND defaults to `auto`
# (Full Panel on the monthly anchor, else Sentinel). The paid run is gated on
# RUN_PAID_PANEL=1 (default closed, independent of the spike/pilot gates).
PANEL_KIND="${PANEL_KIND:-auto}"
PANEL_ARGS=(--kind "$PANEL_KIND")
[ -n "${PANEL_WAVE_CODE:-}" ]       && PANEL_ARGS+=(--wave-code "$PANEL_WAVE_CODE")
[ -n "${PANEL_BATCH_SIZE:-}" ]      && PANEL_ARGS+=(--batch-size "$PANEL_BATCH_SIZE")
[ -n "${PANEL_POLL_INTERVAL:-}" ]   && PANEL_ARGS+=(--poll-interval "$PANEL_POLL_INTERVAL")
[ -n "${PANEL_COLLECT_TIMEOUT:-}" ] && PANEL_ARGS+=(--collect-timeout "$PANEL_COLLECT_TIMEOUT")
[ -n "${PANEL_WORKERS:-}" ]         && PANEL_ARGS+=(--workers "$PANEL_WORKERS")
PANEL_EXEC_ARGS=()
[ "${PANEL_RESUME:-0}" = "1" ] && PANEL_EXEC_ARGS+=(--resume)

echo "==> [3/6] Dry-run spike (no provider call, no writes)"
python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
  --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" --dry-run
echo "==> [3/6] Dry-run 3x5 pilot plan (water gate + accounting; no call, no writes)"
python -m collector.pilot "${PILOT_ARGS[@]}" --dry-run
echo "==> [3/6] Dry-run Full Panel / Sentinel cadence plan (PANEL_KIND=${PANEL_KIND}; no call, no writes)"
python -m collector.panel_driver "${PANEL_ARGS[@]}" --dry-run
echo "==> [3/6] Dry-run AIO capture probe plan (Stage 2 ADR-0005; no call, no writes)"
python -m collector.aio_probe --dry-run

if [ "${RUN_PAID_SPIKE:-0}" = "1" ]; then
  echo "==> [4/6] RUN_PAID_SPIKE=1 -> running the single PAID ${SURFACE} spike${PROBE_ARG:+ (probe-only)}"
  python -m collector.spike --industry "$INDUSTRY" --market "$MARKET" --point "$POINT" \
    --surface "$SURFACE" --treatment "$TREATMENT" "${ZOOM_ARG[@]}" "${PROBE_ARG[@]}"
else
  echo "==> [4/6] RUN_PAID_SPIKE not set -> stopping before the single paid spike (gated)."
fi

if [ "${RUN_PAID_PILOT:-0}" = "1" ]; then
  echo "==> [5/6] RUN_PAID_PILOT=1 -> running the bounded 3x5 PAID pilot (MANY calls) + QA evaluation"
  python -m collector.pilot "${PILOT_ARGS[@]}" "${PILOT_EXEC_ARGS[@]}" --execute --persist-evaluation
else
  echo "==> [5/6] RUN_PAID_PILOT not set -> stopping before the paid pilot (gated)."
  echo "    To run the paid 3x5 pilot: set RUN_PAID_PILOT=1 on the service and redeploy."
  echo "    To RESUME an interrupted paid pilot without re-paying for completed jobs,"
  echo "    set PILOT_RESUME=1 (continues the latest pilot wave) or PILOT_WAVE_CODE to a"
  echo "    specific wave (idempotency is per wave)."
fi

if [ "${RUN_PAID_PANEL:-0}" = "1" ]; then
  echo "==> [6/6] RUN_PAID_PANEL=1 -> running the Full Panel / Sentinel cadence driver (MANY calls) + QA evaluation"
  echo "    PANEL_KIND=${PANEL_KIND} (auto=Full Panel on the monthly anchor, else Sentinel)."
  echo "    Graduated first live step is ONE Sentinel wave; run only on explicit owner 'go'."
  python -m collector.panel_driver "${PANEL_ARGS[@]}" "${PANEL_EXEC_ARGS[@]}" --execute --persist-evaluation
else
  echo "==> [6/6] RUN_PAID_PANEL not set -> stopping before the paid panel wave (gated)."
  echo "    To run a paid panel wave: set RUN_PAID_PANEL=1 on the service and redeploy"
  echo "    (Sentinel-first; PANEL_KIND=sentinel for the graduated first live step)."
  echo "    To RESUME an interrupted panel wave without re-paying for completed jobs,"
  echo "    set PANEL_RESUME=1 (continues the latest wave of the kind) or PANEL_WAVE_CODE."
fi

# AIO capture-feasibility probe (Stage 2, ADR-0005). Small number of paid AI-Mode
# calls over the 3x5 pilot cells; gated on RUN_AIO_PROBE=1 (default closed,
# independent of the spike/pilot/panel gates). Narrow with AIO_PROBE_* vars.
AIO_PROBE_ARGS=()
[ -n "${AIO_PROBE_INDUSTRIES:-}" ] && AIO_PROBE_ARGS+=(--industries "$AIO_PROBE_INDUSTRIES")
[ -n "${AIO_PROBE_MARKETS:-}" ]    && AIO_PROBE_ARGS+=(--markets "$AIO_PROBE_MARKETS")
[ -n "${AIO_PROBE_CONDITIONS:-}" ] && AIO_PROBE_ARGS+=(--conditions "$AIO_PROBE_CONDITIONS")
[ -n "${AIO_PROBE_WAVE_CODE:-}" ]  && AIO_PROBE_ARGS+=(--wave-code "$AIO_PROBE_WAVE_CODE")
[ "${AIO_PROBE_NO_RECTANGLES:-0}" = "1" ] && AIO_PROBE_ARGS+=(--no-rectangles)

if [ "${RUN_AIO_PROBE:-0}" = "1" ]; then
  echo "==> [7/7] RUN_AIO_PROBE=1 -> running the AIO capture-feasibility probe (Stage 2, ADR-0005) + report"
  echo "    Small paid AI-Mode sweep over the 3x5 pilot cells; run only on explicit owner 'go'."
  python -m collector.aio_probe "${AIO_PROBE_ARGS[@]}" --execute
else
  echo "==> [7/7] RUN_AIO_PROBE not set -> stopping before the paid AIO capture probe (gated)."
  echo "    To run it: set RUN_AIO_PROBE=1 on the service and redeploy; re-close after."
  echo "    Report an existing wave later with: python -m collector.aio_probe --summarize-only <WAVE_CODE>"
fi

echo "==> done."
