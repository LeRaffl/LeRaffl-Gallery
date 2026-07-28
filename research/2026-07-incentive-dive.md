# What speeds up — and stalls — the BEV transition?

*Research note, July 2026. Working material for the next article after the
Italy/Spain rental splits. Method: hypothesis → prediction → test on fresh
countries not used to form the hypothesis.*

## Background

The Italy and Spain articles showed that a slow national headline number can
hide two very different markets (rental vs. non-rental). Checking the other
disjoint splits in our data (Denmark, Finland: private vs. industry) showed
the private/corporate gap is not universal — its **sign flips between
countries and over time**. That killed the naive story ("private leads" or
"fleets lead") and produced three hypotheses.

## Hypotheses

- **H1 — Incentive design determines *who* leads.** Whichever channel the
  tax/subsidy system favors electrifies first; there is no natural leader.
- **H2 — Incentive *removal* is immediately visible as pull-forward spike +
  collapse.** If H1 is right, cutting an incentive must show up as a sharp
  break in the monthly series, timed to the policy date.
- **H3 — Structural economics can outweigh incentives** in two channels:
  short-holding rental fleets (residual-value risk, tourist duty cycles) and
  the used market (weak residual values), which in turn brakes corporate
  leasing.

## Tests

### H1: sign of the private-vs-corporate gap (our data + external)

| Country | Evidence | Gap |
|---|---|---|
| Denmark | Private 92.4% vs Industry 48.6% BEV (TTM, own data) | **Private +44 pp** — registration tax hits private ICE buyers hardest |
| Belgium | Corporate ~54% vs private ~9% (H1 2025, T&E) | **Corporate +45 pp** — company-car tax reform |
| Finland | Gap flipped from private +4.6 pp (2023) to industry −6.6 pp (2025), own data | **Sign flip** timed to end of the private purchase subsidy (end 2023), while the company-car benefit continued |

Same continent, same years, opposite signs — and the one within-country flip
coincides with a policy change. **H1 supported.** Finland is the strongest
evidence because it is a natural experiment inside one country.

### H2: incentive-removal shocks on fresh countries (own monthly data)

Predicted signature: spike in the last eligible month, collapse in the first
ineligible month. All four fresh cases show it:

| Country | Policy event | Own data (monthly BEV share) |
|---|---|---|
| New Zealand | Clean Car Discount ends 31 Dec 2023 | Dec 2023: 20% → Jan 2024: **1%**; yearly 10.1% (2023) → 3.4% (2024) |
| Iceland | Blanket VAT exemption ends 31 Dec 2023 (replaced by smaller capped grant + km charge) | Dec 2023: 86% → Jan 2024: 37%, Apr: 13%; yearly 50.0% → 29.3% |
| Germany | Umweltbonus: corporate eligibility ends 1 Sep 2023; abrupt full stop 17 Dec 2023 | Aug 2023: 32% → Sep: 14% (corporate cut); 2024 yearly 18.4% → 13.5% |
| Sweden | Klimatbonus abolished 8 Nov 2022 | Dec 2022: 51% → Jan 2023: 28% (order pull-forward); 2024 dip to 34.2% |

Counterfactual check: countries **without** cuts in that window (UK with the
ZEV mandate, France, Portugal, Norway, Belgium) show no 2024 dip — they rise
monotonically. **H2 strongly supported.** Germany even shows *two* breaks
matching the two policy dates.

### H3: structural brakes (rental, used market)

- Rental: Italy rental 5.6% vs non-rental 9.0%; Spain rental 4.3% vs
  non-rental 13.0% (TTM, own data). Rental lags in both, under different
  national incentive regimes.
- Used market: Netherlands used-BEV share **peaked at 7.7% in 2022 and fell
  to 3.8% by 2025**, even though the new-BEV share four years earlier (the
  cohort feeding the used market) kept rising steeply (20→35%). The domestic
  used market is not absorbing the lease returns — consistent with exports of
  used BEVs and weak residual values. Spain used: 3.5% vs 8.9% new.
- Residual-value risk plausibly also explains why Danish industry sits near
  50% while Danish private is at 92% despite no tax penalty on corporate
  BEVs. (This leg is the weakest — correlational only.)

**H3 supported for rental and used; the corporate-residual-value link is
plausible but untested.**

## Resulting insight (article thesis)

1. **There is no natural leader of the transition.** Who electrifies first —
   households or fleets — is decided by incentive design (DK vs BE vs FI).
