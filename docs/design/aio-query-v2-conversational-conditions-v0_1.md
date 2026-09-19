# AIO_QUERY_V2 — conversational AIO conditions (owner-signed-off)

Status: **SIGNED OFF — owner confirmed the two judgment calls 2026-09-19; BUILT +
offline-validated.** This wording is now frozen as `manifest/aio_query_v2_conditions.json`
and compiled deterministically into `supabase/migrations/029_aio_query_v2.sql` (ADR-0011);
that migration applies to production on the next `main` deploy (idempotent, additive).
The collector's active AIO treatment set (`aio_run.AIO_TREATMENT_SET`) is
`AIO_QUERY_V2`; `AIO_QUERY_V1` is retained as history (reproduces the graduated
`AIO-20260918` wave). The full AIO panel runs `AIO_QUERY_V2`.

**Owner confirmations (2026-09-19):** (1) C07/C08 normalized to one template across all
industries — **confirmed**; (2) C06 adapted "immediate / last-minute" framing kept for
discretionary/food industries (incl. Chinese Restaurant) — **confirmed**. Both judgment
calls below are resolved as drafted.

## What changes vs `AIO_QUERY_V1`

10 conditions per industry, same count. **C01–C04, C09, C10 are unchanged** (kept from
V1). **C05–C08 are replaced** with conversational, natural-language intents (V1's
`recommended_city` / `top_rated_city` / `reviews_city` / `local_city` are dropped —
they were short keyword variants, not conversational).

