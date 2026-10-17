// Runs the gallery tag logic (assets/fit_core.js + assets/tag_system.js — the
// files index.html and sources/tags.html load) under node against params.csv.
// usage: node scripts/tag_system_report.js [params.csv] [--by-variant] [--legacy] [--json]
//   --by-variant: one line per variant (with its reference group)
//   --legacy:     old rules (one speed pool for every variant, timing cut at
//                 fixed calendar years 2023 / 2025) for before/after comparisons.
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = path.join(__dirname, '..');
// One shared global scope, like two classic <script> tags in a page.
function loadTagApi(){
  const ctx = vm.createContext({ console, Date, Math, Number, String, Object, Set, Map, JSON, isFinite, isNaN, window: {} });
  for (const f of ['assets/fit_core.js', 'assets/tag_system.js', 'assets/tag_boxplots.js']) {
    vm.runInContext(fs.readFileSync(path.join(ROOT, f), 'utf8'), ctx, { filename: f });
  }
  // const/let live in the context's lexical scope, not on the global object
  return vm.runInContext(`({ parseCSV, rowHasNoTransition, fitReliability, inv_x_years,
    TAG_PARENT, TAG_MIN_GROUP, tagGroupOf, tagIsReference, tagGroupLabel, tagGroupCutoffs,
    timingTagFor, speedTagFor, statusTagFor, tagComputeAll, TagBoxplots: window.TagBoxplots })`, ctx);
}
module.exports = { loadTagApi, run };

const args = process.argv.slice(2);
const flags = new Set(args.filter(a => a.startsWith('--')));
const csv = args.filter(a => !a.startsWith('--'))[0] || path.join(ROOT, 'params.csv');

function run(legacy, byVariant, csvPath){
  const api = loadTagApi();
  const rows = api.parseCSV(fs.readFileSync(csvPath || csv, 'utf8'));
  const { enriched: E, cutoffs } = api.tagComputeAll(rows);
  const elig = e => e.eligible;
  let cuts;
  if (legacy) {
    const q = (s, p) => { const i=(s.length-1)*p, lo=Math.floor(i), hi=Math.ceil(i); return lo===hi?s[lo]:s[lo]*(hi-i)+s[hi]*(i-lo); };
    const sp = E.filter(elig).map(e => e.speed).filter(isFinite).sort((a,b)=>a-b);
    const all = { timing: { ok: true, legacy: true }, speed: { ok: true, lo: q(sp,.25), hi: q(sp,.75) } };
    cuts = new Proxy({}, { get: () => all });
  } else cuts = cutoffs;
  const dist = {};
  for (const e of E){
    const dk = byVariant ? e.variant : e.group;
    const d = dist[dk] || (dist[dk] = { label: byVariant ? `${e.variant} → ${e.groupLabel}` : e.groupLabel, group: e.group,
      rows: 0, countries: new Set(),
      timing: { early: 0, late_start: 0, none: 0 }, speed: { fast: 0, avg: 0, slow: 0, none: 0 } });
    d.rows++; d.countries.add(e.country);
    if (!elig(e)) { d.timing.none++; d.speed.none++; continue; }
    const c = cuts[e.group];
    const tm = legacy ? (!isFinite(e.t10) ? null : e.t10 < 2023 ? {v:'early'} : e.t10 > 2025 ? {v:'late_start'} : null)
                      : api.timingTagFor(e.t10, c && c.timing);
    const sp = legacy ? (isFinite(e.speed) ? (e.speed >= c.speed.hi ? {v:'fast'} : e.speed <= c.speed.lo ? {v:'slow'} : {v:'avg'}) : null)
                      : api.speedTagFor(e.speed, c && c.speed);
    d.timing[tm ? tm.v : 'none']++; d.speed[sp ? sp.v : 'none']++;
  }
  for (const d of Object.values(dist)) d.countries = d.countries.size;
  return { dist, cuts: legacy ? null : JSON.parse(JSON.stringify(cuts)) };
}
if (require.main === module) {
  const out = run(flags.has('--legacy'), flags.has('--by-variant'));
  if (flags.has('--json')) { console.log(JSON.stringify(out, null, 1)); }
  else for (const [g, d] of Object.entries(out.dist).sort((a,b)=>b[1].rows-a[1].rows)) {
    const c = out.cuts && out.cuts[d.group];
    console.log(`${d.label.padEnd(14)} rows=${String(d.rows).padStart(3)}  timing E/L/- ${d.timing.early}/${d.timing.late_start}/${d.timing.none}  speed F/A/S/- ${d.speed.fast}/${d.speed.avg}/${d.speed.slow}/${d.speed.none}` +
      (c ? `  cut t10 ${c.timing.ok ? c.timing.lo.toFixed(1)+'–'+c.timing.hi.toFixed(1) : 'n<4'} (n=${c.timing.n})` : ''));
  }
}
