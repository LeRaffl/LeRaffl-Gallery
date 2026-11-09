#!/usr/bin/env python3
"""Regression tests for the Fleet tab's projection and emissions model.

Run:  python scripts/test_fleet_model.py   (needs node on PATH)

The model lives in index.html; this runs the real in-page functions under node
(scripts/js_extract.js) against small made-up countries. What it pins:

* a turnover box means one thing: a mature fleet loses exactly that share a
  year, in both hazard modes;
* calibration makes the first projected year lose the country's observed
  share, and books a share below the floor as net used imports;
* a young category starts from its registration history and barely loses cars;
* registrations are conserved and the combustion side lands in HEV / PETROL /
  DIESEL by the country's inflow mix, not wholesale in OTHERS (which the
  Energy view reads as LPG/CNG);
* where the age structure of a stock is observed, the fleet starts from it;
* a car is driven as far as its own country's statistics say, and a country's
  km per car is held constant as its fleet turns electric;
* electricity is charged from each country's own grid, and the three grid
  scenarios behave as documented;
* the defaults in the markup and in the code agree, and only passenger-car
  rows of the stock file are read.
"""
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAMES = """safeNum clamp01 VINTAGE_AGE_CAP weibullSurvival deriveWeibullScale weibullStepSurvival
emptyVintageBuckets fleetAgeProfile fleetCombustionHistory initVintageBuckets vintageTotal
stepVintageBuckets fleetCalibration FLEET_TURNOVER_FLOOR fleetTurnover getFleetCategories
emptyFleetRow rowTotal getObservedRow inferNonBevTargetBucket inferNonBevSplit fleetIceSplit
fleetYearInflow applyFleetNetImports fleetProjectionCache cachedFleetProjection projectCountryFleet
projectCountryFleetLinear projectCountryFleetVintage projectCountryFleetVintageRun effectiveHazard
inflowDecayMultiplier shiftSharesForDecay parseGridMix feWorldMix feGridSeries feGridTrend feGridAt
feChain fePerVehicle FE_F FE_KEYS FE_LAB FE_KM feNormalise
FLEET_AGE_BANDS fleetAgeBands initVintageBucketsFromBands feMileage feAverageKm""".split()

