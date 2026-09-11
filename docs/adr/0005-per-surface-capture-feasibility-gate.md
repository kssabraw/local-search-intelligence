# 0005 — Per-surface capture-feasibility gate before committing that surface's schema

Before committing a surface's schema and building its collector, run a small live probe confirming the provider/vendor actually returns the fields that surface's measurement model requires; build columns only for what the provider *proves* it returns, and mark everything else `provider_not_observable` rather than as empty columns implying absence. The surfaces vary enormously in capture certainty — Maps/Organic (clean DataForSEO SERP) is settled, but AIO depends on the provider exposing element rectangles, citation reference-vs-link, local-business cards, embedded GBP, and SearchViewer destinations, and ChatGPT depends on a vendor genuinely capturing the consumer product plus observed fanout rather than a wrapped API call. A schema written ahead of that proof risks unfillable columns and, for ChatGPT, may force amending an otherwise-locked methodology decision (the consumer-product + fanout target).

## Consequences

- Each surface gets a "Gate-1" provider-validation step analogous to the Maps pilot's provider validation.
- If a locked field proves uncollectable (e.g. ChatGPT fanout via the chosen vendor), that is escalated as a methodology decision, not silently absorbed into empty columns.
