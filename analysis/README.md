# analysis/

Research analysis over the immutable outcome panel. Read-only; no paid call, no
methodology change.

## Layers

- **SQL views** — `supabase/migrations/027_analysis_layer_v0_1.sql` creates the
  `analysis` schema (coverage, distance-decay, entity dominance, Maps↔Organic
  overlap, AIO↔organic overlap) + an immutable `analysis.norm_domain()` that mirrors
  `collector/normalize.py`. `028_aio_prevalence_trend.sql` adds
  `analysis.aio_prevalence_trend` — cross-wave AIO prevalence over time (wave-over-wave
  delta, cross-grid safe, query-family aware). Design of record:
  `docs/design/analysis-layer-v0_1.md`. Applied to production; re-applied idempotently
  on every Railway deploy (`02[0-9]_*` glob).
- **Notebook** — `fullpanel_202609_g13e_findings.ipynb` renders the headline findings
  and charts from those views over `FULLPANEL-202609-G13E` (119,000 Maps+Organic
  observations) and `AIO-20260918`.
- **Validation** — `scripts/validate_analysis_views.py` (54 checks, ALL PASS) builds
  a hand-computable panel through the production write path on ephemeral pgvector and
  asserts every view (incl. the `028` trend delta). Run:
  `python scripts/validate_analysis_views.py`.

## Running the notebook

```bash
pip install psycopg[binary] pandas matplotlib jupyter
export SUPABASE_DB_URL="postgresql://postgres.<ref>:<pw>@<pooler-host>:5432/postgres"  # from Railway/Supabase; never commit
jupyter notebook analysis/fullpanel_202609_g13e_findings.ipynb
```

The notebook sets `statement_timeout = 600s` per query — the default 60 s pooler
window is too small for a full-panel (~1.4 M result-row) scan. It defaults to the 3
pilot industries for the Maps distance-decay/overlap cells; set `INDUSTRIES = None`
for the panel-wide run. AIO prevalence is already full-panel.

## AIO over time (free, no paid AIO panel)

`analysis.aio_prevalence_trend` lays out AIO *appearance* chronologically with the
wave-over-wave delta, so the trend accrues for free from each monthly Maps+Organic
Full Panel (the `ai_overview` block rides the plain 600 µUSD organic SERP, no
`load_async` add-on). The delta is computed **only within one grid** (`geometry_code`),
so the `MAPORG13_V1 → GEOGRID13E_V1` repoint never fakes a jump — the clean series
starts from `GEOGRID13E_V1` forward.

```sql
-- whole-wave prevalence trend on the active grid
select wave_code, scheduled_for, aio_prevalence, prevalence_delta, wave_ordinal
from analysis.aio_prevalence_trend
where all_query_families and geometry_code = 'GEOGRID13E_V1'
order by scheduled_for;

-- by query family (near-me vs high-need drift)
select query_family, wave_code, aio_prevalence, prevalence_delta
from analysis.aio_prevalence_trend
where not all_query_families and geometry_code = 'GEOGRID13E_V1'
order by query_family, scheduled_for;
```

## Headline findings (production, 2026-09-18/19)

| finding | value |
|---|---|
| Coverage | 119,000 / 119,000 eligible observations (100 %); 11,000 excluded, 0 obs |
| AIO prevalence (full panel) | **9.86 %** of near-me SERPs carry a standalone AI Overview |
| AIO prevalence by query | 4.3 % "near me" → 9.7 % "in [CITY]" → 11.7 % "best" → 13.7 % high-need |
| Distance-decay (Maps, "near me") | center Local-Pack retained ~18–22 % @3 mi, ~7–9 % @4 mi, ~3–4 % @5 mi |
| Maps↔Organic overlap (locksmith Q1) | only ~16 % of Local-Pack business websites also rank organically |
| AIO↔organic redundancy | AIO web sources ~100 % already rank organically (small n); AIO's independent signal is the GBP carousel |

**Implication for the AIO-widen go/no-go:** a standalone AIO is rare (~10 %) and its
web-citation layer is largely redundant with organic already collected; its only
independent contribution is GBP-carousel embedding. This argues for a **targeted**
widen (high-AIO query classes / GBP-embedding capture) over a full 148,750-task
panel — or deferral — pending the notebook's panel-wide generalization.