2. **Incentives work, and their removal is brutal and instantaneous.** Four
   independent countries show the same spike-and-cliff signature within one
   month of the policy date; no-cut countries show no cliff. BEV demand at
   current prices is heavily policy-elastic.
3. **Two channels resist incentives for structural reasons:** short-holding
   rental fleets and the used market. Italy and Spain are slow not because
   incentives fail there, but because their corporate channel is unusually
   rental-heavy — they are special cases of H3, not counterexamples to H1/H2.

## H4/H5: do incentives change the destination, or only the speed?

Two follow-up hypotheses:

- **H4 — Incentives only accelerate; the transition happens without them,
  just slower.** Prediction: after a cut, every market recovers to and
  eventually exceeds its pre-cut share, without the incentive coming back.
- **H5 — Permanence depends on the stage at removal.** Cutting early in the
  transition does lasting damage; cutting late (>~50–70% share) does little.

Test: for each removal case, pre-cut TTM peak, post-cut trough, relative
drop, and months back to the pre-cut peak (all own monthly data):

| Country | Cut | Share at cut | Trough | Rel. drop | Back to peak |
|---|---|---|---|---|---|
| Denmark | 2016 (registration-tax phase-in) | 2.1% | 0.3% | **−85%** | +45 months |
| New Zealand | Jan 2024 | 10.1% | 3.4% | **−66%** | not yet (30+ mo, now 6.7%) |
| Germany | Jan 2024 (corporate already Sep 2023) | 20.5% | 13.5% | −34% | +27 months (now 22.6%) |
| Sweden | Nov 2022 | 30.2% | 34.1% (from 39.5% delivery peak) | −14% | never below pre-cut level |
| Iceland | Jan 2024 | 50.0% | 29.3% | −41% | not yet (now 45.4%, rising) |
| Norway | 2023 (partial VAT, gradual) | 78.4% | 78.0% | ~0% | immediate (now 97.6%) |

**H4 supported:** no market stays down. Even Denmark's near-death 2016–17
market (−85%) resumed and sits at 76% today; Germany regained its peak in 27
months **without a new purchase subsidy** and has moved past it. The
transition direction appears irreversible; incentives buy time, not the
destination. Caveats: Denmark's recovery coincided with the government
postponing/softening the tax phase-in in 2018, so it is not a clean
"no-policy-reversal" case — Germany is the cleanest one. New Zealand is the
one market still far below peak after 2.5 years (and it added road-user
charges for EVs on top, i.e. a negative incentive, not mere removal).

**H5 supported with one amendment:** relative damage falls broadly with the
stage at removal (2% → −85%; 10% → −66%; 20% → −34%; 30% → −14%; 78% → 0%;
90% → −18% [HK, abrupt] vs. 78% → 0% [NO, gradual]) — **except Iceland**
(50% → −41%). Note the two late points aren't monotone: Hong Kong's abrupt
full removal at 90% bit harder (−18%) than Norway's gradual one at 78%
(~0%), which is the dose axis showing up, not a break in the stage rule.
The Iceland outlier is
explained by **dose**: it didn't remove one subsidy, it removed a blanket
VAT exemption *and* introduced a per-km road charge simultaneously — the
largest single-shock repricing in the sample. So the working model is:
*lasting-ness of the transition ≈ f(stage); size of the shock ≈ f(dose).*
And even Iceland is back to 45% and climbing within 2.5 years, consistent
with H4.

Rule of thumb for the article: **below ~20–30% market share, removing
incentives costs years; above ~70%, it costs nothing.** The transition
completes either way.

## Hong Kong: the missing datapoint, live

Hong Kong is the case our sample lacked — an **abrupt, complete removal at
very late stage** — and it also contains the most brutal early-stage case on
record, so one city spans the whole H5 curve:

- **2017, early stage:** full first-registration-tax waiver capped at
  HK$97,500 in April 2017. Tesla registered 2,939 cars in March 2017 and
  **32 in the remaining nine months** of the year. Consistent with the
  early-stage end of the curve (DK 2016, NZ 2024).
- **2026, late stage:** all FRT concessions (incl. One-for-One) ended
  completely on 31 March 2026, with BEV penetration around 90%.

Monthly BEV penetration of private-car registrations (via Roland Pircher,
@piloly, from HK Transport Department data — treated as reliable):

| Month | BEV share | Note |
|---|---|---|
| 2025-06 | 86.3% | baseline |
| 2026-01 | 89.2% | |
| 2026-03 | 95.0% | record — pull-forward before the 31 Mar deadline |
| 2026-04 | 94.6% | first post-concession month |
| 2026-05 | 89.2% | back at the January baseline (still pre-deadline orders) |
| 2026-06 | 73.4% | **first clean month** — orders mostly placed post-deadline; total mkt collapsed to ~1,900 cars |

