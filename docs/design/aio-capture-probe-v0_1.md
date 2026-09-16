# AIO Capture-Feasibility Probe v0.1 (Stage 2, ADR-0005 Gate-1)

Status: **EXECUTED on production (2026-09-16) + verified.** Wave
`AIOPROBE-AIOPROBE_V0-20260916`: 30/30 triggered (trigger rate 1.0), $0.072
(2,400 µUSD/task), gate re-closed. The column-by-column ruling from the results is
in `aio-schema-decision-v0_1.md`; the GBP detect/resolve mechanics are shipped +
tested in `collector/aio_destination.py`. (Harness was built offline-validated first;
the live sweep was gated on `RUN_AIO_PROBE`, default closed.)

This is the Stage-2 (AIO surface) **capture-feasibility gate** required by
[ADR-0005](../adr/0005-per-surface-capture-feasibility-gate.md): *before* we commit
(or extend) the `aio.*` schema and build an AIO collector, we run a small live probe
that proves which fields the provider actually returns, and mark everything it does
not return `provider_not_observable` rather than as empty columns implying absence.

It rides the already-validated shared foundation (immutable content-addressed raw,
the observation/attempt/cost ledger, deterministic idempotency, the water gate). It
does **not** normalize into `aio.*`, mint entities, or change any frozen methodology
dimension — that is deferred until the probe passes and the owner signs off.

## What is being probed

- **Surface / endpoint:** the already-seeded `DFS_AIO_V1` provider profile —
  DataForSEO **AI Mode** (`/v3/serp/google/ai_mode/task_post` →
  `/v3/serp/google/ai_mode/task_get/advanced/{id}`), `location_coordinate`
  `{lat},{lon},9z`, `en` / `desktop` / `windows`. This is the surface the manifest
  commits for AIO; the probe tests exactly it (no silent endpoint change).
- **Request augmentation:** the probe sets `calculate_rectangles=true`. DataForSEO
  only returns pixel `rectangle` geometry when asked, and the AIO PRD (§17/§32)
  requires element rectangles for placement / above-the-fold analysis — so *not*
  asking would make rectangles look unobservable when they may not be. Whether the
  AI-Mode endpoint honours the flag is itself a probe finding (toggle with
  `--no-rectangles`).
- **Cells / scope:** the frozen 3×5 Stage-1 pilot cells (Locksmith IND010, Urgent
  Care IND019, Chinese Restaurant IND022 × MKT008/011/021/040/049), geometry
  **center point C** only (capture feasibility is about field *presence*, not spatial
  coverage), and a small **versioned probe condition subset** `AIOPROBE_V0` =
  `AIO_C01` (core near-me) + `AIO_C04` (core explicit-city), spanning the
  query-formulation families the AIO PRD §8 makes first-class. **This is a probe
  selection, not the locked production condition set** (the full 10 `AIO_QUERY_V1`
  conditions stay owner-signed in the manifest). Default sweep = 3 × 5 × 2 = **30
  executable jobs** (structural-water coordinates are dropped, never submitted).

## The capture checklist (AIO-PRD field → probe check → schema decision)

The inspector (`collector/inspect_aio.py`) is pure-Python (no LLM — parent PRD hard
rule) and **schema-agnostic**: it recurses the whole response and detects each
capability by structure + value patterns, and always emits a raw
`structure_fingerprint` (every observed item `type` + key set + URL sample) so a
human can verify the verdicts against the immutable raw.

| Capability key | AIO PRD | Probe check |
|---|---|---|
| `aio_answer_text` | §15/17 | any `markdown`/`text`/`answer` content returned |
| `element_level_structure` | §17 | element/sub-element items, not one flat blob |
| `element_rectangles` | §17/§32 | a `rectangle` object (x/y/width/height) anywhere |
| `source_citations` | §16/18 | a `references`/`sources` array (source visibility) |
| `reference_vs_link` | §18 | reference/citation distinguishable from inline link (`is_reference` flag, or separate refs + inline links) |
| `local_business_cards` | §69 | structured local-business-card module(s) |
| `embedded_gbp` | §69 | direct embedded GBP / Maps entity surface (type hints, place_id/cid, GBP URLs) |
| `destination_searchviewer` | §69 | Google SearchViewer / Maps / GBP destination URLs |
| `business_position_order` | §32/§69 | rank / position / order for selected businesses |