HARNESS = r"""
const {execFileSync} = require('child_process');
const src = execFileSync('node', [process.argv[1], process.argv[2], ...JSON.parse(process.argv[3])],
                         {maxBuffer: 64 * 1024 * 1024}).toString();
const TESTS = String.raw`
const out = [];
const check = (ok, msg) => out.push([!!ok, msg]);
const near = (a, b, tol) => Math.abs(a - b) <= tol;

// ---- stubs for what the page loads -------------------------------------
const fleetState = { observed: [], calibration: {}, grid: {} };
const getCountryCandidates = c => [String(c || '')];
let INFLOW = 0, BEV_SHARE = 0.2, ICE_SHARE = 0.7;
const getCountryAnnualInflow = () => INFLOW;
const modeledBevShareForYear = () => BEV_SHARE;
const modeledIceShareForYear = () => ICE_SHARE;
const RATES = { BEV: 0.045, PHEV: 0.045, HEV: 0.045, HYBRID: 0.045, PETROL: 0.045, DIESEL: 0.05, OTHERS: 0.045 };
const opts = (extra) => Object.assign({ hazardCurve: { base: RATES, kneeYear: 12, slope: 0 }, calibrate: false,
  weibullShape: 3, inflowMultiplier: 1, netImportsPerYear: 0, bevImportShare: 1 }, extra || {});
const setCountry = (name, row, cal) => {
  fleetState.observed = fleetState.observed.filter(r => r.country !== name);
  fleetState.observed.push(Object.assign({ country: name, year: 2025, BEV: 0, PHEV: 0, HEV: 0, HYBRID: 0, DIESEL: 0, PETROL: 0, OTHERS: 0 }, row));
  if (cal) fleetState.calibration[name] = cal; else delete fleetState.calibration[name];
  fleetProjectionCache.clear();
};
const exit1 = (s) => (rowTotal(s[0]) + INFLOW - rowTotal(s[1])) / rowTotal(s[0]);

// ---- 1. a box = the share a mature fleet loses per year ------------------
INFLOW = 0;
setCountry('A', { PETROL: 1e6 });
for (const [fn, label] of [[projectCountryFleetVintage, 'Weibull'], [projectCountryFleet, 'constant rate']]) {
  const s = fn('A', 2025, 2027, opts());
  check(near(exit1(s), 0.045, 1e-6), label + ': a mature petrol fleet loses exactly 4.5% (got ' + exit1(s) + ')');
}
setCountry('A', { DIESEL: 1e6 });
check(near(exit1(projectCountryFleetVintage('A', 2025, 2026, opts())), 0.05, 1e-6), 'Weibull: a mature diesel fleet loses exactly 5.0%');
// ...and keeps losing it when the cars that leave are replaced.
setCountry('A', { PETROL: 1e6 }); INFLOW = 45000; BEV_SHARE = 0; ICE_SHARE = 1;
{ const s = projectCountryFleetVintage('A', 2025, 2045, opts());
  check(near(rowTotal(s[20]), 1e6, 1e6 * 1e-3), 'a mature fleet with replacement inflow stays the same size for 20 years'); }
for (const shape of [1, 2, 3, 5]) {
  const sc = deriveWeibullScale(0.045, shape); let sum = 0;
  for (let a = 0; a <= VINTAGE_AGE_CAP; a++) sum += weibullSurvival(a, sc, shape);
  check(near(1 / sum, 0.045, 1e-6), 'scale solves 1/sum S(a) = rate at shape ' + shape);
}

// ---- 2. calibration: first year = the observed share ---------------------
INFLOW = 60000; BEV_SHARE = 0.2; ICE_SHARE = 0.7;
const young = {}; [2021, 2022, 2023, 2024, 2025].forEach((y, i) => { young[y] = 10000 * (i + 1); });
setCountry('B', { BEV: 150000, PHEV: 50000, PETROL: 500000, DIESEL: 300000 },
  { attrition: { rate: 0.03, n: 5, from: 2021, to: 2025 }, reg_by_year: { BEV: young } });
for (const [fn, label] of [[projectCountryFleetVintage, 'Weibull'], [projectCountryFleet, 'constant rate']]) {
  check(near(exit1(fn('B', 2025, 2030, opts({ calibrate: true }))), 0.03, 2e-4), label + ' + calibration: first year loses the observed 3.0%');
  check(!near(exit1(fn('B', 2025, 2030, opts())), 0.03, 2e-3), label + ' without calibration does not');
}
// Observed below the floor (used-import country): floor of exits + used imports.
fleetState.calibration.B.attrition.rate = -0.02; fleetProjectionCache.clear();
{ const t = fleetTurnover('B', opts({ calibrate: true }));
  check(near(t.exitRate, 0.01, 1e-12) && near(t.usedRate, 0.03, 1e-12), 'observed -2%: 1% leaves, 3% net used imports');
  for (const [fn, label] of [[projectCountryFleetVintage, 'Weibull'], [projectCountryFleet, 'constant rate']])
    check(near(exit1(fn('B', 2025, 2030, opts({ calibrate: true }))), -0.02, 6e-4), label + ': the fleet nets the observed -2.0%'); }
fleetState.calibration.B.attrition.rate = 0.4;
check(fleetTurnover('B', opts({ calibrate: true })).exitRate === 0.15, 'an absurd observed rate is capped');
check(fleetTurnover('B', opts()) === null && fleetTurnover('A', opts({ calibrate: true })) === null,
      'no turnover target with calibration off, or without an observed rate');
fleetState.calibration.B.attrition.rate = 0.03; fleetProjectionCache.clear();

// ---- 3. age structure from the registration history ----------------------
{ const p = fleetAgeProfile('B', 'BEV', 2025);
  check(near(p[0], 50000 / 150000, 1e-9) && near(p[4], 10000 / 150000, 1e-9) && p[5] === 0, 'BEV age profile = registrations by year');
  check(fleetAgeProfile('B', 'PHEV', 2025) === null && fleetAgeProfile('A', 'BEV', 2025) === null, 'no history, no profile');
  const s = projectCountryFleetVintage('B', 2025, 2026, opts());
  INFLOW = 0; fleetProjectionCache.clear();
  const s0 = projectCountryFleetVintage('B', 2025, 2026, opts());
  check((150000 - s0[1].BEV) / 150000 < 0.002, 'a five-year-old BEV fleet loses under 0.2% in a year');
  check((500000 - s0[1].PETROL) / 500000 > 0.04, '...while the mature petrol fleet next to it loses over 4%');
  INFLOW = 60000; }
// Combustion history: a fast-grown fleet starts young, a stock older than the record keeps a tail.
{ const hist = {}; for (let y = 2011; y <= 2025; y++) hist[y] = 60000;
  setCountry('C', { PETROL: 800000 }, { reg_by_year: { COMBUSTION: hist } });
  INFLOW = 0;
  const youngFleet = exit1(projectCountryFleetVintage('C', 2025, 2026, opts()));
  check(youngFleet < 0.02, 'a stock fully explained by 15 years of registrations is young: loses ' + youngFleet.toFixed(4) + ' < 2%');
  setCountry('C', { PETROL: 3000000 }, { reg_by_year: { COMBUSTION: hist } });
  const old = exit1(projectCountryFleetVintage('C', 2025, 2026, opts()));
  check(old > 0.06, 'a stock far larger than the record is old: loses ' + old.toFixed(4) + ' > 6%');
  const b = initVintageBuckets(getObservedRow('C', 2025), { PETROL: deriveWeibullScale(0.045, 3) }, 3, {}, fleetCombustionHistory('C', 2025));
  check(near(vintageTotal(b, 'PETROL'), 3000000, 1), 'the age buckets always add up to the stock');
  check(fleetCombustionHistory('A', 2025) === null, 'fewer than five unbroken years: no history');
  INFLOW = 60000; }

// Observed age bands win over every inferred structure.
{ INFLOW = 0;
  const bands = [0.10, 0.20, 0.40, 0.30];
  const sumBand = (arr, lo, hi) => { let t = 0; for (let a = lo; a < Math.min(hi, VINTAGE_AGE_CAP + 1); a++) t += arr[a]; return t; };
  const sc = { PETROL: deriveWeibullScale(0.045, 3), DIESEL: deriveWeibullScale(0.05, 3), BEV: deriveWeibullScale(0.045, 3) };
  const row = { BEV: 0, PETROL: 600000, DIESEL: 400000 };
  const b = initVintageBuckets(Object.assign(emptyFleetRow(2025), row), sc, 3, {}, null, bands);
  FLEET_AGE_BANDS.forEach(([lo, hi], i) => {
    const got = (sumBand(b.PETROL, lo, hi) + sumBand(b.DIESEL, lo, hi)) / 1e6;
    check(near(got, bands[i], 1e-9), 'age band ' + lo + '+ holds its observed share (' + got.toFixed(3) + ')');
  });
  check(near(vintageTotal(b, 'PETROL'), 600000, 1e-3) && near(vintageTotal(b, 'DIESEL'), 400000, 1e-3), 'banded buckets add up to each category');
  check(near(sumBand(b.DIESEL, 20, 999) / 400000, 0.30, 1e-9), 'every non-profile category gets the same band shares');
  // A young BEV fleet takes its cars out of the youngest band first.
  const prof = new Float64Array(VINTAGE_AGE_CAP + 1); prof[0] = 0.5; prof[1] = 0.5;
  const b2 = initVintageBuckets(Object.assign(emptyFleetRow(2025), { BEV: 50000, PETROL: 950000 }), sc, 3, { BEV: prof }, null, bands);
  check(near(b2.BEV[0], 25000, 1e-9) && near(sumBand(b2.PETROL, 0, 5), 50000, 1e-6), 'young BEVs fill the under-5 band; petrol gets what is left of it');
  check(near(sumBand(b2.PETROL, 20, 999), 300000, 1e-6) && near(vintageTotal(b2, 'PETROL'), 950000, 1e-3), '...and the old bands stay all petrol');
  // Bands the stock contradicts (more young BEVs than young cars) still add up.
  const b3 = initVintageBuckets(Object.assign(emptyFleetRow(2025), { BEV: 500000, PETROL: 500000 }), sc, 3, { BEV: prof }, null, bands);
  check(near(vintageTotal(b3, 'PETROL'), 500000, 1e-3) && near(vintageTotal(b3, 'BEV'), 500000, 1e-3) && sumBand(b3.PETROL, 0, 5) === 0, 'inconsistent bands never lose or invent cars');
  setCountry('F', { PETROL: 1e6 }, { age_bands: { '2024': [0.05, 0.10, 0.30, 0.55], '2019': [0.4, 0.3, 0.2, 0.1] } });
  check(fleetAgeBands('F', 2025)[3] === 0.55 && fleetAgeBands('F', 2016) === null, 'bands: nearest year within two, else none');
  const oldFleet = exit1(projectCountryFleetVintage('F', 2025, 2026, opts()));
  setCountry('F', { PETROL: 1e6 }, { age_bands: { '2025': [0.45, 0.35, 0.18, 0.02] } });
  const newFleet = exit1(projectCountryFleetVintage('F', 2025, 2026, opts()));
  check(oldFleet > 2 * newFleet, 'an observed old fleet loses far more cars than an observed young one (' + oldFleet.toFixed(3) + ' vs ' + newFleet.toFixed(3) + ')');
  check(near(exit1(projectCountryFleetVintage('F', 2025, 2026, opts({ calibrate: true }))), newFleet, 1e-12), 'bands without an observed rate: nothing to calibrate to');
  INFLOW = 60000; }

// ---- 4. where new registrations land --------------------------------------
BEV_SHARE = 0.2; ICE_SHARE = 0.7;   // -> 10% plug-in hybrids
const sumRow = r => getFleetCategories().reduce((a, k) => a + r[k], 0);
{ const row = { BEV: 1, PHEV: 1, HEV: 1, PETROL: 1, DIESEL: 1, OTHERS: 1 };
  setCountry('D', row, { inflow_mix: { HEV: 0.4, PETROL: 0.35, DIESEL: 0.2, OTHERS: 0.05 } });
  const start = getObservedRow('D', 2025);
  const f = fleetYearInflow('D', 2026, start, opts(), inferNonBevSplit(start), fleetIceSplit('D', start));
  check(near(sumRow(f), 60000, 1e-6), 'every registered car lands in a bucket');
  check(near(f.BEV, 12000, 1e-6) && near(f.PHEV, 6000, 1e-6), 'BEV by its curve, plug-ins between the curves');
  check(near(f.HEV, 16800, 1e-6) && near(f.PETROL, 14700, 1e-6) && near(f.DIESEL, 8400, 1e-6) && near(f.OTHERS, 2100, 1e-6),
        'the combustion side follows the inflow mix (HEV / PETROL / DIESEL / gas)');
  // Stock without a full-hybrid bucket: hybrids go where that stock keeps them.
  setCountry('D', { BEV: 1, PHEV: 1, PETROL: 1, DIESEL: 1 }, { inflow_mix: { HEV: 0.4, PETROL: 0.35, DIESEL: 0.2, OTHERS: 0.05 } });
  const s2 = fleetIceSplit('D', getObservedRow('D', 2025));
  check(near(s2.PETROL, 0.75, 1e-9) && s2.HEV === 0, 'no HEV bucket: full hybrids are booked with petrol');
  setCountry('D', { BEV: 1, HYBRID: 1, PETROL: 1, DIESEL: 1 }, { inflow_mix: { HEV: 0.4, PETROL: 0.35, DIESEL: 0.2, OTHERS: 0.05 } });
  const s3 = fleetIceSplit('D', getObservedRow('D', 2025));
  check(near(s3.HYBRID, 0.4, 1e-9), 'combined HYBRID bucket takes the full hybrids');
  // China-style stock: no petrol/diesel split -> everything stays lumped.
  setCountry('D', { BEV: 100, PHEV: 50, OTHERS: 1000 }, { inflow_mix: { HEV: 0.4, PETROL: 0.35, DIESEL: 0.2, OTHERS: 0.05 } });
  check(fleetIceSplit('D', getObservedRow('D', 2025)).OTHERS === 1, 'a stock without petrol/diesel keeps combustion lumped in OTHERS');
  // No inflow mix: in proportion to the stock.
  setCountry('D', { BEV: 100, PHEV: 50, PETROL: 600, DIESEL: 300, OTHERS: 100 });
  const s4 = fleetIceSplit('D', getObservedRow('D', 2025));
  check(near(s4.PETROL, 0.6, 1e-9) && near(s4.DIESEL, 0.3, 1e-9) && near(s4.OTHERS, 0.1, 1e-9), 'no inflow mix: split like the stock');
  // The regression itself: projected petrol stock must not migrate to OTHERS.
  setCountry('D', { BEV: 1e5, PHEV: 5e4, PETROL: 6e5, DIESEL: 3e5, OTHERS: 1e4 }, { inflow_mix: { HEV: 0, PETROL: 0.7, DIESEL: 0.3, OTHERS: 0 } });
  for (const fn of [projectCountryFleetVintage, projectCountryFleet]) {
    const s = fn('D', 2025, 2040, opts());
    check(s[15].OTHERS < 1e4 && s[15].PETROL > 3e5, 'projected combustion cars stay petrol/diesel; OTHERS (LPG/CNG) only shrinks');
  } }
// Manual net imports still add up.
{ setCountry('E', { BEV: 1e5, PETROL: 9e5 }); INFLOW = 0;
  for (const fn of [projectCountryFleetVintage, projectCountryFleet]) {
    const a = fn('E', 2025, 2026, opts()), b = fn('E', 2025, 2026, opts({ netImportsPerYear: 10000, bevImportShare: 0.25 }));
    check(near(b[1].BEV - a[1].BEV, 2500, 1e-6) && near(b[1].OTHERS - a[1].OTHERS, 7500, 1e-6), 'positive net imports: BEV share to BEV, rest to OTHERS');
    const c = fn('E', 2025, 2026, opts({ netImportsPerYear: -10000, bevImportShare: 0.25 }));
    check(near(rowTotal(a[1]) - rowTotal(c[1]), 10000, 1e-6), 'negative net imports remove exactly that many cars');
  } }

// ---- 5. each country's own grid --------------------------------------------
fleetState.grid = parseGridMix([
  { country: 'World', year: '2024', gco2_kwh: '470', coal: '35', gas: '22', oil: '3', nuclear: '9', hydro: '14', wind: '8', solar: '7', bio: '2', other_renew: '0' },
  ...[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024].map((y, i) =>
    ({ country: 'Clean', year: String(y), gco2_kwh: String(30), coal: '', gas: '2', oil: '', nuclear: '', hydro: '90', wind: '8', solar: '', bio: '', other_renew: '' })),
  ...[2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024].map((y, i) =>
    ({ country: 'Dirty', year: String(y), gco2_kwh: String(800 - 20 * i), coal: '70', gas: '20', oil: '', nuclear: '', hydro: '5', wind: '5', solar: '', bio: '', other_renew: '' })),
  ...[2020, 2021, 2022, 2023, 2024].map((y, i) =>
    ({ country: 'Worse', year: String(y), gco2_kwh: String(300 + 10 * i), coal: '30', gas: '30', oil: '', nuclear: '', hydro: '40', wind: '', solar: '', bio: '', other_renew: '' })),
  { country: 'Broken', year: '2024', gco2_kwh: '', coal: '50', gas: '50' }
]);
check(near(feGridAt('Dirty', 2018, 'trend').g, 0.740, 1e-9), 'an observed year uses that year, whatever the scenario');
check(near(feGridAt('Dirty', 2010, 'trend').g, 0.800, 1e-9), 'before the record: the first year on record');
check(near(feGridAt('Dirty', 2030, 'constant').g, 0.620, 1e-9), "'constant' holds the last observed year");
check(near(feGridAt('Dirty', 2030, 'trend').g, 0.620 - 6 * 0.020, 1e-9), "'trend' continues the ten-year slope (-20 g/yr)");
check(near(feGridAt('Dirty', 2080, 'trend').g, FE_F.grid_co2_target, 1e-9), "'trend' never goes below the net-zero residual");
check(near(feGridAt('Worse', 2040, 'trend').g, 0.340, 1e-9), "'trend' never extrapolates a grid that got dirtier");
check(near(feGridAt('Dirty', 2032, 'nze').g, 0.620 + (0.020 - 0.620) * 8 / 16, 1e-9), "'nze' is linear to the target");
check(near(feGridAt('Dirty', 2045, 'nze').g, 0.020, 1e-9), "'nze' is flat after the target year");
check(near(feGridAt('Clean', 2045, 'nze').g, 0.030, 1e-9) || feGridAt('Clean', 2045, 'nze').g <= 0.030, 'a grid already near the target is never made dirtier');
check(near(feGridAt('Nowhere', 2030, 'constant').g, 0.470, 1e-9), 'a country without rows falls back to World');
check(feGridSeries('Broken') === fleetState.grid.World, 'a row without an intensity is not a grid');
check(near(feGridAt('Clean', 2024, 'constant').mix.renew, 0.98, 1e-9), 'mix is folded onto the Sankey sources and normalised');
{ const cars = { BEV: 1e6, PHEV: 0, HEV: 0, DIESEL: 0, PETROL: 0, GASFUEL: 0 };
  const kwh = 1e6 * FE_F.cons_bev / 100 * FE_F.km_bev / (1 - FE_F.grid_td_loss);
  const one = c => feChain({ year: 2024, row: cars, parts: [{ country: c, row: cars }] }, 'constant');
  check(near(one('Clean').co2.elec, kwh * 0.030 / 1e9, 1e-9), 'clean grid: a million BEVs emit generation x 30 g');
  check(near(one('Dirty').co2.elec / one('Clean').co2.elec, 620 / 30, 1e-6), 'the same cars on the dirty grid emit 20x as much');
  const two = { BEV: 2e6, PHEV: 0, HEV: 0, DIESEL: 0, PETROL: 0, GASFUEL: 0 };
  const both = feChain({ year: 2024, row: two, parts: [{ country: 'Clean', row: cars }, { country: 'Dirty', row: cars }] }, 'constant');
  check(near(both.co2.elec, one('Clean').co2.elec + one('Dirty').co2.elec, 1e-9), 'two countries: each charged from its own grid, then summed');
  check(near(both.gridG, (0.030 + 0.620) / 2, 1e-9), 'reported grid intensity is generation-weighted');
  const flows = both.links.reduce((a, l) => { a[l.s] = (a[l.s] || 0) + l.v; return a; }, {});
  check(flows.Coal > 0 && flows.Renewables > 0, 'the Sankey draws the combined generation mix');
  const lossless = both.links.filter(l => l.t === 'Work at the wheel' || l.t === 'Supply loss' || l.t === 'Conversion loss').reduce((a, l) => a + l.v, 0);
  check(near(lossless, both.primary, both.primary * 1e-9), 'energy is conserved: primary = work + losses');
  const petrol = feChain({ year: 2024, row: { BEV: 0, PHEV: 0, HEV: 0, DIESEL: 0, PETROL: 1e6, GASFUEL: 0 } }, 'trend');
  check(petrol.co2.elec === 0 && petrol.gridG === null && petrol.co2.oil > 0, 'a fleet without plug-ins has no grid emissions'); }

// ---- 6. how far a car is driven ---------------------------------------------
{ fleetState.calibration.Far = { mileage: { year: 2025, ALL: 22800, PETROL: 20000, DIESEL: 30000, BEV: 25000 } };
  const m = feMileage('Far'), d = feMileage('Nowhere');
  check(m.PETROL === 20000 && m.BEV === 25000 && m.GASFUEL === 20000, "a country's own km per car are used (gas cars as petrol)");
  check(near(m.PHEV, FE_F.km_phev * 22800 / FE_F.km_all, 1e-9), 'a class the office does not report: the default at the country level');
  check(d.PETROL === FE_F.km_petrol && d.BEV === FE_F.km_bev, 'no figures: the defaults');
  check(near(fePerVehicle('BEV', 25000).carrierElec, FE_F.cons_bev / 100 * 25000, 1e-9) && fePerVehicle('BEV').km === FE_F.km_bev, 'energy per car scales with its km');
  const cars = n => ({ BEV: n.BEV || 0, PHEV: 0, HEV: 0, DIESEL: 0, PETROL: n.PETROL || 0, GASFUEL: 0 });
  const far = feChain({ year: 2024, row: cars({ PETROL: 1e6 }), parts: [{ country: 'Far', row: cars({ PETROL: 1e6 }) }] });
  const std = feChain({ year: 2024, row: cars({ PETROL: 1e6 }), parts: [{ country: 'Nowhere', row: cars({ PETROL: 1e6 }) }] });
  check(near(far.co2.oil / std.co2.oil, 20000 / FE_F.km_petrol, 1e-9), 'emissions follow the km: same cars, driven further, emit in proportion');
  check(near(far.km, 20000 * 1e6, 1) && near(far.cars, 1e6, 1e-6), 'the chain reports the vehicle-km it used');
  // Electrification must not add driving: km per car stays where it was.
  const before = cars({ PETROL: 9e5, BEV: 1e5 }), after = cars({ PETROL: 1e5, BEV: 9e5 });
  const k0 = feAverageKm('Far', before), k1 = feAverageKm('Far', after);
  check(k1 > k0, 'unscaled, a fleet of battery cars would drive more per car (' + Math.round(k0) + ' -> ' + Math.round(k1) + ')');
  const held = feChain({ year: 2030, row: after, parts: [{ country: 'Far', row: after, kmScale: k0 / k1 }] });
  check(near(held.km / held.cars, k0, 1e-6), 'with kmScale the country still drives ' + Math.round(k0) + ' km per car');
  const two = feChain({ year: 2024, row: cars({ PETROL: 2e6 }), parts: [{ country: 'Far', row: cars({ PETROL: 1e6 }) }, { country: 'Nowhere', row: cars({ PETROL: 1e6 }) }] });
  check(near(two.co2.oil, far.co2.oil + std.co2.oil, 1e-9), 'two countries: each driven at its own mileage, then summed');
  const flows = two.links.filter(l => l.s === 'Petrol').reduce((a, l) => a + l.v, 0), crude = two.links.find(l => l.s === 'Crude oil' && l.t === 'Petrol').v;
  check(near(flows, crude, 1e-9), 'Sankey links stay balanced when countries are combined'); }

console.log(JSON.stringify(out));
`;
eval(src + '\n' + TESTS);
"""


