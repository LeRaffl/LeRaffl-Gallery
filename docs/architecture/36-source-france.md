# 36 · Source findings: France — why our numbers differ from other sources (and the SDES migration plan)

**Status: INVESTIGATION / DECISION-PENDING.** France is still served by
`fetch_acea.py` (stub `country_source_stubs.yaml`, `data/France.csv`,
`source = ACEA`). This document records *why the French market prints
different numbers in different places* — the answer people ask when they see
our figure next to an SDES headline or an AAA press release — and the plan to
move France onto a national primary source (SDES) without breaking the series.

It is written to be the **ready answer** to two recurring questions:

1. "Why does your France number differ from ACEA / SDES / AAA?"
2. "Where are the SUVs / pickups / trucks / vans in these figures?"

Both are answered **fachlich** (definitions: what is counted, what is a
rounding, what is a correction) and **technisch** (lineage, access, cadence).

## TL;DR

There is **one registry** behind every French figure — the **SIV** (Système
d'Immatriculation des Véhicules, Ministry of the Interior). The numbers differ
only because each publisher applies a different **scope**, **adjustment**, and
**energy taxonomy** on top of it. Worked example, **June 2026, passenger cars
(VP / EU M1)**:

| Figure | June 2026 VP | vs. ACEA | What it is |
|---|---:|---|---|
| **ACEA** (our `data/France.csv`) | **188 787** | — | raw registrations, aggregated from PFA |
| **AAA-DATA** (press / the brand tables) | **188 787** | **±0** | raw registrations, the SIV processor — *same number as ACEA* |
| **PFA / CCFA** ("Immatriculations mensuelles par énergie") | = AAA | ≈ 0 | raw registrations, the industry association ACEA aggregates |
| **SDES — données brutes** | **188 500** | −0,15 % | raw registrations, registry statistics (rounded to the hundred) |
| **SDES — CVS-CJO** (the headline in most SDES/press write-ups) | **142 100** | −24,6 % | **seasonally- and working-day-adjusted** — *not a raw count* |

Two independent exact matches prove the lineage: our stored ACEA figure equals
the AAA number to the unit in **August 2025 (87 849 = 87 849)** and **June 2026
(188 787 = 188 787)**. So **our France series already is the raw French market
number.** The only large discrepancy a reader will hit — the "33 % too high"
illusion — is **raw vs. CVS-CJO**, i.e. comparing our raw count against SDES's
*adjusted* headline. It is a definitional artefact, not an error on either side.

## 1. The France series today

- `data/France.csv`, variant `Whole` only, monthly since 2015-01, full
  BEV/PHEV/HEV/PETROL/DIESEL/OTHERS split, `source = ACEA`, written by
  `fetch_acea.py` on the shared ACEA cron (publishes ~3rd–4th week of the
  following month). There is **no `fetch_france.py`**.
- France is one of the few large markets still on the ACEA *aggregate* rather
  than its own national registry — unlike Spain (DGT), Germany (KBA),
  Netherlands (RDW), Italy (UNRAE), Sweden (SCB), Portugal (ACAP), etc. The
  stub even names the true origin: *"National registrations (PFA/SDES),
  aggregated by ACEA."*
- Reference split we validate against (ACEA, June 2026): BEV **55 851** ·
  PHEV **12 300** · HEV **79 773** · PETROL **28 807** · DIESEL **4 955** ·
  OTHERS **7 101** · TOTAL **188 787**.

## 2. One registry, many products (the lineage)

```
                         SIV  (Système d'Immatriculation des Véhicules)
                         Ministère de l'Intérieur — the registration event
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              ▼                          ▼                         ▼
   SDES (Min. Transition écol.)   AAA-DATA (private SIV       (national market
   registry statistics:          processor) ──► PFA/CCFA       feed)
   • données brutes              (Plateforme Automobile,           │
   • données CVS-CJO             industry association)             ▼
   • détail « motorisations »          │                        ACEA
                                       └──── same raw number ──► (EU-wide
                                                                 aggregate,
                                                                 what we ingest)
```

Everything starts at the SIV. **AAA-DATA = PFA/CCFA = ACEA** are the same raw
market number at three points of the same chain (private processor → industry
association → European aggregate). **SDES** is the *statistical* branch: same
registry, but it publishes a raw series, an adjusted series, and a detailed
motorisation product — and it applies the government energy taxonomy.

## 3. Fachlich — why the numbers differ

### 3a. Scope: what "the French market" (`Whole`) counts

`Whole` is **EU category M1** — *voitures particulières* (VP): vehicles for
carrying passengers, ≤ 9 seats incl. driver, ≤ 3,5 t. Crucially:

- **SUVs and crossovers ARE M1** — there is no separate "SUV" line anywhere;
  they are already inside the passenger-car total (ACEA's own definition:
  "small cars and sports utility vehicles (SUVs)").
- **Pickups, vans, trucks, buses are NOT in `Whole`.** Pickups and car-derived
  "dérivé VP" vehicles are homologated **N1** (VUL / light commercial); trucks
  are **N2/N3**; buses/coaches are **M2/M3**. See the reference table in §5.

This matters because **ACEA "new car registrations" = M1 = VP**, and so does
SDES's VP series. The ACEA↔SDES difference is therefore **not** a scope gap —
both count the same M1 universe. (Contrast Spain, where the DGT-vs-ACEA gap
*is* a scope/definition difference over M1 people-movers — see
[28-source-spain.md](28-source-spain.md) §4. France does not have that.)

### 3b. The big one: raw vs. CVS-CJO (a *correction*, not a count)

SDES publishes each month in **three** forms; press write-ups usually quote the
**CVS-CJO** one:

- **Données brutes** — the actual number of registrations in the calendar
  month. This is what ACEA/AAA/PFA report, and what our series holds.
- **CVS-CJO** — *corrigées des variations saisonnières et des jours ouvrables*:
  seasonally adjusted **and** working-day adjusted. It removes the calendar so
  months are comparable as a trend. It is **not** a headcount and must never be
  compared to a raw figure.

June 2026 makes the trap concrete: **22 working days vs. 20 in June 2025**, so
the raw count is **188 787 (+11 % YoY)** while the working-day-corrected change
is only **≈ +1,25 %**, and the CVS-CJO *level* is **142 100**. A reader who sets
our 188 787 against the 142 100 headline "sees" a 33 % overcount that is
entirely the adjustment.

**Rule for the gallery:** we track **raw registrations** (the flow the model is
built on). Compare only against other **brut** figures (ACEA, AAA/PFA, SDES
*données brutes*), never against CVS-CJO.

### 3c. Provisional, transit-temporary, and consolidation (the small residual)

The **188 787 (ACEA/AAA) vs. 188 500 (SDES brut)** gap is ≈ 0,15 % and comes
from definitional edges, not error:

- SDES *données brutes* is explicitly **"hors immatriculations provisoires et
  transit temporaire"** (excludes provisional plates and temporary/WW transit
  registrations); AAA's market figure treats these slightly differently.
