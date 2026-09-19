# analysis/

Research analysis over the immutable outcome panel. Read-only; no paid call, no
methodology change.

## Layers

- **SQL views** — `supabase/migrations/027_analysis_layer_v0_1.sql` creates the
  `analysis` schema (coverage, distance-decay, entity dominance, Maps↔Organic
  overlap, AIO↔organic overlap) + an immutable `analysis.norm_domain()` that mirrors
  `collector/normalize.py`. Design of record: `docs/design/analysis-layer-v0_1.md`.
  Applied to production; re-applied idempotently on every Railway deploy.
- **Notebook** — `fullpanel_202609_g13e_findings.ipynb` renders the headline findings
  and charts from those views over `FULLPANEL-202609-G13E` (119,000 Maps+Organic
  observations) and `AIO-20260918`.
- **Validation** — `scripts/validate_analysis_views.py` (43 checks, ALL PASS) builds
  a hand-computable panel through the production write path on ephemeral pgvector and
  asserts every view. Run: `python scripts/validate_analysis_views.py`.

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
