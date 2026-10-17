/* Fit core — shared by index.html, sources/tags.html (via tag_system.js)
   and scripts/tag_system_report.js / tests (node). Moved verbatim out of
   index.html (#294 tag refactor); classic script, so every declaration stays
   a global exactly as before. Loaded synchronously in index.html's <head>,
   before any inline script that uses it.

   parseCSV, normNumber, toYYYYMM, getDataPer, inv_x_years — params.csv
   parsing and the fitted crossing year.
   rowHasNoTransition — the "shows no transition" rule every tab uses.
   fitReliability (+ FIT_* constants) — the one reliability gate: unsettled
   (refit_swing), collapsed (10→80 % in < FIT_COLLAPSE_SPAN years while
   observed < FIT_COLLAPSE_OBS) or stale (> FIT_STALE_MONTHS old). */

// "No transition" = curve never enters a meaningful adoption regime.
//   • v2 > 1  → S-curve: use slope at the inflection point.
//   • v2 ≤ 1  → concave curve (no inflection): slope is infinite at t0 and
//               decelerates immediately. Use the slope at data_per instead,
//               which reflects how fast the curve is actually moving at the
//               most recent observation. Malta (v2=0.886, ~5pp/yr at data_per)
//               is correctly flagged as a real transition; Croatia/Italy
//               (~0.1pp/yr) are correctly flagged as no-transition.
// In both cases the threshold is MIN_TRANSITION_SLOPE (1pp/yr).
// Full row-level check — use this everywhere a params row is available.

// Fit reliability — the one gate every ranking, table, map and tag reads.
// A curve can be unusable for three different reasons, and each has its own
// test:
//   • unsettled — the projected 80 % crossing moved more than
//     FIT_UNSETTLED_SWING years across the recent re-fits (`refit_swing` in
//     params.csv; Inf = re-fits stopped producing a crossing at all).
//   • collapsed — the fit is a near-vertical step: it claims 10 %→80 % in
//     under FIT_COLLAPSE_SPAN years while the observed share has not even
//     reached FIT_COLLAPSE_OBS, so the whole claimed rise is extrapolation.
//     The fastest observed transitions (Norway ~8 y, Denmark ~5 y) are far
//     slower. A collapse that repeats on every refit (Argentina) is *stable*,
//     which is why refit_swing alone cannot catch it. A non-positive shape
//     counts as collapsed too.
//   • stale — the newest data point is more than FIT_STALE_MONTHS old, so the
//     curve describes a market we no longer observe (Belgium Vans: 2023-03).
// Excluded rows drop out of Thresholds, Durations, Time interval, the World
// Map and the tag quartiles; the chart itself stays in the gallery.
// Swing between FIT_PROVISIONAL_SWING and FIT_UNSETTLED_SWING keeps the row
// but flags it provisional. Rows that show no transition are left to
// rowHasNoTransition — callers check that first.
// "Inf" (R's infinity), an empty cell, or anything unparseable all mean the
// same thing: we cannot vouch for this curve.
// Fitted years from 10 % to 80 % share. Independent of t0: both crossings
// share the same origin, so it cancels.
function parseCSV(text){
  const raw=(text||'').trim(); if(!raw) return [];
  const first=raw.split(/\r?\n/)[0]||''; const delimiter=(first.match(/;/g)||[]).length>(first.match(/,/g)||[]).length?';':',';
  const lines=raw.split(/\r?\n/); const header=(()=>{ const {row}=splitCsvLine(lines.shift()||'',delimiter); return row.map(h=>h.replace(/^\uFEFF?/, '').trim()); })();
  const out=[]; for(const line of lines){ if(!line) continue; const {row}=splitCsvLine(line,delimiter); if(row.length===1&&row[0]==='') continue; const o={}; header.forEach((h,i)=>o[h]=(row[i]??'').trim()); out.push(o);} return out;
  function splitCsvLine(line,d){ const row=[]; let cur='',inQ=false; for(let i=0;i<line.length;i++){ const ch=line[i]; if(ch==='"'){ if(inQ && line[i+1]=='"'){cur+='"'; i++;} else inQ=!inQ; } else if(ch===d && !inQ){ row.push(cur); cur=''; } else { cur+=ch; } } row.push(cur); return {row}; }
}

