// Runs the gallery tag logic of index.html under node against params.csv.
// usage: node scripts/tag_system_report.js [index.html] [params.csv] [--legacy] [--json]
//   --legacy: old rules (one speed pool for every variant, timing cut at fixed
//             calendar years 2023 / 2025) for before/after comparisons.
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const args = process.argv.slice(2);
const flags = new Set(args.filter(a => a.startsWith('--')));
const pos = args.filter(a => !a.startsWith('--'));
const html = pos[0] || path.join(__dirname, '..', 'index.html');
const csv  = pos[1] || path.join(__dirname, '..', 'params.csv');
const NAMES = ['normNumber','toYYYYMM','getDataPer','MIN_TRANSITION_SLOPE','rowHasNoTransition',
  'FIT_UNSETTLED_SWING','FIT_PROVISIONAL_SWING','FIT_COLLAPSE_SPAN','FIT_COLLAPSE_OBS','FIT_STALE_MONTHS',
  'parseRefitSwing','fitSpan10to80','fitReliability','splitCsvLine','parseCSV','period_to_year','inv_x_years',
  'TAG_MIN_GROUP','TAG_LOW_Q','TAG_HIGH_Q','tagGroupOf','tagGroupLabel','tagQuantile','tagGroupCutoffs',
  'timingTagFor','speedTagFor'];
const have = n => new RegExp('^(?:function '+n+'\\s*\\(|(?:const|let|var) '+n+'\\b)','m').test(fs.readFileSync(html,'utf8'));
const code = execFileSync('node', [path.join(__dirname,'js_extract.js'), html, ...NAMES.filter(have)]).toString();
const api = new Function(code + '; return {' + NAMES.filter(have).join(',') + '};')();
module.exports = api;

function slope(v1raw, v2raw){
  let k = +v2raw, v1n = +v1raw; if (v1n === 0) v1n = -1e-24;
  if (!isFinite(k) || !isFinite(v1n) || v1n >= 0 || k <= 1) return NaN;
  const invL = Math.pow(-v1n, 1/k), u = Math.pow((k-1)/k, 1/k);
  return k * invL * Math.pow(u, k-1) * Math.exp(-Math.pow(u, k));
}
function run(legacy){
  const rows = api.parseCSV(fs.readFileSync(csv, 'utf8'));
  const E = rows.map(row => {
    const variant = String(row.variant || '').trim();
    const t10 = api.inv_x_years(0.10, row.v1, row.v2, row.t0);
    const group = api.tagGroupOf ? api.tagGroupOf(variant) : (variant.toLowerCase() || 'whole');
    return { country: String(row.country||'').trim(), variant: variant || 'Whole', group,
      label: api.tagGroupLabel ? api.tagGroupLabel(group, variant) : variant,
      noTrans: api.rowHasNoTransition(row), rel: api.fitReliability(row),
      t10: t10 && isFinite(t10.x) ? t10.x : NaN, speed: slope(row.v1, row.v2) };
  });
  const elig = e => !e.noTrans && e.rel.status !== 'excluded';
  let cuts;
  if (legacy) {
    const q = (s, p) => { const i=(s.length-1)*p, lo=Math.floor(i), hi=Math.ceil(i); return lo===hi?s[lo]:s[lo]*(hi-i)+s[hi]*(i-lo); };
    const sp = E.filter(elig).map(e => e.speed).filter(isFinite).sort((a,b)=>a-b);
    const all = { timing: { ok: true, legacy: true }, speed: { ok: true, lo: q(sp,.25), hi: q(sp,.75) } };
    cuts = new Proxy({}, { get: () => all });
  } else {
    cuts = api.tagGroupCutoffs(E.map(e => ({ ...e, eligible: elig(e) })));
  }
  const dist = {};
  for (const e of E){
    const d = dist[e.group] || (dist[e.group] = { label: e.label, rows: 0, countries: new Set(),
      timing: { early: 0, late_start: 0, none: 0 }, speed: { fast: 0, avg: 0, slow: 0, none: 0 } });
    d.rows++; d.countries.add(e.country);
    if (!elig(e)) { d.timing.none++; d.speed.none++; continue; }
    const c = cuts[e.group];
    let tm;
    if (legacy) tm = !isFinite(e.t10) ? null : e.t10 < 2023 ? {v:'early'} : e.t10 > 2025 ? {v:'late_start'} : null;
    else tm = api.timingTagFor(e.t10, c && c.timing);
    const sp = legacy ? (isFinite(e.speed) ? (e.speed >= c.speed.hi ? {v:'fast'} : e.speed <= c.speed.lo ? {v:'slow'} : {v:'avg'}) : null)
                      : api.speedTagFor(e.speed, c && c.speed);
    d.timing[tm ? tm.v : 'none']++; d.speed[sp ? sp.v : 'none']++;
  }
  for (const d of Object.values(dist)) d.countries = d.countries.size;
  return { dist, cuts: legacy ? null : cuts };
}
if (require.main === module) {
  const out = run(flags.has('--legacy'));
  if (flags.has('--json')) { console.log(JSON.stringify(out, null, 1)); }
  else for (const [g, d] of Object.entries(out.dist).sort((a,b)=>b[1].rows-a[1].rows)) {
    const c = out.cuts && out.cuts[g];
    console.log(`${d.label.padEnd(14)} rows=${String(d.rows).padStart(3)}  timing E/L/- ${d.timing.early}/${d.timing.late_start}/${d.timing.none}  speed F/A/S/- ${d.speed.fast}/${d.speed.avg}/${d.speed.slow}/${d.speed.none}` +
      (c ? `  cut t10 ${c.timing.ok ? c.timing.lo.toFixed(1)+'–'+c.timing.hi.toFixed(1) : 'n<4'} (n=${c.timing.n})` : ''));
  }
}