| # | Family / intent | Source |
|---|---|---|
| C01 | core near-me | kept from V1 (`[SERVICE] near me`) |
| C02 | best near-me | kept (`best [SERVICE] near me`) |
| C03 | service-variant near-me | kept (V1's per-industry variant) |
| C04 | explicit-city | kept (`[SERVICE] in [CITY]`) |
| **C05** | **problem-led conversational** | **NEW — per-industry scenario** |
| **C06** | **duress / immediate-need conversational** | **NEW — per-industry scenario** |
| **C07** | **price / value conversational** | **NEW** (`Who offers reasonably priced [SERVICE] in [CITY]?`) |
| **C08** | **criteria / decision-support conversational** | **NEW** (`What should I look for … and which local [ENTITY] meet those criteria?`) |
| C09 | best explicit-city | kept (`best [SERVICE] in [CITY]`) |
| C10 | high-need explicit-city | kept (V1's per-industry high-need variant) |

Derived/kept conditions (C01/C02/C04/C09 from the service noun; C03/C10 carried
verbatim from V1) are not re-listed here per industry — they are unchanged. This doc
is the review surface for the **new C05–C08**.

## Two judgment calls to confirm (flagged)

1. **C07/C08 normalized to one template across all industries.** Your two examples
   varied the phrasing ("locksmith services" vs "Which urgent care clinics … are
   reasonably priced"). For cross-industry research consistency (C07/C08 are one
   condition family each), I normalized all 25 to a single template with a per-industry
   service phrase + entity noun. Say the word if you'd rather keep bespoke phrasing.
2. **C06 "duress" intensity varies by industry.** True emergencies exist for
   plumbing/electrical/locksmith/urgent-care/vet/water-damage; for discretionary
   services (house cleaning, landscaping, med spa, handyman) and **Chinese Restaurant**
   there is no genuine emergency, so C06 is adapted to "immediate / last-minute need."
   Chinese Restaurant's C05/C06 are non-emergency by nature — flagged for your review.

## The per-industry conversational library (C05–C08) — DRAFT

`[CITY]` is substituted per market at render time (as in V1's C04). Closing verb
varies by industry (call / go / see / contact / take my car / order).

### Home & field services

**IND001 Plumbing**
- C05: `My kitchen faucet has been dripping and I'd like to get it fixed. Who should I call in [CITY]?`
- C06: `A pipe burst and water is flooding my basement. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced plumbing services in [CITY]?`
- C08: `What should I look for when choosing a plumber in [CITY], and which local companies meet those criteria?`

**IND002 HVAC**
- C05: `My AC hasn't been cooling well and I'd like to have it looked at. Who should I call in [CITY]?`
- C06: `My furnace stopped working and it's freezing in the house. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced HVAC services in [CITY]?`
- C08: `What should I look for when choosing an HVAC contractor in [CITY], and which local companies meet those criteria?`

**IND003 Roofing**
- C05: `I noticed a few missing shingles after a storm and want my roof inspected. Who should I call in [CITY]?`
- C06: `My roof is leaking into the house during a storm. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced roofing services in [CITY]?`
- C08: `What should I look for when choosing a roofer in [CITY], and which local companies meet those criteria?`

**IND004 Electrician**
- C05: `I want to add a few outlets and have some old wiring checked. Who should I call in [CITY]?`
- C06: `Half my house lost power and I smell something burning from an outlet. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced electrical services in [CITY]?`
- C08: `What should I look for when choosing an electrician in [CITY], and which local companies meet those criteria?`

**IND005 Pest Control**
- C05: `I've been seeing a few ants in the kitchen and want to deal with it. Who should I call in [CITY]?`
- C06: `I just found a large wasp nest by my front door and need it removed right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced pest control services in [CITY]?`
- C08: `What should I look for when choosing a pest control company in [CITY], and which local companies meet those criteria?`

**IND006 Tree Service**
- C05: `I have a large tree that needs trimming before it gets too close to the house. Who should I call in [CITY]?`
- C06: `A large tree limb just fell and is blocking my driveway. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced tree services in [CITY]?`
- C08: `What should I look for when choosing a tree service in [CITY], and which local companies meet those criteria?`

**IND007 Garage Door Repair**
- C05: `My garage door has been opening slowly and making a grinding noise. Who should I call in [CITY]?`
- C06: `My garage door spring snapped and my car is stuck inside. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced garage door repair in [CITY]?`
- C08: `What should I look for when choosing a garage door repair company in [CITY], and which local companies meet those criteria?`

**IND008 Water Damage Restoration**
- C05: `I had a small leak that left some water damage and want it assessed. Who should I call in [CITY]?`
- C06: `My house flooded and there's standing water everywhere. I need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced water damage restoration in [CITY]?`
- C08: `What should I look for when choosing a water damage restoration company in [CITY], and which local companies meet those criteria?`

**IND009 Handyman**
- C05: `I have a few small repairs around the house I'd like taken care of. Who should I call in [CITY]?`
- C06: `A shelf just collapsed and I need someone to fix it today. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced handyman services in [CITY]?`
- C08: `What should I look for when choosing a handyman in [CITY], and which local companies meet those criteria?`

**IND010 Locksmith** *(your example, verbatim)*
- C05: `I just moved into a house and want the locks changed. Who should I call in [CITY]?`
- C06: `I'm locked out of my house and need help right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced locksmith services in [CITY]?`
- C08: `What should I look for when choosing a locksmith in [CITY], and which local companies meet those criteria?`

**IND020 Auto Repair**
- C05: `My car is making a strange noise and I'd like to get it checked. Who should I take my car to in [CITY]?`
- C06: `My car broke down and I need it repaired right away. Who should I take my car to in [CITY]?`
- C07: `Who offers reasonably priced auto repair in [CITY]?`
- C08: `What should I look for when choosing an auto repair shop in [CITY], and which local shops meet those criteria?`

**IND023 Moving Company**
- C05: `I'm planning a move in a couple of months and want to line up a mover. Who should I call in [CITY]?`
- C06: `I need to be moved out by this weekend and need movers right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced moving services in [CITY]?`
- C08: `What should I look for when choosing a moving company in [CITY], and which local companies meet those criteria?`

**IND024 Landscaping**
- C05: `I'd like to get my yard cleaned up and maintained regularly. Who should I call in [CITY]?`
- C06: `I have an event at my house this weekend and need my yard done right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced landscaping services in [CITY]?`
- C08: `What should I look for when choosing a landscaper in [CITY], and which local companies meet those criteria?`

**IND025 House Cleaning**
- C05: `I'd like to set up regular cleaning for my home. Who should I call in [CITY]?`
- C06: `I have guests arriving tomorrow and need my house cleaned right away. Who should I call in [CITY]?`
- C07: `Who offers reasonably priced house cleaning services in [CITY]?`
- C08: `What should I look for when choosing a house cleaning service in [CITY], and which local companies meet those criteria?`

### Legal

**IND011 Personal Injury Law**
- C05: `I was in a minor car accident and I'm wondering whether I have a case. Who should I contact in [CITY]?`
- C06: `I was seriously injured in an accident and need legal help right away. Who should I contact in [CITY]?`
- C07: `Who offers reasonably priced personal injury legal services in [CITY]?`
- C08: `What should I look for when choosing a personal injury lawyer in [CITY], and which local firms meet those criteria?`

**IND012 Family Law**
- C05: `My spouse and I are considering divorce and I want to understand my options. Who should I contact in [CITY]?`
- C06: `I was just served with custody papers and need legal help right away. Who should I contact in [CITY]?`
- C07: `Who offers reasonably priced family law services in [CITY]?`
- C08: `What should I look for when choosing a family lawyer in [CITY], and which local firms meet those criteria?`

**IND013 Criminal Defense Law**
- C05: `I'm under investigation and want to understand my legal options. Who should I contact in [CITY]?`
- C06: `A family member was just arrested and needs a lawyer right away. Who should I contact in [CITY]?`
- C07: `Who offers reasonably priced criminal defense services in [CITY]?`
- C08: `What should I look for when choosing a criminal defense lawyer in [CITY], and which local firms meet those criteria?`

### Health & wellness

**IND014 Dentistry**
- C05: `I'm overdue for a checkup and cleaning and want to find a dentist. Where should I go in [CITY]?`
- C06: `I have severe tooth pain and need to be seen right away. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced dental care in [CITY]?`
- C08: `What should I look for when choosing a dentist in [CITY], and which local practices meet those criteria?`

**IND015 Cosmetic Dentistry**
- C05: `I'd like to improve my smile and am considering veneers. Where should I go in [CITY]?`
- C06: `I chipped my front tooth before an event and want it fixed right away. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced cosmetic dentistry in [CITY]?`
- C08: `What should I look for when choosing a cosmetic dentist in [CITY], and which local practices meet those criteria?`

**IND016 Chiropractic**
- C05: `I've had ongoing back stiffness and want to see a chiropractor. Where should I go in [CITY]?`
- C06: `I threw out my back and can barely move. I need to be seen right away. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced chiropractic care in [CITY]?`
- C08: `What should I look for when choosing a chiropractor in [CITY], and which local practices meet those criteria?`

**IND017 Med Spa**
- C05: `I'm interested in trying Botox or a facial treatment. Where should I go in [CITY]?`
- C06: `I have an event this weekend and want a last-minute treatment. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced med spa treatments in [CITY]?`
- C08: `What should I look for when choosing a med spa in [CITY], and which local providers meet those criteria?`

**IND018 Optometry**
- C05: `I think I need new glasses and want to schedule an eye exam. Where should I go in [CITY]?`
- C06: `Something is suddenly wrong with my vision and I need to be seen right away. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced eye exams in [CITY]?`
- C08: `What should I look for when choosing an optometrist in [CITY], and which local practices meet those criteria?`

**IND019 Urgent Care** *(your example, verbatim C05/C06)*
- C05: `I have a minor injury that isn't serious enough for the ER. Where should I go in [CITY]?`
- C06: `I need medical attention for something that isn't an emergency, but I need to be seen right away. Where should I go in [CITY]?`
- C07: `Who offers reasonably priced urgent care in [CITY]?`  *(normalized from your "Which urgent care clinics … are reasonably priced" — see judgment call #1)*
- C08: `What should I look for when choosing an urgent care clinic in [CITY], and which local clinics meet those criteria?`

**IND021 Veterinary**
- C05: `My dog is due for a checkup and vaccinations. Who should I take my pet to in [CITY]?`
- C06: `My pet is very sick and needs to be seen right away. Who should I take my pet to in [CITY]?`
- C07: `Who offers reasonably priced veterinary care in [CITY]?`
- C08: `What should I look for when choosing a veterinarian in [CITY], and which local clinics meet those criteria?`

### Food

**IND022 Chinese Restaurant** *(non-emergency; C06 adapted — flagged)*
- C05: `I'm planning a family dinner and want good Chinese food. Where should I go in [CITY]?`
- C06: `I want Chinese food delivered as soon as possible tonight. Where should I order from in [CITY]?`
- C07: `Who offers reasonably priced Chinese food in [CITY]?`
- C08: `What should I look for when choosing a Chinese restaurant in [CITY], and which local restaurants meet those criteria?`

## Build plan (on wording sign-off)

1. **ADR-0011** — versioned amendment: new `AIO_QUERY_V2` treatment set (conversational
   C05–C08), V1 retained as history; no other methodology change (same 25×50 universe,
   same `GEOGRID13E_V1` geometry, same `DFS_AIO_V2` provider, same 10-condition count).
2. **`manifest/aio_query_v2_conditions.json`** — this library as structured data (the
   frozen source of truth), + `scripts/gen_migration_029_aio_query_v2.py` → deterministic
   `supabase/migrations/029_aio_query_v2.sql` (25×10 treatments + `surface_treatment`
   links for the `aio` surface). Regenerated on any wording edit.
3. **Collector switch** — `aio_run.AIO_TREATMENT_SET` → `AIO_QUERY_V2` (V1 kept for the
   historical wave). Full-panel scope stays 25 × 10 × 595 = 148,750 executable.
4. **Offline validation** — apply 001–029 on ephemeral pg; assert 250 V2 treatments,
   `[CITY]` renders per market, V1 retained, `surface_treatment` links present, and the
   full-panel scope still resolves 148,750; `pytest` + `validate_migrations` green.
5. Apply to production + point the panel at V2 only after sign-off. (The AIO
   content-analysis enrichment stage, ADR-0010, then analyzes these richer answers.)