const normNumber = x => { const s=String(x||'').trim().replace(',', '.'); const n=Number(s); return isFinite(n)?n:NaN; };

function toYYYYMM(s){ if(!s) return ''; if(/^\d{4}-\d{2}$/.test(s)) return s; if(/^\d{4}-\d{2}-\d{2}$/.test(s)) return s.slice(0,7); return ''; }

function getDataPer(r){ const c=[r.data_per,r.latest_month,r.last_month,r.month_latest,r.data_month,r.latest_date,r.last_date,r.obs_last,r.data_asof].map(x=>String(x||'').trim()).filter(Boolean); for(const v of c){ const m=toYYYYMM(v); if(m) return m; } return ''; }

function inv_x_years(y,v1,v2,t0){
  let v1n=normNumber(v1),
        v2n=normNumber(v2),
        t0n=normNumber(t0);
  // Defensive fallback only — applyV1Recovery() should already have replaced
  // v1=0 rows at load time. Reached only if a caller bypassed that path.
  if(v1n == 0) v1n = -1e-24;
  if(!(y>0&&y<1))
    return{x:NaN,why:'y∉(0,1)'}; 
  if(!isFinite(v1n)||!isFinite(v2n)||!isFinite(t0n))
    return{x:NaN,why:'v1/v2/t0 not numeric'}; 
  if(v2n===0)
    return{x:NaN,why:'v2=0'}; 
  if(v1n>=0)
    return{x:NaN,why:'v1 must be < 0'}; 
  const num=Math.log(1-y)/v1n;
  if(!(num>0))
    return{x:NaN,why:'ln(1-y)/v1 ≤ 0'};
  // CALENDAR-YEAR FIX (2026-06): return the calendar year of the crossing,
  // i.e. t0 + delta — NOT the historical (t0-1) + delta.
  //
  // Why the -1 was there and why it was wrong: the R pipeline's
  // period_to_year() maps "YYYY-MM" to (year-1)+(month-1)/12, so R fits and
  // plots in an internal axis that is one less than the calendar year, and
  // R re-adds the +1 only at label time (plots.R: labels = "Jan " + (x+1)).
  // t0 (= verschiebung) is stored in that internal space. The canonical
  // calendar share curve is therefore S(C) = 1 - exp(v1·(C - t0)^v2) — exactly
  // the world-map "share" formula (z = calYear - t0). Its inverse is
  // C = t0 + delta. The old (t0-1) returned R-internal units, which every
  // ABSOLUTE-date consumer (Thresholds table, Time-Interval timeline,
  // World-Map year mode, gallery status pills) then rendered verbatim as a
  // calendar year → every date shown 1 year too early (e.g. Finland Buses
  // "Past 80%" while the model only crosses 80% in 2027). Duration consumers
  // (Durations tab, Time-Interval spans) subtract two of these, so the
  // constant shift cancels and they are unaffected by this change.
  return{x:t0n+Math.pow(num,1/v2n),why:null};
}

const MIN_TRANSITION_SLOPE = 0.01;

