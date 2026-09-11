# QA / Wave Acceptance Contract v0.1

**Status:** DRAFT — awaiting owner sign-off. Pre-provisioning.

**Scope:** the quality gates and acceptance rules for a **Maps/Organic** collection wave, plus the **Stage-1 pilot go/no-go** and the **13-vs-9 telemetry** the pilot must produce. AIO/ChatGPT get their own acceptance addenda at their stages. A machine-readable rules file + SQL seed follows this doc once the schema (v0.1) is applied.

**Governing principle:** a wave is accepted only when it is provably COMPLETE. `PARTIAL` means REMEDIATE, never GO. QA never *fixes* data — it accepts, quarantines, or flags for remediation.

---

## 1. Wave lifecycle

A **wave** is one versioned collection cohort of a panel for one surface. Each wave:

1. opens a `research_run` with an explicit `cohort_type` (`PILOT` | `FULL_PANEL` | `SENTINEL` | `EXPERIMENT`) and freezes the methodology/geometry/query/provider versions;
2. issues one `provider_task` per (eligible coordinate × query condition), skipping structurally-excluded coordinates (they are recorded, not requested);
3. persists each raw response immediately (fail-on-exists) before parsing;
4. parses into normalized `surface_observation` + result children;
5. resolves newly observed businesses/domains;
6. runs the QA checks in §4;
7. receives a wave verdict (§5).

Steps 1–3 must complete independently of 4–6: if parsing/resolution is delayed, the immutable raw + task records survive and downstream work is re-runnable.

---

## 2. Observation states, retries & structural missingness

- **Valid outcomes that are NOT failures:** an empty local result set, a short result set, or a business's non-appearance are **scientific observations** — recorded, never retried for a "better" result.
- **Retries** are for **QA-authorized technical failures only** (provider 5xx/timeout/malformed transport, checkout/parse crash before any result body). `max_attempts = 3` (initial + 2). Every attempt preserves attempt number, reason, and outcome; a retry must **never** duplicate a paid provider call that already succeeded.
- **Structural missingness is not zero.** `structural_water_exclusion`, `outside_country_exclusion`, and `configuration_failure` coordinates are excluded *before* SERP observation, retained as missingness, and **never** encoded as rank 0, no-visibility, or a failed task. `provider_not_observable` marks a field the provider never returns. Coverage/prevalence **denominators use eligible coordinates only** — excluded, failed, and methodology-excluded observations are tracked separately and never silently enter a denominator.

---

## 3. Eligibility freeze precondition

A wave may not open until, for every configured coordinate in its markets: the US-country-boundary gate and the 2025 TIGER/Line AREAWATER water classifier have run and each coordinate carries a frozen `eligibility_status`. A center anchor that is itself excluded is a `configuration_failure` that **blocks the wave** for that market/surface until corrected. Excluded coordinates are never relocated, rotated, randomized, substituted, or imputed.

---

## 4. Automated QA checks

Each check has a severity: **BLOCKING** (prevents COMPLETE), **WARNING** (recorded, manual triage), **INFO**.

**Manifest ↔ collection reconciliation**
- Every eligible (coordinate × condition) in the frozen manifest has exactly one task; no extra, no missing. *(BLOCKING)*
- Coordinate count per market matches the frozen geometry's eligible count (not an assumed 13). *(BLOCKING)*
- No coordinate drift: each task's lat/lng equals the registry coordinate. *(BLOCKING)*
- No duplicate coordinates within a market/geometry. *(BLOCKING)*

**Raw & integrity**
- Every succeeded task has exactly one `raw_observation` with a resolvable, unique, content-addressed `storage_path`. *(BLOCKING)*
- No normalized observation lacks a raw pointer. *(BLOCKING)*
- Result depth within the locked bound (Maps/Organic Top-10); unexpected depth change flagged. *(WARNING)*
- No duplicate business (place_id) within a single local result set. *(WARNING)*
- Malformed / non-canonical URLs. *(WARNING)*

**Entity & geometry sanity**
- Place_id/CID/business resolution conflicts (same place_id → two businesses, or vice-versa). *(BLOCKING)*
- Impossible values: rank ≤ 0, position gaps, out-of-range lat/lng, distance < 0. *(BLOCKING)*
- FK integrity across result → observation → task → run. *(BLOCKING)*