**A shallow dent, not a cliff — and not "nothing" either.** The earlier read
(only through May) looked like a full return to baseline, i.e. zero damage.
That was premature: April and May still cleared pre-deadline orders, exactly
the caveat flagged below. June is the first month whose buyers mostly decided
*after* the concessions were gone, and BEV share drops to 73.4% — a relative
fall of ~18% vs. the ~89% baseline (~23% vs. the 95% spike). So the honest
H5 result is: at ~90% stage, a full, abrupt removal (high dose) still bites,
but only ~a fifth of the way — vs. −41% at Iceland's 50% (double dose) and
−85% at Denmark's 2%. Stage still dominates; "no damage at all past 90%" was
an overstatement of a real effect (shallow, high-baseline damage). Note the
contrast with Norway (78%, gradual, low dose → ~0%): late stage *and* low
dose is what buys zero — Hong Kong isolates the dose axis at the top.

Caveats: June is a single month on tiny post-crash volume (~1,900 cars),
so the point is noisy; July–August 2026 will show whether 73% is the floor
or a way-station. Worth building `Hong Kong.csv`
from TD monthly stats and tracking this through year-end.

## Toward a field guide: the full event table (stage × dose)

Goal: make subsidy effects *plannable* — "cut X% of price advantage at Y%
market share and expect Z". Dose = change in effective price of the
country's best-selling BEV at the event date, as % of its purchase price
(purchase incentives, taxes, VAT; recurring charges as rough 4-year NPV).
Doses marked ~ are estimates from policy parameters, not computed prices.
Market response columns are computed from Gallery data (TTM, peak→trough)
unless marked ext.

| Event | Date | Share at cut | Dose (~% of car price) | Rel. drop | Time lost |
|---|---|---|---|---|---|
| Netherlands, PHEV bijtelling 7%→15/22% | 2016–17 | 9.2% (PHEV) | very high (company-car tax on list price doubled+) | **−94%** | 70 months |
| Denmark, reg-tax phase-in | 2016 | 2.1% | ~7–9% in y1, rising by schedule | **−85%** | 45 months |
| Hong Kong, FRT waiver capped | Apr 2017 | early | ~50%+ (luxury segment) | ~total (ext: Tesla 2,939→32) | reinstated 2018 instead |
| New Zealand, CCD end + RUC | Jan 2024 | 10.1% | ~15–19% (rebate + new km charge) | −66% | 30+ months, ongoing |
| USA, federal credit end | Oct 2025 | 8.2% | ~16% where eligible | −17% so far | ongoing (still falling, 2026-05) |
| Germany, Umweltbonus end (2 steps) | Sep+Dec 2023 | 20.5% | ~11% | −34% | 27 months |
| Sweden, Klimatbonus end | Nov 2022 | 30.2% | ~10–14% (50–70k SEK) | −14% (from delivery peak) | ~0 (never below pre-cut level) |
| UK, Plug-in Car Grant end | Jun 2022 | 15.1% | ~2–5% (£1,500, only <£32k cars) | **−1% (none)** | 0 |
| France, bonus reductions (steps) | 2024–25 | 17.8% | ~2% per step, staircase | −5% | 9 months |
| Israel, purchase-tax staircase 10→45% | 2023–26 | ~20–25% | ~5–10% per step, annual | none visible (ext) | 0 |
| Iceland, VAT exemption end + km charge | Jan 2024 | 50.0% | ~20%+ (double shock) | −41% | 30+ months, recovering |
| Denmark, phase-in postponed (relief) | 2018 | ~0.4% | negative (price cut) | recovery begins | — |
| Norway, partial VAT, gradual | 2023 | 78.4% | small per step | ~0 | 0 |
| Hong Kong, all concessions end | Mar 2026 | ~90% | large (~25%) | **−18%** (Jun, 1st clean mo) | ongoing |

n≈14 heterogeneous events — enough for a surface and rules of thumb, NOT
for a regression. No elasticities; nearest-precedent lookup only.

## The rules, quantified (current best estimates)

1. **How hard is the typical crash?** Determined jointly by stage and dose.
   Early (<10% share) + big abrupt dose: −66% to −94% of the market, i.e.
   the market effectively resets. Mid-stage (15–30%) + moderate dose
   (~10–15% of car price): −5% to −34%. Late (>70%): a gradual/low dose
   costs ~0 (Norway); a full, abrupt dose still costs ~18% even at ~90%
   (Hong Kong, Jun 2026, provisional) — shallow, and off a high baseline,
   but not zero.
