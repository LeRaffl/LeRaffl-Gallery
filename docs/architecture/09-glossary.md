# 09 · Glossary

Domain jargon used across the codebase, the data, and the chats. Look here when an LLM session or a new contributor asks "what does X mean".

## Vehicle / fuel categories

These are the *technical* definitions — what physically distinguishes one drivetrain from another. How each one is mapped into the CSV schema and the chart rollups is in the rightmost column.

| Term | Definition | In our schema |
|---|---|---|
| **BEV** | Battery Electric Vehicle. Propelled exclusively by one or more electric motors drawing from an on-board traction battery, which is recharged from the grid. No combustion engine on board. | `BEV` column. Required for every country. Headline metric of the project. |
| **PHEV** | Plug-in Hybrid Electric Vehicle. Combines a combustion engine with a traction battery that can be recharged from the grid. Can operate in pure-electric mode while the battery has charge; the engine engages above a state-of-charge or speed threshold. Always has an external charging port. | `PHEV` column. Counted as PHEV in the 3-curve rollup; in the TTM stack EREVs (where reported) appear as a separate layer above PHEV. |
| **EREV / P-EREV** | Extended-Range Electric Vehicle. A PHEV variant where the combustion engine is mechanically decoupled from the wheels and acts only as a generator that recharges the battery. P-EREV adds an external charging port (otherwise the engine is the sole energy source). Some sources (China CPCA from 2025-01, ANAC from 2025) lump EREV/P-EREV into PHEV; we follow each source's reporting. | `EREV` column when the source breaks it out (currently China only). Folded into PHEV in the 3-curve plot; its own layer in `_ttm_shares`. |
| **HEV** | (Full) Hybrid Electric Vehicle, a.k.a. self-charging hybrid. Combustion engine plus traction battery, but the battery is recharged *only* by regenerative braking and the engine itself — there is no external charging port. Can drive short distances on electric power alone. | `HEV` column. Counted as ICE in the 3-curve rollup; renders as a parenthetical "of which Xp were HEV" in the post text. |
| **MHEV** | Mild Hybrid (Microhíbrido / Mild-Hybrid). Combustion engine with a small 48V (or smaller) battery that assists with start-stop, regenerative recovery, and brief torque-fill. The MHEV system *cannot* propel the vehicle on electric power alone. Mechanically closer to a conventional ICE than to a full HEV. | `MHEV` column (reserved; not yet populated in any active CSV). Where a source reports MHEV without giving us a column to put it in (e.g. Chile), it falls into the ICE bucket via the implicit `ICE = TOTAL − BEV − PHEV − HEV − OTHERS` subtraction. |
| **ICE** | Internal Combustion Engine. Catch-all for any drivetrain whose sole propulsion source is fuel combustion: petrol, diesel, ethanol, flex-fuel, CNG, LPG, hydrogen ICE, etc. Includes MHEVs by maintainer convention (the mild-hybrid systems don't change the propulsion principle). | `ICE` column when the source reports a single ICE total without splitting fuels (China, USA, South Korea, Thailand, Chile). Otherwise *derived* in the 3-curve plot as `TOTAL − BEV − PHEV − EREV` and shown in the TTM stack as the sum of `PETROL` + `DIESEL` + `FLEXFUEL` + `OTHERS` (+ explicit `ICE` column if present). |
| **PETROL / DIESEL** | Pure-petrol / pure-diesel ICE. Conventional spark-ignition or compression-ignition engine with no hybrid assist. | `PETROL` / `DIESEL` columns. *Caveat:* a small number of source statistics fold petrol-HEV variants into `PETROL` rather than `HEV` (and the same for diesel). Headline ICE/BEV/PHEV trajectories are unaffected — both end up in ICE — but per-fuel TTM shares can be off. Improving the upstream split is a known data-quality task. |
| **FLEXFUEL** | Engine certified to run on a variable mix of petrol and ethanol (E20–E100). Brazil-specific in practice (>80% of new sales there); a small number of Sweden rows also use this column. Counted as ICE in every output. | `FLEXFUEL` column. |
| **ETHANOL** | Pure ethanol (E85+) ICE. Reserved; in practice folded into `OTHERS` or `FLEXFUEL` upstream. Counted as ICE. | `ETHANOL` column (reserved). |
| **GAS / CNG / LPG** | Gas-powered ICE: generic natural gas (`GAS`), compressed natural gas (`CNG`), liquefied petroleum gas (`LPG`). | Reserved columns. Only Georgia currently uses `GAS` (via the re-mapped `PETROL-GAS` source column). Counted as ICE. |
| **OTHERS** | Catch-all for anything the source doesn't put in a named bucket. Typically absorbs `GAS`/`CNG`/`LPG`/`ETHANOL` and hydrogen fuel-cell (FCEV) where they appear. | `OTHERS` column. Counted as ICE in every output chart. |
| **FCEV** | Fuel-Cell Electric Vehicle. Electric motor powered by a hydrogen fuel cell. We do not yet have a dedicated column — sources that report FCEV either fold it into `BEV` (rare, technically wrong but consistent with their definition) or into `OTHERS`. | No dedicated column today. |
| **TOTAL** | All registrations in the period, summed across every drivetrain. | `TOTAL` column. Required. The denominator for every share computation. |
| **Hybrid (capital, no qualifier)** | A source's single combined hybrid bucket — sources that don't split PHEV vs HEV (Türkiye `HYBRIDS`, Georgia `Hybrid`). | Mapped to the `HEV` column on ingest; the post text labels it as "Hybrid" without parentheses to flag the ambiguity. |

## Vehicle scope per source

The technical definitions above are universal; what varies between countries is **which vehicles the source counts in the first place**. Most countries' headline reports cover only light-duty passenger and commercial vehicles, but the exact weight cut-off depends on national regulation. This is the table to keep up-to-date as new countries are added.

| Country | Source | Vehicle scope (included) | Excluded | Authority |
|---|---|---|---|---|
| Chile | ANAC | "Livianos y medianos": passenger cars (Vehículo de Pasajeros), SUVs, pickups (Camionetas) and light commercial vehicles (Vehículo Comercial). **Livianos** = peso bruto vehicular (GVWR) < 2.700 kg; **Medianos** = 2.700 ≤ GVWR < 3.860 kg. | Camiones (trucks ≥ 3.860 kg GVWR), Buses (all). ANAC publishes those in the same monthly PDFs but we don't ingest them. | DS N°241/2014, MTT (Reglamento del Impuesto Adicional a vehículos motorizados nuevos, livianos y medianos) |
| Brazil | ANFAVEA | "Automóveis e Comerciais Leves": passenger cars + light commercial vehicles. ANFAVEA's sheet III is split into two blocks — the first is what we parse. | Caminhões e Ônibus (trucks + buses): different fuel taxonomy, excluded by stopping the parser at the "Fonte:" end-of-table marker. | ANFAVEA classification (industry self-definition); no single legal decree referenced. |
| Japan | JADA | **Standard passenger cars only (kei cars excluded).** 登録車 *(tōrokusha, "registered vehicles": engine > 660 cc **or** length > 3.40 m / width > 1.48 m / height > 2.00 m — no formal weight cap, but in practice ≈ LDV / EU M1; almost all under 3.5 t)*: the 乗用車計 *(jōyōsha-kei, "passenger car total")* row of JADA's "燃料別メーカー別登録台数（乗用車）" *("Registrations by fuel type × maker (passenger cars)")* file. Covers domestic + 輸入車 *(yunyū-sha, imported)* passenger cars across all reported makers. | 軽自動車 *(kei jidōsha, "light vehicles": engine ≤ 660 cc **and** length ≤ 3.40 m / width ≤ 1.48 m / height ≤ 2.00 m — typically 700-1000 kg; ~35-40 % of Japan's new-car market)*: explicitly excluded by JADA's footer "２．軽自動車は含みません。" *("2. Kei cars not included.")*. Trucks and buses are not on this page either (JADA publishes them separately under pages/343/). | 道路運送車両法 *(Dōro Unsō Sharyō Hō, Road Transport Vehicle Act)*. The 登録車 vs 軽自動車 split follows engine displacement **and** body dimensions (no weight cutoff, unlike EU/US/Chile); JADA covers the former, 全国軽自動車協会連合会 *(Zenkei-jikyō, Japan Light Motor Vehicle & Motorcycle Association)* covers the latter. |
| Uruguay | ACAU | **AUTOS + SUV** sheets of the yearly "Compilado YYYY" workbook, summed together. AUTOS covers turismos (sedans, hatchbacks, coupés); SUV covers utility vehicles. Per-model rows with monthly volumes. | MINIBUSES, UTILITARIO (light commercial / pickups), CAMIONES (medium/heavy trucks, would be an HDV candidate), OMNIBUS (buses) — separate sheets in the same workbook, all currently out of scope (no HDV CSV variant exists for Uruguay yet). | ACAU industry-self definition. No single regulatory decree referenced; the IMESI tax-category column (`F`/`F1`/`F2`/`F3`/`F6`) is the closest proxy to a legal classification on the file. |
| USA | ANL (Argonne National Laboratory) | **Light-Duty Vehicles (LDV):** passenger cars + light trucks (US "light-duty" ≈ GVWR ≤ 8,500 lb / 3,856 kg). ANL's "Total Sales" table reports BEV / PHEV / HEV / Total LDV per month; ICE is derived as `TOTAL − BEV − PHEV − HEV`. | Medium- and heavy-duty trucks and buses are not in this table. | ANL Energy Systems & Infrastructure Analysis division; figures aggregate OEM/registration data (e.g. HW/Wards/Hawaii DBEDT lineage seen in older `source` cells). |
| Others | various | *To be documented per country as the scope is confirmed by the maintainer or pulled from the agency's methodology page.* | — | — |

