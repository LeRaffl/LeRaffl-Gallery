# 09 · Glossary

Domain jargon used across the codebase, the data, and the chats. Look here when an LLM session or a new contributor asks "what does X mean".

## Vehicle / fuel categories

These are the *technical* definitions — what physically distinguishes one drivetrain from another. How each one is mapped into the CSV schema and the chart rollups is in the rightmost column.

| Term | Definition | In our schema |
|---|---|---|
| **BEV** | Battery Electric Vehicle. Propelled exclusively by one or more electric motors drawing from an on-board traction battery, which is recharged from the grid. No combustion engine on board. | `BEV` column. Required for every country. Headline metric of the project. |
| **PHEV** | Plug-in Hybrid Electric Vehicle. Combines a combustion engine with a traction battery that can be recharged from the grid. Can operate in pure-electric mode while the battery has charge; the engine engages above a state-of-charge or speed threshold. Always has an external charging port. | `PHEV` column. Counted as PHEV in the 3-curve rollup; in the TTM stack EREVs (where reported) appear as a separate layer above PHEV. |
| **EREV / P-EREV** | Extended-Range Electric Vehicle. A PHEV variant where the combustion engine is mechanically decoupled from the wheels and acts only as a generator that recharges the battery. P-EREV adds an external charging port (otherwise the engine is the sole energy source). Some sources (China CPCA from 2025-01, ANAC from 2025) lump EREV/P-EREV into PHEV; we follow each source's reporting. | `EREV` column when the source breaks it out (China; Spain; Argentina, where the model designation says `REEV`). Folded into PHEV in the 3-curve plot; its own layer in `_ttm_shares`. |
| **HEV** | (Full) Hybrid Electric Vehicle, a.k.a. self-charging hybrid. Combustion engine plus traction battery, but the battery is recharged *only* by regenerative braking and the engine itself — there is no external charging port. Can drive short distances on electric power alone. | `HEV` column. Counted as ICE in the 3-curve rollup; renders as a parenthetical "of which Xp were HEV" in the post text. |
| **MHEV** | Mild Hybrid (Microhíbrido / Mild-Hybrid). Combustion engine with a small 48V (or smaller) battery that assists with start-stop, regenerative recovery, and brief torque-fill. The MHEV system *cannot* propel the vehicle on electric power alone. Mechanically closer to a conventional ICE than to a full HEV. | `MHEV` column — populated only by Argentina (designation-based, a lower bound). Where a source reports MHEV without giving us a column to put it in (e.g. Chile), it falls into the ICE bucket via the implicit `ICE = TOTAL − BEV − PHEV − HEV − OTHERS` subtraction. |
| **ICE** | Internal Combustion Engine. Catch-all for any drivetrain whose sole propulsion source is fuel combustion: petrol, diesel, ethanol, flex-fuel, CNG, LPG, hydrogen ICE, etc. Includes MHEVs by maintainer convention (the mild-hybrid systems don't change the propulsion principle). | `ICE` column when the source reports a single ICE total without splitting fuels (China, USA, South Korea, Thailand, Chile). Otherwise *derived* in the 3-curve plot as `TOTAL − BEV − PHEV − EREV` and shown in the TTM stack as the sum of `PETROL` + `DIESEL` + `FLEXFUEL` + `OTHERS` (+ explicit `ICE` column if present). |
| **PETROL / DIESEL** | Pure-petrol / pure-diesel ICE. Conventional spark-ignition or compression-ignition engine with no hybrid assist. | `PETROL` / `DIESEL` columns. *Caveat:* a small number of source statistics fold petrol-HEV variants into `PETROL` rather than `HEV` (and the same for diesel). Headline ICE/BEV/PHEV trajectories are unaffected — both end up in ICE — but per-fuel TTM shares can be off. Improving the upstream split is a known data-quality task. |
| **FLEXFUEL** | Engine certified to run on a variable mix of petrol and ethanol (E20–E100). Brazil-specific in practice (>80% of new sales there); a small number of Sweden rows also use this column. Counted as ICE in every output. | `FLEXFUEL` column. |
| **ETHANOL** | Pure ethanol (E85+) ICE. Reserved; in practice folded into `OTHERS` or `FLEXFUEL` upstream. Counted as ICE. | `ETHANOL` column (reserved). |
| **GAS / CNG / LPG** | Gas-powered ICE: generic natural gas (`GAS`), compressed natural gas (`CNG`), liquefied petroleum gas (`LPG`). | Reserved columns. Only Georgia currently uses `GAS` (via the re-mapped `PETROL-GAS` source column). Counted as ICE. |
| **OTHERS** | Catch-all for anything the source doesn't put in a named bucket. Typically absorbs `GAS`/`CNG`/`LPG`/`ETHANOL` and hydrogen fuel-cell (FCEV) where they appear. | `OTHERS` column. Counted as ICE in every output chart. |
| **FCEV** | Fuel-Cell Electric Vehicle. Electric motor powered by a hydrogen fuel cell. We do not yet have a dedicated column — sources that report FCEV either fold it into `BEV` (rare, technically wrong but consistent with their definition) or into `OTHERS`. | No dedicated column today. |
| **TOTAL** | All registrations in the period, summed across every drivetrain. | `TOTAL` column. Required. The denominator for every share computation. |
| **Hybrid (capital, no qualifier)** | A source's single combined hybrid bucket — sources that don't split PHEV vs HEV (Türkiye `HYBRIDS`, Georgia `Hybrid`, Ukraine's register fuel value `ЕЛЕКТРО АБО …`). | Mapped to the `HEV` column on ingest, with `PHEV`/`EREV` left **empty**; the post text labels it "Hybrid" without parentheses to flag the ambiguity. The TTM chart shows it as `Hybrid`; the BEV/ICE trajectory counts it inside ICE and **omits the PHEV curve entirely** rather than drawing a zero the source never measured ([#210](https://github.com/LeRaffl/LeRaffl-Gallery/issues/210) — see `has_phev_split` in `R/plots.R`). |

## Vehicle scope per source

The technical definitions above are universal; what varies between countries is **which vehicles the source counts in the first place**. Most countries' headline reports cover only light-duty passenger and commercial vehicles, but the exact weight cut-off depends on national regulation. This is the table to keep up-to-date as new countries are added.

| Country | Source | Vehicle scope (included) | Excluded | Authority |
|---|---|---|---|---|
| Argentina | DNRPA (open microdata) | **`Whole` = new registrations of passenger-car body types** (sedán, rural/SUV, todo terreno, coupé, convertible, familiar) ≈ EU M1, all brands (registry, record level). Only 0 km registrations (`INSCRIPCION INICIAL NACIONAL/IMPORTADO`). `Pickups` = every PICK-UP body type (data-only CSV, not rendered). Fuel is **classified from the model designation** (the records carry no fuel field) and validated against ACARA's electrified totals. | Classic cars, auctioned vehicles, court-ordered registrations; FURGÓN / CHASIS / CAMIÓN / TRANS. DE PASAJEROS / MINIBÚS (no weight or seat count → cannot be mapped to N1/N2/M2/M3, so no Vans/HDV/Buses); L6/L7 quadricycles (Coradir Tita, Sero). No petrol/diesel split (single `ICE`). | DNRPA registry body types (`automotor_tipo_descripcion`); see [39-source-argentina.md](39-source-argentina.md). |
| Ukraine | MIA open vehicle register (data.gov.ua) | **`Whole` = first registrations of new passenger cars** (register kind `ЛЕГКОВИЙ` = EU M1), every brand, record level, by the register's own new-vehicle operation codes (105 dealer-imported, 99 made in Ukraine, 72 private import, 180/184/185 business, …), from 2018-09. `Private`/`Industry` = owner type P/J. `Used` = used passenger cars at their first Ukrainian registration (used imports: codes 100/70/71/76/77/172). `Vans` = new goods vehicles with gross weight ≤ 3,500 kg (N1). Fuel from the record; one combined hybrid value. | Changes of owner, re-registrations, temporary military registrations; op 69 (acceptance act); goods > 3.5 t and buses (no BEV signal yet); motorcycles. No PHEV/HEV split (single Hybrid bucket). | MIA register operation codes and `KIND`/`TOTAL_WEIGHT`; see [40-source-ukraine.md](40-source-ukraine.md). |
| Hong Kong | Transport Department «Particulars of first registered vehicles» (DATA.GOV.HK) | **`Whole` = new private cars**: TD vehicle class `Private Car` (≈ EU M1) with first-registration status A, B or C1 (never, or under 15 days, registered abroad), every brand, record level, from 2019-11. `Used` = status C2 (registered abroad before import — used imports). `Vans` = class `LGV` with permitted gross weight ≤ 3.5 t (N1), status A/B/C1/E. Fuel from the record (no hybrid value): plug-ins classified from the model designation, full/mild hybrids in PETROL. | Taxis (own vehicle class), own-use imports (status D), government auctions (F), LGVs 3.5–5.5 t, goods vehicles and buses, motorcycles. No HEV column. | TD first-registration status (data specification) and Cap. 374 vehicle classes; see [41-source-hong-kong.md](41-source-hong-kong.md). |
| Chile | ANAC | "Livianos y medianos": passenger cars (Vehículo de Pasajeros), SUVs, pickups (Camionetas) and light commercial vehicles (Vehículo Comercial). **Livianos** = peso bruto vehicular (GVWR) < 2.700 kg; **Medianos** = 2.700 ≤ GVWR < 3.860 kg. | Camiones (trucks ≥ 3.860 kg GVWR), Buses (all). ANAC publishes those in the same monthly PDFs but we don't ingest them. | DS N°241/2014, MTT (Reglamento del Impuesto Adicional a vehículos motorizados nuevos, livianos y medianos) |
| Brazil | ANFAVEA | "Automóveis e Comerciais Leves": passenger cars + light commercial vehicles. Queried from ANFAVEA's Central de Dados as `total_leves` (until 2026-09: the first block of the yearly workbook's sheet III — same scope). | Caminhões e Ônibus (trucks + buses, `total_pesados`): different fuel taxonomy, not queried. | ANFAVEA classification (industry self-definition); no single legal decree referenced. |
| Japan | JADA | **Standard passenger cars only (kei cars excluded).** 登録車 *(tōrokusha, "registered vehicles": engine > 660 cc **or** length > 3.40 m / width > 1.48 m / height > 2.00 m — no formal weight cap, but in practice ≈ LDV / EU M1; almost all under 3.5 t)*: the 乗用車計 *(jōyōsha-kei, "passenger car total")* row of JADA's "燃料別メーカー別登録台数（乗用車）" *("Registrations by fuel type × maker (passenger cars)")* file. Covers domestic + 輸入車 *(yunyū-sha, imported)* passenger cars across all reported makers. | 軽自動車 *(kei jidōsha, "light vehicles": engine ≤ 660 cc **and** length ≤ 3.40 m / width ≤ 1.48 m / height ≤ 2.00 m — typically 700-1000 kg; ~35-40 % of Japan's new-car market)*: explicitly excluded by JADA's footer "２．軽自動車は含みません。" *("2. Kei cars not included.")*. Trucks and buses are not on this page either (JADA publishes them separately under pages/343/). | 道路運送車両法 *(Dōro Unsō Sharyō Hō, Road Transport Vehicle Act)*. The 登録車 vs 軽自動車 split follows engine displacement **and** body dimensions (no weight cutoff, unlike EU/US/Chile); JADA covers the former, 全国軽自動車協会連合会 *(Zenkei-jikyō, Japan Light Motor Vehicle & Motorcycle Association)* covers the latter. |
| Uruguay | ACAU | **AUTOS + SUV** sheets of the yearly "Compilado YYYY" workbook, summed together. AUTOS covers turismos (sedans, hatchbacks, coupés); SUV covers utility vehicles. Per-model rows with monthly volumes. | MINIBUSES, UTILITARIO (light commercial / pickups), CAMIONES (medium/heavy trucks, would be an HDV candidate), OMNIBUS (buses) — separate sheets in the same workbook, all currently out of scope (no HDV CSV variant exists for Uruguay yet). | ACAU industry-self definition. No single regulatory decree referenced; the IMESI tax-category column (`F`/`F1`/`F2`/`F3`/`F6`) is the closest proxy to a legal classification on the file. |
| USA | ANL (Argonne National Laboratory) | **Light-Duty Vehicles (LDV):** passenger cars + light trucks (US "light-duty" ≈ GVWR ≤ 8,500 lb / 3,856 kg). ANL's "Total Sales" table reports BEV / PHEV / HEV / Total LDV per month; ICE is derived as `TOTAL − BEV − PHEV − HEV`. | Medium- and heavy-duty trucks and buses are not in this table. | ANL Energy Systems & Infrastructure Analysis division; figures aggregate OEM/registration data (e.g. HW/Wards/Hawaii DBEDT lineage seen in older `source` cells). |
| Canada | StatCan (cube 20-10-0025) | **`Whole` = EU M1:** `Passenger cars` + `Multi-purpose vehicles` (SUVs/crossovers). StatCan splits SUVs out as their own body type, so M1 must sum the two — matching how every other country counts passenger cars. Quarterly; M1 fuel split from ~2017. Also `Pickups` (Pickup trucks) and `Vans` (minivans + cargo vans) as **Canada-specific** variants (not EU N1/N2). **Definition change:** `Whole` was historically passenger-cars-only; pre-2017 rows dropped. | Heavy trucks (> class 3) and buses are not in this light-vehicle cube. | Statistics Canada, "New motor vehicle registrations" (table 20-10-0025-01); vehicle-type footnotes: MPV = "SUVs and Crossovers", Pickups = "GVWR 0–14,000 lb (classes 1–3)", Vans = "all minivans and cargo vans". |
| Indonesia | GAIKINDO | **`Whole` = GAIKINDO "Passenger Car"**: Sedan + 4x2 + 4x4 + LCGC ("KBM Hemat Energi & Terjangkau" / Affordable Energy Saving Cars) — ≈ EU M1. **Wholesales** (factory→dealer), not registrations. Also `Pickups` (pick ups GVW < 5 t + double cabins), `HDV` (trucks ≥ 5 t incl. tractor heads) and `Buses` as variants — together exactly GAIKINDO's "Commercial Vehicle" block. | Nothing dropped: sections 1–7 of the wholesales PDF map completely onto the four series (checksummed against the PDF's own PC/CV/DOMESTIC summary rows). | GAIKINDO wholesales-PDF sheet structure (sections 1–7 + PASSENGER CAR / COMMERCIAL VEHICLE summary); see [30-source-indonesia.md](30-source-indonesia.md). |
| Nepal | Department of Customs (FTS) | **`Whole` = HS 8703 imports minus three-wheelers**: motor cars, jeeps & vans principally designed for the transport of persons (≈ EU M1). Figures are **customs imports**, not registrations — Nepal has no domestic car production, so import ≈ market. `3-Wheelers` = passenger three-wheelers within 8703 (petrol auto-rickshaws + electric e-rickshaws). Nepali fiscal months (mid-month → mid-month) are labelled by their Gregorian end month. | Buses & 10+-seat vans (HS 8702, incl. Nepal's large electric mini/microbus segment), goods vehicles/pickups (8704), motorcycles (8711). Hybrids are a single combined bucket (PHEV/HEV split in the tariff codes is unreliable). | WCO HS 2022 heading 87.03 (vehicles principally for the transport of <10 persons); Nepal 8-digit national tariff splits. See [32-source-nepal.md](32-source-nepal.md). |
| Others | various | *To be documented per country as the scope is confirmed by the maintainer or pulled from the agency's methodology page.* | — | — |

**Why this matters:** the headline BEV-share number for a country is `BEV_count / TOTAL_count`, and `TOTAL` is exactly the count of vehicles within that source's scope. Different scopes are not directly comparable — Chile counting up to 3.860 t is broader than EU `M1+N1` (≤ 3.5 t) but narrower than US light-duty (≤ 8.500 lb ≈ 3.856 t); Japan's 登録車 has no explicit weight cap but is dimension-gated and in practice sits in the same LDV neighbourhood (excluding the ~35-40 % kei-car segment entirely). Document scope before comparing absolute volumes across countries.

## Variant definitions (canonical)

A **variant** is a within-country slice rendered as its own gallery entry (own CSV `data/<Country>_<Variant>.csv`, own `params.csv`/`weights.csv` row, own slug/flag). This is the single reference for what each variant *means*; the per-country source playbooks (10–16) give the exact source category. The intended definition is anchored to the **EU vehicle-category classes** so variants are comparable across countries:

> EU classes: **M1** = passenger cars (≤ 8 seats besides driver) · **M2/M3** = buses & coaches (> 8 seats; M2 ≤ 5 t, M3 > 5 t) · **N1** = goods vehicles ≤ 3.5 t · **N2** = goods 3.5–12 t · **N3** = goods > 12 t.

| Variant | Canonical meaning | EU class | Notes |
|---|---|---|---|
| `Whole` | The country's headline new-registration series — **passenger cars** (the default slice; UI label "New Cars"). | M1 | What `data/<Country>.csv` (no suffix) holds. The world map + cross-country rankings use this. |
| `Private` | Passenger cars registered to **private persons / households**. | M1 | Subset of Whole. |
| `Industry` | Passenger cars **not** registered to private persons (companies, state, etc.). | M1 | Defined as `Whole − Private` where the source has no direct "industry" bucket (Finland), or a direct "in industries" category (Denmark). `Private + Industry = Whole`. |
| `Used` | **Used vehicles at their first national registration** — in practice used **imports** (the car was registered abroad before). Changes of owner within the country are *not* `Used` (see `Resale`). | M1 | **Netherlands** (imported used cars at first Dutch registration), **Hong Kong** (private cars registered abroad before import — TD status C2), **Spain** (used cars at their first Spanish registration — overwhelmingly imports), **Ukraine** (used imports at their first Ukrainian registration, by the register's operation codes) and **Latvia** (a legacy series with no CSV in this repo — definition not re-verified against this rule). A different population from every other variant, which are *new* registrations. |
| `Resale` | **Reserved, not built.** Used vehicles changing owner *within* the country (second or later national registration). | M1 | No country yet. Ukraine's register carries it (change-of-owner operation codes; IAR's August-2026 EV market of 9,074 = 504 new + 3,613 used imports + 4,957 resales). Kept separate from `Used` so a used-import series is never mixed with domestic turnover. |
| `Vans` | **Light commercial** goods vehicles (vans, pickups). | **N1** (≤ 3.5 t) | |
| `HDV` | **Heavy goods** vehicles (lorries / trucks — freight, not people). | **N2 + N3** (> 3.5 t) | See the cross-country deviation note below. |
| `Buses` | **Buses & coaches.** | **M2 + M3** | Very low volume in most countries → lumpy, batch-driven fleet orders make the TTM share swing hard (this is real, not a bug — see e.g. Ireland Buses). |
| `Rental` | Passenger cars registered to the **short-/long-term rental channel**. | M1 | **Italy** ("noleggio": `Rental = Whole − al netto del noleggio` from the UNRAE PDF; real from `2019-06`, **estimated before that** and flagged in `notes`) and **Spain** (registry-side: `SERVICIO = A01 alquiler sin conductor` or `RENTING = S`). `Rental + NonRental = Whole` in both. |
| `NonRental` | Passenger cars registered **outside** the rental channel (private + company + self-registration). | M1 | **Italy** (the UNRAE "al netto del noleggio" block, read directly — `Rental` is the derived complement) and **Spain** (the exact complement of `Rental`). Note this is *not* a private-persons slice: no per-fuel private-only split exists in either source. |

> **Italy estimated history.** Both `Rental` and `NonRental` are *real* from
> `2019-06` (first UNRAE bulletin with the rental block) and **modelled** for
> `2015-01 … 2019-05` by applying the 2019-H2 per-fuel rental share to `Whole`.
> Every estimated row is flagged in its `notes` column; `2020-04` is omitted
> from both (COVID-lockdown data anomaly). See
> [18-source-italy.md](18-source-italy.md) and
> [03-data-objects.md § Estimated-value convention](03-data-objects.md).

> **`Whole` that includes used imports — the Albania exception.** `Whole`
> is meant to be *new* registrations. Albania's source (DPSHTRR open data)
> publishes only *first registrations* with no new/used dimension (the
> report exposes vehicle type, fuel and month only), so `Albania.csv` `Whole`
> = new **+ imported used** — i.e. it overlaps what `Used` means elsewhere,
> and is not comparable to new-only `Whole` series (~5× the new-car total,
> [27-source-albania.md](27-source-albania.md)). **Open item:** split used
> first registrations into `Albania_Used` (leaving a new-only `Whole`) if a
> probe finds a model-year or new/used field in the report's datasource;
> until then the footnote flags it.

### Per-country variant → source category

| Country | Whole | Private | Industry | Vans (N1) | HDV (N2/N3) | Buses (M2/M3) |
|---|---|---|---|---|---|---|
| Albania | First registrations of M1 passenger cars (Autovetura), new and imported used | — | — | — | First registrations of heavy goods vehicles | First registrations of buses |
| Argentina | New registrations of passenger-car body types (sedán, rural, todo terreno, coupé, …) ≈ M1 | Whole ∧ first owner a natural person (persona física) | Whole ∧ first owner a legal person (persona jurídica) | — | — | — |
| Austria | New passenger cars, class M1 (Pkw) | — | — | Lorries N1, up to 3.5 t | Lorries N2 + N3 plus articulated tractors (Sattelzugfahrzeuge) | — |
| Belgium | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Bulgaria | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Canada | Passenger cars + multi-purpose vehicles (SUVs/crossovers) = EU class M1 | — | — | Minivans + cargo vans — Canada-specific, mixes M1 and N1 | — | — |
| China | Retail (零售) — passenger cars reaching end customers in mainland China | — | — | — | — | — |
| Croatia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Cyprus | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Czechia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Denmark | All new passenger-car registrations (BILTYPE 4000101002, all owners) | New passenger cars registered in households (BRUG 1100) | New passenger cars registered in industries (BRUG 1200) | New vans (BILTYPE 4000102000) | New lorries (BILTYPE 4000103000) | — |
| Estonia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Finland | First registrations of passenger cars, all possessors (vehicle class 01) | Passenger cars whose possessor is a private person | Derived cell-by-cell as possessor Total minus Private person | Vans (vehicle class 02) | Lorries over 3.5 t (vehicle class 03) | Buses and coaches (vehicle class 04) — very low volume |
| France | SDES registry série — new EU M1 passenger cars | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report — France has no national Vans/HDV/Buses source, unlike its own SDES `Whole` |
| Germany | KBA press release — new passenger cars | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report — Germany has no national Vans/HDV/Buses source, unlike its own KBA `Whole` |
| Greece | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Hong Kong | New private cars (TD class Private Car, first-registration status A/B/C1 ≈ M1) | — | — | New light goods vehicles ≤ 3.5 t (TD class LGV, status A/B/C1/E, N1) | — | — |
| Hungary | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Iceland | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| India | New passenger cars = EU M1 (VAHAN Vehicle Class MOTOR CAR + MOTOR CAB + LUXURY CAB) | — | — | — | — | — |
| Indonesia | GAIKINDO Passenger Car — Sedan + 4x2 + 4x4 + LCGC | — | — | — | Trucks of 5 t and above | Buses |
| Ireland | New passenger-car registrations | — | — | New light commercial vehicles (SIMI LCV) | New heavy commercial vehicles (SIMI HCV) | New buses and coaches |
| Israel | New private passenger cars — MoT registry `sug_degem` = P, from 2017-01 | — | — | New light commercial vehicles up to 3.5 t — registry `sug_degem` = M (N1) | — | — |
| Italy | Passenger cars, whole market including rental | — | — | Light commercial vehicles, derived from published percentage shares | — | — |
| Latvia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Lithuania | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Luxembourg | New car registrations (VEHICLE_TYPE = CAR) | — | — | New van registrations (VEHICLE_TYPE = VAN) | Trucks + buses + road tractors combined | — (STATEC has no separate Buses category; deliberately not filled from ACEA — see 38-source-acea-cv.md § 1a) |
| Malta | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report — some releases omit Malta entirely (footnoted "Data for Malta not available"), so coverage is patchier than the rest of the roster |
| Nepal | HS 8703 imports — cars, jeeps and vans (approximately EU M1), excluding three-wheelers | — | — | — | — | — |
| Netherlands | New passenger cars (Instroom Personenauto Nieuw) | — | — | — | New heavy commercial vehicles (Zware bedrijfsvoertuigen) — broader than EU N2/N3 | — |
| Norway | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Poland | New passenger cars (OSOBOWE, M1) | — | — | Light commercial vehicles up to 3.5 t (SAMOCHODY DOSTAWCZE, N1) | Trucks over 3.5 t (SAMOCHODY CIEZAROWE POW. 3,5T, N2/N3) | Buses (AUTOBUSY, M2/M3) |
| Portugal | New passenger cars — Ligeiros de Passageiros (M1) | — | — | Light commercials — Ligeiros de Mercadorias (N1, ≤ 3.5 t) | Heavy goods vehicles incl. tractor units — Pesados de Mercadorias (N2/N3) | Buses and coaches — Pesados de Passageiros (M2/M3) |
| Romania | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Slovakia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Slovenia | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Spain | New turismos + todoterrenos (registry-side passenger cars, incl. M1 people movers) | — | — | New EU N1 (incl. N1G) light commercials | New EU N2/N3 trucks | New EU M2/M3 buses and coaches |
| Sweden | SCB PxWeb PersBilarDrivMedel — new passenger cars | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report — Sweden has no national Vans/HDV/Buses source, unlike its own SCB `Whole` |
| Switzerland | New passenger-car registrations, via ACEA | — | — | New van registrations (N1, ≤ 3.5 t), via ACEA's Commercial Vehicle report | New truck registrations (N2+N3, > 3.5 t combined), via ACEA's Commercial Vehicle report — the BFS-direct legacy series (pxweb.bfs.admin.ch) mentioned in older docs was never built; this is the live one | New bus & coach registrations (M2+M3), via ACEA's Commercial Vehicle report |
| Thailand | Passenger Car and Pickup Truck — the AIU category; pickups are bundled in and cannot be separated | — | — | — | Truck category | Bus category |
| Ukraine | New passenger cars (register kind ЛЕГКОВИЙ, M1) by the MIA register's new-vehicle first-registration codes | Whole ∧ owner a natural person (PERSON P) | Whole ∧ owner a legal person (PERSON J) | New goods vehicles (ВАНТАЖНИЙ) with gross weight ≤ 3,500 kg | — | — |
| Uruguay | AUTOS + SUV worksheets combined | — | — | UTILITARIO worksheet | CAMIONES worksheet | OMNIBUS worksheet |

> **ACEA Commercial Vehicle rows above** (Belgium, Bulgaria, Croatia, Cyprus,
> Czechia, Estonia, France, Germany, Greece, Hungary, Iceland, Latvia,
> Lithuania, Malta, Norway, Romania, Slovakia, Slovenia, Sweden, Switzerland
> — a maintainer-curated roster, not the same list `fetch_acea.py` uses for
> passenger cars; see [38-source-acea-cv.md § 1a](38-source-acea-cv.md)) are
> **quarterly from ~2024 onward** (`Q1`/`Q2`/`Q3`/`Q4`, reconstructed from
> ACEA's cumulative Q1/H1/Q1-Q3/FY checkpoints — see
> [38-source-acea-cv.md](38-source-acea-cv.md)) and **yearly** for any year
> where no quarterly baseline exists yet (every year through 2023, plus a
> country/variant's first bootstrap year). From ~2024 onward the chart
> label reads `EV`, not `BEV`, because ACEA reports a combined
> "Electrically Chargeable Vehicle" bucket (BEV+PHEV together) for
> commercial vehicles — not a pure-BEV count. See `footnotes.csv`.

Single-variant countries (`Whole` only) are omitted. This table is generated
from the same front-matter that drives the public source pages, so the two
cannot drift apart.

### Variants outside the EU core six

Some countries expose slices that deliberately don't map onto M1/N1/N2/N3/M2/M3.
They render their own trajectories but are **not** part of any cross-country
`Vans`/`HDV`/`Buses` ranking:

- **Albania** — `2-Wheelers` (First registrations of motorcycles and mopeds)
- **Argentina** — `Pickups` (every new PICK-UP body type — simple, doble, cabina y media, carrozada; overwhelmingly N1, no weight field to confirm it). **Data only**: the CSV is kept current but never rendered or shown in the gallery
- **Canada** — `Pickups` (Pickup trucks, GVWR up to 14,000 lb — Canada-specific, not EU N1)
- **China** — `Wholesale` (Wholesale (批发) — manufacturer shipments to dealers, includes exports)
- **Hong Kong** — `Used` (Private cars registered abroad before import — used imports, TD first-registration status C2)
- **India** — `4-Wheelers` (Cars and other four-wheelers); `3-Wheelers` (Auto-rickshaws and other three-wheelers); `2-Wheelers` (Motorcycles, scooters and mopeds — by far India's largest segment)
- **Indonesia** — `Pickups` (Pick-ups under 5 t plus double cabins)
- **Italy** — `Rental` (Rental fleet, derived exactly as Whole minus NonRental); `NonRental` (Passenger cars al netto del noleggio — private buyers, companies and self-registrations)
- **Latvia** — `Used` (Used-import registrations — a legacy series rendered from the maintainer's local pipeline; the CSV is not in this repo and it is not ACEA-sourced)
- **Nepal** — `3-Wheelers` (Passenger three-wheelers — petrol auto-rickshaws and electric e-rickshaws)
- **Netherlands** — `Used` (Imported used passenger cars at first Dutch registration (Personenauto Occasion import))
- **Spain** — `Rental` (Whole where the vehicle is rent-a-car or renting/leasing); `NonRental` (Whole minus Rental — the exact complement); `Used` (Used cars at their first Spanish registration — overwhelmingly used imports); `2-Wheelers` (New EU L-category motorcycles and mopeds)
- **Thailand** — `3-Wheelers` (Three Wheelers category — tiny volumes, high BEV share)
- **Ukraine** — `Used` (Used passenger cars at their first Ukrainian registration — used imports, by the MIA register's used-vehicle operation codes)

**Canada's `Whole` sums two StatCan body types** to reconstruct M1, because
StatCan reports SUVs/crossovers (`Multi-purpose vehicles`) separately from
`Passenger cars` — see [17-source-canada.md](17-source-canada.md). Canada also
publishes two **Canada-specific** variants that intentionally fall outside the
EU columns above: `Pickups` (Pickup trucks, GVWR up to ~6.35 t — into N2) and
`Vans` (minivans **and** cargo vans — mixed M1/N1). They are not used in the
cross-country `Vans`/`HDV` rankings.

### Known HDV deviation (documented, accepted)

The HDV intent is "heavy goods vehicles > 3.5 t = N2 + N3". Most sources expose exactly that as one bucket (Ireland Heavy Commercial, Portugal Pesados de Mercadorias, Finland Lorries > 3.5 t, Netherlands Zware bedrijfsvoertuigen) — **including articulated tractor / road-tractor units**. **Denmark is deliberately narrower**: BIL53 lists "Lorries" and "Road tractors" as separate categories and our Denmark HDV takes **only Lorries** (excluding road tractors), because at the time that was the cleaner single bucket. So Denmark HDV slightly under-counts vs the others' full N2+N3. Both are defensible "heavy goods" definitions; the difference is recorded here and in [11-source-denmark.md](11-source-denmark.md). If exact cross-country HDV comparability ever matters, add Denmark's road-tractor category to its HDV.


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
| **variant** | A within-country slice | `Whole` (default — labelled "New Cars" in the UI), `Custom`, `HDV`, `Vans`, `Private`, `Industry`, `Rental`, `NonRental`, `2-Wheelers`, `3-Wheelers`, `4-Wheelers`, `Used`, `Used Imports`, `Fleet` |
| **type** (in chart filenames) | One of the four canonical chart types | empty (BEV trajectory), `ICE_BEV`, `time`, `ttm_shares` |

## Model parameters

| Term | Meaning |
|---|---|
| **v1, v2, t0** | The three parameters of the BEV-curve fit. The canonical **calendar-year** form is `S(C) = 1 − exp(v1 × (C − t0)^v2)` where `C` is a fractional calendar year (e.g. 2026.5 = mid-2026). `t0` is the integer floor of the earliest **calendar** year present in the raw data for that country (= R's `verschiebung`). The threshold crossing year is `C = t0 + (ln(1−y)/v1)^(1/v2)`. ⚠️ **Historical gotcha:** `R/fit.R` fits on `period_to_year()`-encoded years where `period_to_year("YYYY-MM") = (year − 1) + (month − 1)/12` — one less than the calendar year. `verschiebung = floor(min(df$year_R))` is therefore also one less than the calendar year. `R/plots.R` re-adds +1 at axis-label time (`labels = "Jan " + (x+1)`). The JS `inv_x_years` historically returned `(t0 − 1) + delta` (R-internal units, one year too low for calendar display); **corrected in 2026-06 to return the calendar year `t0 + delta`**. Duration differences are unaffected by the shift. |
| **ice_v1, ice_v2, ice_t0** | Same shape, fit independently on the ICE share. |
| **verschiebung** | Internal R variable for `t0`. In R-internal space equals `floor(min(year_R)) = t0_calendar − 1` (because `period_to_year` subtracts one). R re-adds +1 when printing axis labels (`plots.R`: `labels = "Jan " + (x+1)`). Historical name kept because the math comes from a German R script and renaming it would obscure the byte-for-byte invariant. |
| **extrapol** | The integer year the regression extrapolates to. Currently 2200, far enough that all countries cross every meaningful threshold. |
| **no transition** | A curve is flagged "no transition" when `v2 ≤ 1` (no inflection point — not a structural S-curve) **or** the slope at the inflection point is below 1 percentage-point/year (`MIN_TRANSITION_SLOPE = 0.01` in `index.html`). At 1 pp/yr the 25→75 % segment alone takes >50 years. Such rows show a single "No transition" pill instead of Status/Speed/Timing tags, sort to the bottom of ranking tables, and are excluded from the Time Interval chart. The threshold constant is the single tunable. |
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
| **Builder** | The in-page tab that plots weighted aggregate BEV/ICE/PHEV curves over an arbitrary country set. Since the 2026-09 redesign it plots real monthly dates and **ICE and PHEV always draw** — the old "Show ICE & PHEV" toggle was removed (`showICE` is now a `const true`). Not to be confused with `scripts/snapshot_builder.py`, which freezes the same aggregation into `builder_history/`. |
| **hero chart** | The inline-SVG chart on the landing section (`#galHeroPlot`). Hand-rolled rather than Plotly so first paint doesn't wait on the library; its country comes from the browser timezone, never an IP lookup. |
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