def main():
    if not shutil.which("node"):
        print("SKIP: node not found")
        return 0
    res = subprocess.run(["node", "-e", HARNESS, str(ROOT / "scripts/js_extract.js"),
                          str(ROOT / "index.html"), json.dumps(NAMES)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print("FAIL: harness crashed\n" + res.stderr[-3000:])
        return 1
    checks = [(ok, msg) for ok, msg in json.loads(res.stdout)]

    # ---- static checks on the page ------------------------------------------
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    for cat in ["BEV", "PHEV", "HEV", "HYBRID", "PETROL", "DIESEL", "OTHERS"]:
        m_html = re.search(rf'<input id="haz{cat}"[^>]*value="([0-9.]+)"', html)
        m_js = re.search(rf"getElementById\('haz{cat}'\)\?\.value, ([0-9.]+)\)", html)
        checks.append((bool(m_html and m_js) and float(m_html.group(1)) == float(m_js.group(1)),
                       f"haz{cat}: markup default = code fallback"))
    rates = {c: float(re.search(rf'<input id="haz{c}"[^>]*value="([0-9.]+)"', html).group(1))
             for c in ["BEV", "PHEV", "HEV", "PETROL", "DIESEL"]}
    checks.append((rates["BEV"] == rates["PETROL"] == rates["PHEV"] == rates["HEV"],
                   "defaults claim no lifetime difference between BEV, hybrids and petrol"))
    checks.append((rates["DIESEL"] > rates["PETROL"], "diesel default turnover is above petrol"))
    checks.append((bool(re.search(r'<input id="hazardSlope"[^>]*value="0"', html)),
                   "the projection-time age curve is off by default (slope 0)"))
    shape_html = re.search(r'<input id="weibullShape"[^>]*value="([0-9.]+)"', html)
    shape_js = re.findall(r"weibullShape[^\n]{0,60}, ([0-9.]+)\)", html)
    checks.append((bool(shape_html) and len(shape_js) >= 2 and all(float(v) == float(shape_html.group(1)) for v in shape_js),
                   f"Weibull shape: markup default = code fallbacks ({shape_html.group(1) if shape_html else None}, {shape_js})"))
    fit = ROOT / "fleet" / "survival_fit.csv"
    if fit.exists():
        import csv as _csv
        import statistics as _st
        with fit.open(newline="", encoding="utf-8") as fh:
            usable = [float(r["shape"]) for r in _csv.DictReader(fh) if r["usable"] == "yes"]
        checks.append((len(usable) >= 5 and bool(shape_html)
                       and abs(round(_st.median(usable), 1) - float(shape_html.group(1))) < 1e-9,
                       f"default shape = median of the usable fits in fleet/survival_fit.csv ({usable})"))
    checks.append((bool(re.search(r'<input type="checkbox" id="fleetCalibrate" checked>', html)),
                   "calibration is on by default"))
    checks.append((bool(re.search(r'name="feGridScen" value="trend" checked', html)),
                   "default grid scenario is the country's own trend, not the net-zero path"))
    checks.append((all(f'name="feGridScen" value="{v}"' in html for v in ("trend", "nze", "constant")),
                   "three grid scenarios are offered"))
    checks.append(("rows.filter(isCars)" in html and "v === 'whole'" in html,
                   "only passenger-car (Whole) rows of the stock file are read"))
    for f in ("fleet/fleet_calibration.json", "fleet/grid_mix.csv"):
        checks.append((f"./{f}" in html and (ROOT / f).exists(), f"the page loads {f} and the file exists"))

    bad = [msg for ok, msg in checks if not ok]
    for msg in bad:
        print("FAIL:", msg)
    print(f"{len(checks) - len(bad)}/{len(checks)} passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