**Why this matters:** the headline BEV-share number for a country is `BEV_count / TOTAL_count`, and `TOTAL` is exactly the count of vehicles within that source's scope. Different scopes are not directly comparable — Chile counting up to 3.860 t is broader than EU `M1+N1` (≤ 3.5 t) but narrower than US light-duty (≤ 8.500 lb ≈ 3.856 t); Japan's 登録車 has no explicit weight cap but is dimension-gated and in practice sits in the same LDV neighbourhood (excluding the ~35-40 % kei-car segment entirely). Document scope before comparing absolute volumes across countries.


## Time / period

| Term | Meaning |
|---|---|
| **period** | A YYYY-MM string identifying the data point. Quarterly entries use the middle month (Q1→Feb, Q2→May, Q3→Aug, Q4→Nov). Yearly entries use July (`YYYY-07`). |
| **time_interval** | One of `monthly`, `quarterly`, `yearly`. Drives how the row is plotted and aggregated. |
| **TTM** | Trailing Twelve Months. Rolling sum of the last 12 monthly rows; shown as the `_ttm_shares` chart and as the second block in the post text. |
| **data_per** | The `period` of the most recent data row this fit was based on. Lives in `params.csv` and `weights.csv`. |
| **model_date** | The day the fit was last run, in `YYYY-MM-DD`. Mostly informational. |
| **baseline_date** | Reserved field in `params.csv`; always blank currently. |

