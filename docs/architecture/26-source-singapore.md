# 26 · Source: Singapore (data.gov.sg / LTA "Cars by Fuel Type")

Singapore's Land Transport Authority (LTA) publishes monthly new-car
registrations by fuel type. The figures are republished on the national open
data portal **data.gov.sg**, which exposes them through a clean CKAN datastore
REST API. This is a database-fed country like Canada/Sweden: no PDF, no
scraping — one unauthenticated JSON endpoint, paged.

## TL;DR

```
Source:    data.gov.sg (CKAN datastore; LTA "New Registration of Cars by
           Fuel Type", monthly)
Resource:  d_d3f4d708e1d0a37b4365414e2fad3a07  (cited in the legacy CSV)
Auth:      None required
API:       GET https://data.gov.sg/api/action/datastore_search
              ?resource_id=<id>&limit=<n>&offset=<m>
Variant:   Whole (all cars; Singapore reports a single car series)
Layout:    LONG — one record per (month, fuel_type) with a numeric count;
           summed per month into the wide gallery schema
Coverage:  BEV/PHEV/HEV split resolves from ~2022-07; earlier months report
           electrified cars inside a coarse Others bucket (see §2)
Cadence:   Monthly; time_interval=monthly
HEV:       Reported natively ("Petrol-Electric" / "Non-plugin hybrid")
Backfill:  None — the datastore serves the full history in one resource
Schedule:  Daily days 15-31, 08:00 UTC; commit-gated
Scripts:   scripts/fetch_singapore.py
Workflow:  .github/workflows/fetch-singapore.yml
```

The same LTA data also surfaces as SingStat Table Builder series **M650281** and
inside newautomotive's global EV tracker. data.gov.sg is chosen as the
canonical feed because it is official, has the cleanest JSON API, and is the id
already referenced in the hand-maintained file.

## 1. Fuel classification

The datastore's `fuel_type` labels have shifted over the years. The fetcher maps
them with ordered substring rules (`FUEL_RULES`) that tolerate both the LTA
wording (`Petrol-Electric`, `Petrol-Electric (Plug-In)`, `Electric`) and the
alternative `Battery electric` / `Plugin hybrid` / `Non-plugin hybrid` wording:

```
contains "plug" (but not "non-plug")  → PHEV
contains "battery electric"           → BEV
equals   "electric"                   → BEV
contains "hybrid"                     → HEV   (non-plug-in hybrid)
contains "electric"                   → HEV   (Petrol-Electric, Diesel-Electric)
contains "cng"                        → OTHERS
contains "diesel"                     → DIESEL
contains "petrol"                     → PETROL
everything else                       → OTHERS (printed as a WARNING)
```

The `non-plug` guard matters: **"Non-plugin hybrid"** contains the substring
"plugin" and must NOT be read as a plug-in. Run the workflow once with the
`list_categories` input (or `--list-categories`) to print the live taxonomy and
confirm every label maps where expected before trusting a steady-state run.

## 2. History note: honest pre-2022 electrified figures

The legacy hand-maintained `data/Singapore.csv` spread an **annual** EV estimate
evenly across each month (e.g. every 2017 month carried `BEV = 24.83`) and tagged
those rows `yearly`/`quarterly`. The LTA source only resolves the BEV/PHEV/HEV
split from ~2022-07; before that, electrified cars sit in a coarse Others/
Petrol-Electric bucket. A clean fetch therefore yields **empty BEV/PHEV/HEV for
pre-2022-07 months** and `time_interval=monthly` throughout — more honest than
the spread estimate, but it changes those historical rows. This is expected;
review the diff on first seeding.

## 3. Upsert & idempotence

Keyed on `(period, variant)`, mirroring `fetch_malaysia.py`. The workflow's
commit step is change-gated, so steady-state daily runs are a no-op once the
latest month is present. Use `--since YYYY-MM` to limit the upsert to recent
months and leave curated history untouched; omit it to rebuild the full series.