- **Extraction cut-off**: SDES and AAA freeze the month on marginally different
  dates; late-arriving registrations shift a few hundred units.
- **Provisional → consolidated revisions**: an early monthly figure is revised
  as late records land. This is a *correction over time*, not a discrepancy at
  a point in time.

### 3d. Métropole vs. France entière (DOM/COM)

SDES publishes **France métropolitaine** and **France entière** (incl. overseas
départements). AAA/PFA "marché France" is France entière. Mixing the two adds a
low-single-digit-percent wobble. When we ingest SDES we must pick **France
entière** to line up with the ACEA/AAA baseline.

### 3e. ACEA restatement and roundings

- Each ACEA release **restates the same month one year earlier**, so a
  prior-year France figure can change retroactively.
- **Roundings**: SDES *headline* numbers are rounded (142 100, 147 700,
  188 500 — to the hundred); AAA/ACEA and the SDES *data files* carry exact
  integers (188 787). A "difference" of a few dozen units is usually just the
  rounded headline vs. the exact file.

### 3f. Energy taxonomy — where HEV, FCEV, GPL/GNV, MHEV land

This is the subtle one, and it differs **by SDES product**:

- **ACEA / AAA / PFA** split the six buckets we use directly: BEV, PHEV, **HEV
  (own line)**, PETROL, DIESEL, OTHERS. This is why our current France series
  has a clean HEV column.
- **SDES *coarse* énergie** (the machine-readable "source d'énergie" used in the
  data.gouv / Insee open data) has only **6 buckets that fold HEV into
  petrol/diesel**: `électrique + hydrogène` · `hybride rechargeable` ·
  `essence (thermique OU hybride non rechargeable)` · `diesel (thermique OU
  HNR)` · `gaz` · `autres`. Taken as-is this **loses the HEV column** — coarser
  than what we have today.
- **SDES *detailed* "Motorisations des véhicules légers neufs"** (monthly xlsx)
  **does** separate `essence hybride non rechargeable` and `gazole HNR` from
  pure thermique, with unit counts — so HEV is recoverable.

Bucket edges to keep straight (per [09-glossary.md](09-glossary.md)): **FCEV /
hydrogène** → we put in OTHERS (SDES groups it with électrique — a few
hundred units/yr); **GPL / GNV (gaz)** → OTHERS; **MHEV (mild hybrid)** → folded
into PETROL/DIESEL (ICE) by everyone here, never its own line; **EREV** → not
separately reported in France.