## Identifiers and naming

| Term | Meaning | Example |
|---|---|---|
| **slug** | Lowercase form of country (and optionally variant) with non-alphanumerics replaced by `_`. Used in image filenames and post filenames. | `germany`, `new_zealand`, `denmark_hdv` |
| **country** | The display name of the country | `Germany`, `Türkiye`, `New Zealand` |
| **variant** | A within-country slice | `Whole` (default — labelled "New Cars" in the UI), `Custom`, `HDV`, `Vans`, `Private`, `Industry`, `2-Wheelers`, `3-Wheelers`, `4-Wheelers`, `Used`, `Used Imports`, `Fleet` |
| **type** (in chart filenames) | One of the four canonical chart types | empty (BEV trajectory), `ICE_BEV`, `time`, `ttm_shares` |

## Model parameters

| Term | Meaning |
|---|---|
| **v1, v2, t0** | The three parameters of the BEV-curve fit. The curve is `share(t) = 1 − exp(v1 × (t − (t0 − 1))^v2)`. `t0` is the integer floor of the earliest data year for that country. |
| **ice_v1, ice_v2, ice_t0** | Same shape, fit independently on the ICE share. |
| **verschiebung** | Internal R variable for `t0`. Historical name kept because the math comes from a German R script and renaming it would obscure the byte-for-byte invariant. |
| **extrapol** | The integer year the regression extrapolates to. Currently 2200, far enough that all countries cross every meaningful threshold. |
| **confidence_level** | `0.999` — used to derive the grey/coloured ribbon around each fitted curve. **This is not a true statistical confidence interval.** It is a visual band derived from the fit's standard error scaled by the z-quantile at this level. Useful as a "the curve could plausibly sit anywhere in here" hint, not for rigorous inference. A proper CI is a future improvement. |
| **weight** | In `weights.csv`, the trailing 12-month sum of TOTAL for monthly countries (or trailing-4-quarter sum, or last-yearly). Used as a country importance weight in cross-country aggregates. |