Per-response verdict: `present` (found, with evidence) · `absent` (a valid AIO came
back without it) · `uncertain` (no AIO triggered — this response cannot decide).

## Decision rule (what the report drives)

`collector/aio_probe.py summarize_capture` rolls each field up across the wave:

- **CAPTURABLE** — the provider returned it in ≥1 triggered AIO → **build the
  `aio.*` column**.
- **NOT_OBSERVABLE** — ≥1 AIO triggered but the field never appeared → **mark
  `provider_not_observable`; do not build an empty column**. Per ADR-0005, if a
  *locked* field proves uncollectable this is escalated as a methodology decision,
  not silently absorbed.
- **INCONCLUSIVE** — no AIO triggered in the whole wave → cannot decide; widen the
  probe (more conditions / cells) before committing schema.

The report also gives the **trigger rate** (triggered / returned) — itself a primary
Stage-2 finding (how often local-intent queries surface an AI answer at all).

## AI Mode vs. AI Overview (a finding to resolve, not a silent choice)

The manifest commits AIO to DataForSEO's **AI Mode** endpoint. The AIO PRD's
citation/element/local-card/embedded-GBP model is written largely around the **AI
Overview** block that appears in the organic SERP. These are related but distinct
Google surfaces. The probe deliberately tests the *committed* endpoint first; if AI
Mode does not return the local-surface fields (local cards / embedded GBP /
SearchViewer destinations) that AI Overview would, that is a **capture finding to
put to the owner** — possibly warranting a probe of the AI-Overview-via-organic path
as a methodology decision — never an in-code switch of the frozen provider profile.

## Guardrails held

- Immutable append-only raw before any normalization (request + task_post + task_get
  stored content-addressed, fail-on-exists, gzipped); the probe never overwrites.
- Missing ≠ zero: structural-water coordinates are never submitted; a non-triggering
  AIO is a valid observation, not a failure, and never a fabricated zero.
- One paid task per job; idempotency at submission (a committed observation
  short-circuits → resume re-POSTs nothing, re-pays nothing).
- No LLM in the capture path; the inspector is deterministic parsing only.
- No composite score; no methodology/geometry/condition/depth change — this is an
  ADR-0005 probe, not a committed surface.
- Every paid call attributed truthfully in the cost ledger (the probe records the
  provider's own per-task `cost`, not $0).

## Gate, cost, and how to run (owner action, on "go")

- **Gate:** `RUN_AIO_PROBE` (default `0`/closed, independent of `RUN_PAID_SPIKE` /
  `RUN_PAID_PILOT` / `RUN_PAID_PANEL`). The paid `--execute` path refuses unless
  `RUN_AIO_PROBE=1`, checked before any DB connection. `--dry-run` (default) prints a
  water-gated plan with no writes and no call.
- **Cost:** ~30 AI-Mode tasks. DataForSEO AI-Mode task pricing is **not yet measured
  on this account** (only the Maps/Organic SERP standard price — 600 µUSD/task — is
  seeded), so the probe records the real per-task cost from each response and a
  `DFS_AIO_*` price row can be seeded from the measured value afterwards. Expected
  total is small (order of $0.05–$0.30 for the default sweep); the go/no-go states
  the current estimate.
- **Run (offline first, then gated live):**
  - Dry-run plan: `python -m collector.aio_probe --dry-run`
  - Offline validation: `python scripts/validate_aio_probe.py`
  - Live (owner opens the gate for one run, then re-closes it):
    `RUN_AIO_PROBE=1` on the Railway service → redeploy → the entrypoint runs the
    probe sweep + prints the capture report → set `RUN_AIO_PROBE=0`.
  - Report for an existing wave: `python -m collector.aio_probe --summarize-only <WAVE_CODE>`

## After the probe

- Publish the capture report; decide per field CAPTURABLE / NOT_OBSERVABLE /
  INCONCLUSIVE.
- Only then: author the AIO schema reconciliation (columns for the CAPTURABLE fields;
  `provider_not_observable` for the rest), the AIO parser/normalizer/entity path on
  the shared foundation, and confirm the 9-point geometry + 10-condition production
  matrix — each with owner sign-off. AI-Overview-vs-AI-Mode resolved from findings.