## 4. Technisch — how each product is accessed

| Product | Access | Format | HEV split? | Cadence / lag |
|---|---|---|---|---|
| **ACEA** (today) | `www.acea.auto` press PDF | PDF parse (`fetch_acea.py`) | ✅ | monthly, 3rd–4th week after month-end |
| **AAA-DATA** | `aaa-data.fr` press releases; some data.gouv datasets | PDF / prose; a few CSV | ✅ | monthly, ~1st business day |
| **PFA / CCFA** | `ccfa.fr` "Immatriculations mensuelles par énergie" | **PDF only** (no public API; gated table via `ecostats@ccfa.fr`) | ✅ | monthly, ~1st |
| **SDES — total** (VP brut) | **Insee BDM API**, idbank `010756763` (brut) / `010756764` (CVS-CJO); data.gouv tabular API; SDES DiDo API | JSON / CSV — **clean API** | ❌ (total only) | monthly |
| **SDES — coarse énergie** | data.gouv / ecologie.data.gouv "part … par source d'énergie"; DiDo | CSV / API | ❌ (HEV folded) | monthly/annual |
| **SDES — detailed motorisation** | "Motorisations des véhicules légers neufs" publication page → `media/<id>/download` | **xlsx per month** (~25 KB) | ✅ | monthly |

The tension in one line: **the clean SDES API gives no HEV column; the SDES
product that keeps HEV is a per-month xlsx.** PFA/CCFA keeps HEV but is
PDF-only. There is no French source that is *simultaneously* a clean API **and**
carries a native HEV split.

## 5. "What is in which variant?" — the idiot-proof reference

The question users actually ask. `Whole` is M1 only; the commercial categories
are separate series (not yet built for France — see §6).

| Vehicle | Lands in | Why |
|---|---|---|
| Normal car, hatchback, saloon, estate | **Whole** | VP / M1 |
| **SUV, crossover** (any size) | **Whole** | SUVs are M1 passenger cars — no separate line |
| MPV / people-mover registered as a passenger car | **Whole** | M1 (≤ 9 seats) |
| Taxi, driving-school car, ambulance *car* | **Whole** | still M1; usage doesn't change the category |
| **Pickup** (Hilux, Ranger, …) | **Vans** (N1) | homologated N1 utilitaire in France, not a passenger car |
| Car-derived van, "dérivé VP" (rear seats removed) | **Vans** (N1) | reclassified VUL on the carte grise |
| Panel van, Kangoo/Berlingo cargo, Transit ≤ 3,5 t | **Vans** (N1) | VUL |
| Truck > 3,5 t, rigid or tractor unit | **HDV** (N2/N3) | poids lourds |
| City bus, coach, minibus > 9 seats | **Buses** (M2/M3) | transport en commun |
| Motorhome / camping-car | **nowhere** | own genre (VASP), neither M1 nor N1 |
| Motorcycle, scooter, quad | **nowhere** | EU L-category — no French variant built |
| Agricultural tractor, machinery | **nowhere** | category T / special |
| Used-import car (first French plate) | **nowhere** | our France series is **new** registrations only |

Rules of thumb: `Whole` = **new M1 passenger cars incl. SUVs**; everything that
carries goods (pickups, vans) is N1 = `Vans`; > 3,5 t goods = `HDV`; > 9-seat
people-carriers = `Buses`. SUVs are the one people second-guess — they are
**in** `Whole`, always.

## 6. FAQ (drive-by answers)

- **"Why does ACEA differ from the SDES figure I saw?"** It almost certainly
  doesn't — you compared our **raw** count to SDES's **CVS-CJO** (seasonally +
  working-day adjusted) headline. Against SDES *données brutes* the gap is
  ~0,15 % (provisional/transit-temporary + cut-off). See §3b/§3c.
- **"Where are the SUVs?"** Inside `Whole`. SUVs/crossovers are M1 passenger
  cars; there is no separate SUV figure to add.
- **"Where are pickups / trucks / vans?"** Not in `Whole`. Pickups and vans are
  N1 (a future `Vans` variant), trucks are N2/N3 (`HDV`), buses M2/M3
  (`Buses`). SDES publishes all of these as their own series, so they can be
  added natively later — see §7.
- **"June is +11 % but everyone says the market is flat?"** June 2026 had two
  extra working days vs. June 2025; working-day-adjusted the market was ≈ +1,25 %.
  The +11 % is a raw/calendar effect, which is exactly what CVS-CJO removes.
- **"Is our number complete (all brands)?"** Yes — it is registry-derived
  (every registration, every brand), so it does not have the
  association-membership completeness problem that shelves some other markets
  (see [14-data-source-gaps.md](14-data-source-gaps.md)).