## Architecture / deployment

| Term | Meaning |
|---|---|
| **Worker** | Cloudflare Workers runtime instance running `worker/index.js`. Single deployed unit. |
| **Action** | A GitHub Actions workflow defined in `.github/workflows/*.yml`. We have two: `render-country` (manual) and `build-manifest` (push-triggered). |
| **PAT** | Personal Access Token. The Worker holds a fine-grained PAT scoped to this one repo. |
| **KV** | Cloudflare KV, a key-value store. Used only for rate-limit counters. |
| **Pages** | GitHub Pages, the static-site hosting that serves `index.html` and friends. |
| **manifest** | `manifest.json` at repo root, listing every PNG in `images/`. Built by `build_manifest.R`. |
| **upsert** | Insert-or-update by key. `(country, variant)` for params/weights; `(period, variant)` for `data/<Country>.csv` rows. |
| **honeypot** | A hidden form field that humans never fill but bots auto-populate. Submissions with a non-empty honeypot are silently dropped (response 200 to fool the bot). |
| **rate-limit window** | 60 minutes (`RATE_LIMIT_WINDOW`). Each IP can submit at most `RATE_LIMIT_MAX = 3` of either `/issues` or `/submissions` in that window. |

## Conventions

| Term | Meaning |
|---|---|
| **canonical schema** | The wide-but-sparse fuel-column header that each `data/<Country>.csv` follows. See [03-data-objects.md § 3.1](03-data-objects.md#31-country-raw-data). |
| **wide-but-sparse** | One row per (period, variant); fuel columns are NA where not reported, never zero-filled. |
| **line-level upsert** | Modifying just one line of a CSV without round-tripping the whole file through a parser. Used in `R/upsert.R` to keep diffs minimal. |
| **3-curve rollup** | The aggregation rule for the ICE/BEV/PHEV trajectory plot: BEV / (PHEV + EREV) / (everything else). The "everything else" includes HEV, MHEV, Petrol, Diesel, Gas, OTHERS, and an explicit ICE column if reported. |
| **byte-identical** | The result of a refit must equal the historical params row to ~1e-7 relative tolerance. Drift larger than that means the math has changed and historical thresholds become non-reproducible. |

## Common abbreviations in commit messages and chat

| Abbrev | Stands for |
|---|---|
| **TTM** | Trailing Twelve Months |
| **EAM** | Enterprise Architecture Management |
| **EREV / PHEV / HEV / BEV / MHEV / ICE** | (See vehicle categories above) |
| **PR** | Pull Request |
| **PAT** | Personal Access Token |
| **KV** | Cloudflare Key-Value store |
| **CI** | Continuous Integration (here: GitHub Actions) |
| **`%p`** | Percentage points — the suffix used in the post text to distinguish a sub-percentage value from a top-level percent (e.g. "63.1% ICE (of which 28.2%p were HEV)") |

## See also

- [01-overview.md](01-overview.md) for the high-level picture
- [03-data-objects.md](03-data-objects.md) for schema details