2. **How much time is lost?** Early cuts: 4–6 years (DK 45 mo, NL-PHEV 70
   mo, NZ >30 mo and counting). Mid-stage cuts: 0–27 months (DE 27, FR 9,
   SE ~0). Late gradual cut: none (NO); late abrupt cut: TBD (HK still in
   its dip as of Jun 2026). Time lost shrinks roughly an order of magnitude
   from early to mid stage.
3. **Dose scaling at similar stage** (the UK–SE–DE–NZ column): ~2–5% dose →
   no effect; ~10–14% → −14% (Sweden, from delivery peak); ~11% abrupt overnight → −34%; ~15–19% incl.
   new charges → −66%. Abruptness and stacking (new charges in the same
   month) visibly worsen the response beyond the raw dose.
4. **When is removal safe?** "Safe" = cheap, not free. A single moderate
   incentive can be removed with little damage from ~30% share (Sweden).
   Removing everything gradually is free even mid-high (Norway, 78%).
   Removing everything abruptly still costs ~18% even at ~90% (Hong Kong) —
   cheap relative to the level, not zero. 50% is demonstrably NOT enough for
   a full-dose double shock (Iceland). No single safe threshold; price
   sensitivity just keeps falling as stage rises.
5. **Which incentives to cut first?** (a) Small per-unit grants whose dose
   has shrunk below ~5% of car price — they're no longer load-bearing (UK).
   (b) Anything, if cut as a pre-announced staircase of ≤~5–10% steps —
   staircases show no crater at any tested stage (France, Israel, Norway).
   (c) Never stack a removal with a new recurring charge mid-transition —
   that's the Iceland/NZ signature. (d) Channel-specific cuts crater that
   channel: Germany's September-2023 corporate-only cut broke the whole
   series two months before the general cut did.

## Open questions / next steps

- Belgium private-vs-corporate split from Statbel/FEBIAC to replace the
  external T&E number with own data.
- Test the residual-value → corporate-hesitation link properly (used-BEV
  price indices, e.g. NL/DE).
- Norway as the end-state check: does the private/corporate gap close as the
  market saturates (DK gap already stopped growing in 2026)?
- Check whether the post-cut recovery speed (DE 2025: back to 19.1%) is
  price-parity driven — recovery without re-instated subsidies would bound
  how much of demand is still incentive-dependent.

Next steps for the field-guide article: pin down the ~doses properly
(reference-BEV price per country per event date), decide the scatter
encoding (x=stage, y=rel. drop, size/color=dose), and build the
nearest-precedent lookup ("countries that already tried this") instead of
a fitted model.

## Data & sources

Own data: `data/{Denmark,Finland}_{Private,Industry}.csv`,
`data/{Italy,Spain}_{Rental,NonRental}.csv`,
`data/{Netherlands,Spain}_Used.csv`, whole-market CSVs for NZ, IS, DE, SE,
UK, FR, PT, NO, BE.

External: [ICCT European Market Monitor 2025](https://theicct.org/publication/european-market-monitor-cars-and-vans-2025/) ·
[T&E: corporate fleets & EVs](https://www.transportenvironment.org/articles/how-corporate-fleets-can-boost-demand-for-made-in-eu-evs) ·
[T&E: company-fleet incentives by country](https://www.transportenvironment.org/articles/which-eu-countries-incentivise-company-fleets-to-go-electric) ·
[NZTA: Clean Car Discount end](https://www.nzta.govt.nz/vehicles/clean-car-programme/clean-car-discount-ended-on-31-december-2023) ·
[Newsroom NZ: EV sales plummet](https://newsroom.co.nz/2024/02/07/ev-sales-plummet-after-clean-car-discount-scrapped/) ·
[Ísland.is: electric car grants](https://island.is/en/electric-car-grants) ·
[VATupdate: Iceland removing VAT reliefs](https://www.vatupdate.com/2023/11/30/iceland-removing-vat-reliefs-for-electric-vehicles/) ·
[KBA Jahresbilanz 2025](https://www.kba.de/DE/Presse/Pressemitteilungen/Fahrzeugzulassungen/2026/pm01_2026_n_12_25_pm_komplett.html) ·
[dena Monitoringbericht 2025](https://www.dena.de/fileadmin/dena/Publikationen/PDFs/2025/Monitoringbericht_2025.pdf)