## 7. Migration plan (decided so far)

Direction chosen by the maintainer: **move France onto SDES** (registry-primary,
via API), keeping `Whole` consistent with the ACEA target. Given §3f/§4, the
concrete pick is **SDES Path 2 — the detailed "Motorisations des véhicules
légers neufs" monthly file**, because it is the only SDES product that keeps a
real **HEV** column (the gallery's focus is the fuel split).

Mapping (finer than ACEA, so it can be validated against the ACEA target):

```
BEV     ← électrique
PHEV    ← hybride rechargeable (essence + gazole)
HEV     ← essence hybride non rechargeable + gazole HNR
PETROL  ← essence thermique
DIESEL  ← gazole thermique
OTHERS  ← gaz (GPL + GNV) + hydrogène/autres
TOTAL   ← sum   (validate ≈ ACEA 188 787 for 2026-06, France entière, brut)
```

Bonus: the same product is *véhicules légers*, so **VUL (Vans, N1)** comes along;
SDES separately publishes **PL (HDV, N2/N3)** and **TCP (Buses, M2/M3)** — so
France can gain `Vans` / `HDV` / `Buses` variants natively (the Spain/Portugal
pattern), which the current ACEA feed cannot provide.

Open items before a `fetch_france.py` lands:
- **Confirm Path 2** over the cleaner-but-HEV-less coarse API (Path 1).
- **Obtain a sample** of the monthly xlsx (egress blocks download here, §8) to
  build the parser against the real sheet layout, then validate the six-fuel
  split against the ACEA reference figures.
- On switch: use **France entière**, **données brutes**; give `fetch_france.py`
  the ACEA-courtesy rule (only overwrite a row whose `source` is exactly `ACEA`
  or already the new source string) so history is never silently redefined; add
  a `footnotes.csv` line (done — see below) and, when live, convert this doc's
  frontmatter into a page-driving source doc + retire the France stub in
  `country_source_stubs.yaml`.

## 8. Sandbox / network constraints hit during this investigation

Recorded so the next session doesn't rediscover them:

- The Claude sandbox egress proxy returns **CONNECT 403 (policy denial)** for
  *every* host involved — `api.insee.fr`, `tabular-api.data.gouv.fr`,
  `www.data.gouv.fr`, `statistiques.developpement-durable.gouv.fr`, `ccfa.fr`
  — and even for the sources our *existing* fetchers use (`api.statbank.dk`,
  `www.acea.auto`). So **nothing France-side is fetchable or testable from a
  sandbox session.** Like Spain (§7 there), the fetcher must be built against a
  provided sample and validated from GitHub Actions (unrestricted egress), or
  on the maintainer's machine.
- `WebSearch` works (different path) and was the basis for the figures here;
  `WebFetch` is egress-blocked for these domains.

## Sources

- SDES — [Immatriculation des véhicules routiers](https://www.statistiques.developpement-durable.gouv.fr/immatriculation-des-vehicules-routiers) ·
  [Motorisations des véhicules légers neufs (juillet 2026)](https://www.statistiques.developpement-durable.gouv.fr/motorisations-des-vehicules-legers-neufs-emissions-de-co2-et-bonus-ecologique-juillet-2026) ·
  [méthodologie immat. mensuelles CVS-CJO](https://www.statistiques.developpement-durable.gouv.fr/sites/default/files/2019-02/methodologie%20immat-mensuelles-cvs-cjo.pdf)
- Insee — [série 010756763 (VP neuves, données brutes)](https://www.insee.fr/fr/statistiques/serie/010756763) ·
  [série 010756764 (CVS-CJO)](https://www.insee.fr/fr/statistiques/serie/010756764)
- data.gouv — [Part de véhicules neufs par type de véhicule et par source d'énergie](https://www.data.gouv.fr/datasets/part-de-vehicules-neufs-par-type-de-vehicule-et-par-source-denergie)
- PFA/CCFA — [Immatriculations & baromètre des commandes](https://ccfa.fr/immatriculations-commandes/) ·
  [Immatriculations mensuelles par énergie (déc. 2025 PDF)](https://ccfa.fr/wp-content/uploads/2026/01/Immatriculations-mensuelles-par-energie_Decembre2025.pdf)
- AAA-DATA — [communiqués de presse mensuels](https://www.aaa-data.fr/actualites/communique-de-presse-du-1er-juillet-2026/)
- ACEA — [passenger-car definition (M1, incl. SUVs)](https://www.acea.auto/fact/passenger-cars-what-they-are-and-why-they-are-so-important/) ·
  [new car registrations, June 2026 press release](https://www.acea.auto/files/Press_release_car_registrations_June_2026.pdf)