function rowHasNoTransition(r){
  // Treat empty/missing ttm_bev_share as unknown (NaN), not 0.
  // normNumber('') returns 0 which would wrongly trigger the <1% check.
  const ttmRaw = String(r.ttm_bev_share ?? '').trim();
  const ttmBev = ttmRaw !== '' ? Number(ttmRaw.replace(',', '.')) : NaN;
  if (isFinite(ttmBev) && ttmBev < 0.01) return true;   // < 1% BEV → clearly no transition
  if (isFinite(ttmBev) && ttmBev >= 0.05) return false;  // ≥ 5% BEV → clearly in transition
  const v1n = normNumber(r.v1), v2n = normNumber(r.v2);
  if(!isFinite(v1n) || !isFinite(v2n)) return true;
  if(v1n >= 0) return true;
  if(v2n > 1){
    const invLambda = Math.pow(-v1n, 1/v2n);
    const u = Math.pow((v2n - 1)/v2n, 1/v2n);
    const slope = v2n * invLambda * Math.pow(u, v2n - 1) * Math.exp(-Math.pow(u, v2n));
    if(!isFinite(slope)) return true;
    return slope < MIN_TRANSITION_SLOPE;
  }
  // v2 ≤ 1: use slope at data_per (calendar year)
  const dp = getDataPer(r);
  const dpMatch = dp.match(/^(\d{4})-(\d{2})$/);
  if(!dpMatch) return true;
  const calYear = Number(dpMatch[1]) + (Number(dpMatch[2]) - 1) / 12;
  const t0n = normNumber(r.t0);
  if(!isFinite(t0n)) return true;
  const z = calYear - t0n;
  if(z <= 0) return true;
  const slope = Math.abs(v1n) * v2n * Math.pow(z, v2n - 1) * Math.exp(v1n * Math.pow(z, v2n));
  if(!isFinite(slope)) return true;
  return slope < MIN_TRANSITION_SLOPE;
}

const FIT_UNSETTLED_SWING   = 25;   // years

const FIT_PROVISIONAL_SWING = 5;    // years

const FIT_COLLAPSE_SPAN     = 3;    // years from 10 % to 80 %

const FIT_COLLAPSE_OBS      = 0.10; // observed (TTM) BEV share

const FIT_STALE_MONTHS      = 12;

function parseRefitSwing(raw){
  const t = String(raw ?? '').trim();
  if (t === '') return Infinity;
  if (/^-?inf(inity)?$/i.test(t)) return Infinity;
  const n = Number(t.replace(',', '.'));
  return isFinite(n) ? n : Infinity;
}

function fitSpan10to80(v1, v2){
  if (!(isFinite(v1) && v1 < 0 && isFinite(v2) && v2 > 0)) return NaN;
  const z = p => Math.pow(Math.log(1 - p) / v1, 1 / v2);
  return z(0.80) - z(0.10);
}

function fitReliability(r, now){
  const v1 = normNumber(r.v1), v2 = normNumber(r.v2);
  const ttmRaw = String(r.ttm_bev_share ?? '').trim();
  const obs = ttmRaw !== '' ? Number(ttmRaw.replace(',', '.')) : NaN;
  // The swing gate only engages once params.csv carries the column, so a
  // gallery served alongside an older params.csv does not drop every row.
  const swing = Object.prototype.hasOwnProperty.call(r, 'refit_swing')
    ? parseRefitSwing(r.refit_swing) : NaN;
  const span = fitSpan10to80(v1, v2);
  const reasons = [];
  if (swing > FIT_UNSETTLED_SWING) reasons.push('unsettled');
  if (!(isFinite(v2) && v2 > 0) ||
      (span < FIT_COLLAPSE_SPAN && !(obs >= FIT_COLLAPSE_OBS))) reasons.push('collapsed');
  const dp = getDataPer(r).match(/^(\d{4})-(\d{2})$/);
  let ageMonths = NaN;
  if (dp) {
    const d = now || new Date();
    ageMonths = (d.getUTCFullYear() * 12 + d.getUTCMonth()) - (Number(dp[1]) * 12 + Number(dp[2]) - 1);
    if (ageMonths > FIT_STALE_MONTHS) reasons.push('stale');
  }
  const status = reasons.length ? 'excluded'
    : (swing > FIT_PROVISIONAL_SWING ? 'provisional' : 'ok');
  return { status, reasons, swing, span, obs, ageMonths, dataPer: dp ? dp[0] : '' };
}

if (typeof module !== 'undefined') module.exports = { parseCSV, normNumber, toYYYYMM, getDataPer, inv_x_years,
  MIN_TRANSITION_SLOPE, rowHasNoTransition, parseRefitSwing, fitSpan10to80, fitReliability };