**Denominator & missingness integrity**
- Prevalence/coverage denominators never include failed or methodology-excluded observations. *(BLOCKING)*
- Excluded coordinates carry a reason and never a rank value. *(BLOCKING)*

**Volume, cost & drift**
- Abnormal task failure rate (> threshold, set from pilot baseline). *(WARNING)*
- Provider response schema drift vs the frozen parser expectation. *(BLOCKING for the affected parser)*
- Market-wide ranking discontinuity / unexpectedly empty grids (possible Google volatility, provider issue, or parser failure). *(WARNING → manual)*
- Provider cost spike vs expected wave cost. *(WARNING)*
- Timestamp leakage: no derived feature uses information dated after the observation it explains. *(BLOCKING)*

Thresholds are set **prospectively** from the pilot baseline and versioned; they are never retrofitted after outcomes are seen.

---

## 5. Wave verdict

- **COMPLETE** — zero BLOCKING failures; every eligible (coordinate × condition) resolved to a succeeded task or a legitimate recorded non-result; all raw preserved; reconciliation exact. → eligible for GO / to feed analysis.
- **PARTIAL** — any BLOCKING failure, or unreconciled coverage. → **REMEDIATE, not GO.** Remediation re-runs only the affected tasks (idempotent), never the whole wave.
- WARNING-only waves may be COMPLETE but carry a manual-triage note attached to the run.

Reporting must be able to reconstruct, per wave: expected vs successful vs failed vs excluded tasks; unique canonical businesses/domains; raw-storage writes; and gross-demand vs net-purchased cost.

---

## 6. Stage-1 pilot go/no-go gate

The 15-cell Maps/Organic pilot passes only when it demonstrably produces:

1. immutable raw **and** normalized evidence for every eligible (coordinate × condition);
2. deterministic job identity (idempotency keys; a re-run adopts, never duplicates);
3. valid result-depth capture at the locked Top-10;
4. correct structural-missingness semantics (water/boundary exclusions present, never zero);
5. entity-resolution execution with provenance/confidence (no silent merges);
6. cost/cache telemetry (gross vs net) attributable per surface;
7. a COMPLETE wave verdict under §5;
8. the mandatory failure drills (provider outage mid-wave, forced retry, a `configuration_failure` market) behaving as specified.

A `PARTIAL` pilot is **REMEDIATE**, not GO. Promotion to production requires a COMPLETE-only gate plus exact manifest/DB reconciliation, immutable-raw verification, reproducible rebuild, and the separable telemetry below.

---

## 7. 13-vs-9 geometry telemetry (required pilot output)

The pilot collects all eligible 13 points and derives nested-9 from center + N/S/E/W@1mi + N/S/E/W@5mi; the incremental set is N/S/E/W@3mi. The pilot must measure, separably, the **marginal contribution of the four 3-mile points**:

- unique canonical businesses under 9 vs 13, and businesses found **only** by the incremental four;
- incremental observations, incremental canonical entities after cross-surface dedup, and incremental downstream enrichment/processing/storage cost;
- incremental **spatial** information: distance-decay resolution, directional asymmetry, visibility-radius behaviour, expansion/contraction, longitudinal-transition and explanatory-variable variation.

**Decision rule:** default **RETAIN_13**. Emit `PROPOSE_9_FOR_APPROVAL` only if measured marginal cost is *clearly disproportionate* to the incremental entity + spatial + longitudinal + explanatory value. Mixed or insufficient evidence → **INCONCLUSIVE → RETAIN_13**. No invented equivalence threshold; no outcome-driven optimization; **no geometry change without explicit owner approval.** Observation-count reduction alone is never sufficient evidence for 9.

---

## 8. Machine-readable rules (to follow)

Each §4 check becomes a versioned rule (`rule_id`, severity, SQL/predicate, threshold, threshold_source) in a `qa_rules` seed, evaluated per wave into a `qa_result` record, so acceptance is reproducible and auditable rather than eyeballed. Delivered once schema v0.1 is applied.
