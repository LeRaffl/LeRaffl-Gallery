/* Tag system v2 (#294) — the single implementation of the gallery tags.
   Used by index.html (cards, filters, popover), sources/tags.html (live
   boxplots) and scripts/tag_system_report.js / tests (node). Needs
   assets/fit_core.js loaded first (inv_x_years, rowHasNoTransition,
   fitReliability, parseCSV). Spec: docs/architecture/61-tag-system.md. */

// Status is absolute: fitted 80 % crossing vs today and the 2035 target.
const TAG_PAST_THRESHOLD = 0.8;
const TAG_TARGET_YEAR    = 2035;
function statusTagFor(t80, now){
  if (!isFinite(t80)) return null;
  const d = now || new Date();
  const today = d.getUTCFullYear() + d.getUTCMonth() / 12;
  if (t80 <= today)            return { v: 'past',    label: 'Past 80%' };
  if (t80 <= TAG_TARGET_YEAR)  return { v: 'ontrack', label: 'On track' };
  return                              { v: 'late',    label: 'Late' };
}

// ── Tag system v2 (#294) ────────────────────────────────────────────────
// Speed and timing tags are relative: a market is Fast/Slow or an Early/Late
// starter compared with the other markets of the SAME vehicle group, never
// against a pool that mixes cars with trucks. Electric trucks only reached
// the market years after electric cars, so a fixed calendar cut (the old
// "10 % before 2023") could never award a truck market "Early starter".
//   • Reference groups: only BASE variants define a distribution. Whole is
//     the reference for cars; HDV, Vans, Buses, 2-Wheelers, … are their own
//     references. A subset (Private, Industry, Rental, Used, …) never feeds the
//     cut-offs — it is classified against its parent's distribution ("the
//     boxplot of Whole"). The subset → parent mapping is TAG_PARENT; add a
//     line there when a new subset variant appears. A variant missing from
//     the map is its own reference group.
//   • Timing is share-based: each row's fitted 10 % crossing year. Markets
//     still below 10 % count with their extrapolated year. Early = earliest
//     quarter of the group (≤ 25th percentile), Late = latest quarter
//     (≥ 75th percentile); the middle half carries no timing pill.
//   • Speed: the same quartiles of the inflection slope, per group.
//   • A reference group needs TAG_MIN_GROUP countries (one reference row
//     each) in a pool, otherwise that tag is withheld for the group and all
//     its subsets (quartiles of 2–3 markets are not a ranking).
// Pool = rows that transition (not rowHasNoTransition) and whose fit is not
// excluded by fitReliability(); provisional fits count. Status (80 % / 2035)
// is absolute and unchanged.
const TAG_MIN_GROUP = 4;
const TAG_LOW_Q  = 0.25;
const TAG_HIGH_Q = 0.75;
// Subset variant (lower case) → parent reference variant (lower case).
const TAG_PARENT = {
  'private':      'whole',   // private keepers
  'industry':     'whole',   // company / VAT-registered keepers
  'rental':       'whole',
  'nonrental':    'whole',
  'used':         'whole',   // used imports at first national registration
  'used imports': 'whole',
  'resale':       'whole',
  'fleet':        'whole',
  'custom':       'whole',   // Germany KBA custom passenger-car slice
  'wholesale':    'whole',   // China CPCA passenger-car wholesale
  '4-wheelers':   'whole',   // India cars and other four-wheelers
  'pickups':      'vans',    // Canada StatCan pickup trucks, GVWR ≤ 14,000 lb (N1 + part N2)
};
function tagVariantKey(variant){
  const v = String(variant || '').trim().toLowerCase();
  return v || 'whole';
}
// Reference group a row is compared against.
function tagGroupOf(variant){
  const v = tagVariantKey(variant);
  return TAG_PARENT[v] || v;
}
// True when the row itself defines its group's distribution.
function tagIsReference(variant){
  return !TAG_PARENT[tagVariantKey(variant)];
}
function tagGroupLabel(group, variant){
  if (group === 'whole') return 'Cars (Whole)';
  // A subset row names its parent group, a reference row its own variant.
  return tagIsReference(variant) ? String(variant || group).trim()
    : ({ vans: 'Vans', hdv: 'HDV', buses: 'Buses' }[group] || group);
}
function tagQuantile(sorted, q){
  if (!sorted.length) return NaN;
  const idx = (sorted.length - 1) * q;
  const lo = Math.floor(idx), hi = Math.ceil(idx);
  if (lo === hi) return sorted[lo];
  return sorted[lo] * (hi - idx) + sorted[hi] * (idx - lo);
}
// items: [{ group, label, country, t10, speed, eligible, ref }]
// → { [group]: { label, timing: {n, lo, hi, ok}, speed: {n, lo, hi, ok} } }
// Only reference rows (ref = true) feed a group, one per country (the first
// one wins), so n = countries = values. Subset rows are ignored here.
function tagGroupCutoffs(items){
  const acc = {};
  for (const it of items){
    if (!it.ref) continue;
    const g = acc[it.group] || (acc[it.group] = { label: it.label,
      t: [], s: [], tc: new Set(), sc: new Set(), seen: new Set() });
    if (!it.eligible || g.seen.has(it.country)) continue;
    g.seen.add(it.country);
    if (isFinite(it.t10))   { g.t.push(it.t10);   g.tc.add(it.country); }
    if (isFinite(it.speed)) { g.s.push(it.speed); g.sc.add(it.country); }
  }
  const out = {};
  for (const [k, g] of Object.entries(acc)){
    const dim = (vals, set) => {
      const v = vals.slice().sort((a, b) => a - b);
      const ok = set.size >= TAG_MIN_GROUP;
      return { n: set.size, ok,
               lo: ok ? tagQuantile(v, TAG_LOW_Q)  : NaN,
               hi: ok ? tagQuantile(v, TAG_HIGH_Q) : NaN };
    };
    out[k] = { label: g.label, timing: dim(g.t, g.tc), speed: dim(g.s, g.sc) };
  }
  return out;
}
function timingTagFor(t10, cut){
  if (!cut || !cut.ok || !isFinite(t10)) return null;
  if (t10 <= cut.lo) return { v: 'early',      label: 'Early starter' };
  if (t10 >= cut.hi) return { v: 'late_start', label: 'Late starter' };
  return null; // middle half → no timing pill
}
function speedTagFor(speed, cut){
  if (!cut || !cut.ok || !isFinite(speed)) return null;
  if (speed >= cut.hi) return { v: 'fast', label: 'Fast' };
  if (speed <= cut.lo) return { v: 'slow', label: 'Slow' };
  return                      { v: 'avg',  label: 'Avg speed' };
}

// Slope (dS/dz) at the inflection point of 1 − exp(v1 · z^v2): the Speed
// metric. NaN without an inflection point (v2 ≤ 1).
function tagSlopeAtInflection(v1raw, v2raw){
  let k = +v2raw, v1n = +v1raw;
  if (v1n === 0) v1n = -1e-24;
  if (!isFinite(k) || !isFinite(v1n)) return NaN;
  if (v1n >= 0 || k <= 1) return NaN;
  const invLambda = Math.pow(-v1n, 1/k);
  const u = Math.pow((k - 1) / k, 1/k);
  return k * invLambda * Math.pow(u, k - 1) * Math.exp(-Math.pow(u, k));
}
// Phase 1 + 2 of the tags for parsed params.csv rows: every row enriched with
// t80 / t10 / speed / reliability / group, plus the per-group cut-offs.
// The single implementation — the gallery tags, the boxplots on
// sources/tags.html and scripts/tag_system_report.js all call this.
function tagComputeAll(rows, pastThreshold){
  const enriched = rows.map(row => {
    const variant = String(row.variant || '').trim();
    const key = (!variant || variant.toLowerCase() === 'whole')
      ? row.country
      : `${row.country} (${variant})`;
    // inv_x_years returns the calendar year of the crossing directly.
    const t80res = inv_x_years(pastThreshold ?? TAG_PAST_THRESHOLD, row.v1, row.v2, row.t0);
    const t10res = inv_x_years(0.10,                 row.v1, row.v2, row.t0);
    // Empty ttm_bev_share stays NaN ("unknown"), never 0; out-of-range too
    // (a stray column shift can put a year in this field).
    const ttmRaw = String(row.ttm_bev_share ?? '').trim();
    const ttm = ttmRaw !== '' ? Number(ttmRaw.replace(',', '.')) : NaN;
    const v2n = Number(String(row.v2 ?? '').replace(',', '.'));
    const group = tagGroupOf(variant);
    const e = {
      key,
      country: String(row.country || '').trim(),
      variant: variant || 'Whole',
      group,
      groupLabel: tagGroupLabel(group, variant),
      ref: tagIsReference(variant),
      noTrans: rowHasNoTransition(row),
      t80: t80res && isFinite(t80res.x) ? t80res.x : NaN,
      t10: t10res && isFinite(t10res.x) ? t10res.x : NaN,
      speed: tagSlopeAtInflection(row.v1, row.v2),
      obs: isFinite(ttm) && ttm >= 0 && ttm <= 1 ? ttm : NaN,
      // Share at the inflection point (S-shaped fits only).
      inflShare: isFinite(v2n) && v2n > 1 ? 1 - Math.exp(-(v2n - 1) / v2n) : NaN,
      rel: fitReliability(row),
    };
    // Excluded fits stay out of the pools: a collapsed curve carries a huge
    // inflection slope and would drag the "Fast" cut-off up with it.
    e.eligible = !e.noTrans && e.rel.status !== 'excluded';
    return e;
  });
  const cutoffs = tagGroupCutoffs(enriched.map(e => ({
    group: e.group, label: e.groupLabel, country: e.country,
    t10: e.t10, speed: e.speed, eligible: e.eligible, ref: e.ref })));
  return { enriched, cutoffs };
}


// Display only: a fractional (decimal) year as "Mon YYYY", e.g. 2021.9 →
// "Nov 2021". Month = floor(frac × 12) + 1, clamped to Jan–Dec; a tiny
// epsilon keeps float noise (2021.99999999 for 2022.0) from slipping a month
// back. Calculations keep the raw number — never feed this back in.
const TAG_MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
function tagFmtYearMonth(y){
  if (typeof y !== 'number' || !isFinite(y)) return '—';
  let yr = Math.floor(y + 1e-9), m = Math.floor((y - yr) * 12 + 1e-9);
  if (m < 0) m = 0; if (m > 11) m = 11;
  return `${TAG_MONTHS[m]} ${yr}`;
}

// ── Sidebar tag filter (filter sidebar v2) ──────────────────────────────
// Four groups of chips. Nothing selected in a group = that group does not
// filter. Values inside a group are OR-ed (a row has exactly one value per
// group, so AND would always be empty); groups are AND-ed.
const TAG_FILTER_GROUPS = [
  { cat: 'fit',    label: 'Fit',    values: [['reliable', 'Reliable'], ['unreliable', 'Volatile / unreliable'], ['notrans', 'No transition']] },
  { cat: 'status', label: 'Status', values: [['past', 'Past 80%'], ['ontrack', 'On track'], ['late', 'Late']] },
  { cat: 'speed',  label: 'Speed',  values: [['fast', 'Fast'], ['avg', 'Avg'], ['slow', 'Slow']] },
  { cat: 'timing', label: 'Start',  values: [['early', 'Early'], ['mid', 'Mid'], ['late_start', 'Late']] },
];
// The one value a row has in a filter group, or null = "no tag" (the row
// drops out as soon as a value of that group is selected).
//   fit:    notrans | unreliable | reliable. A chart without a params row
//           has no verdict and counts as reliable.
//   status/speed/timing: null for no-transition and unreliable rows (they
//           carry no such pill) and for speed/timing when the reference
//           group has fewer than TAG_MIN_GROUP markets (tags.noscale).
//   timing: a scaled row without a timing pill sits in the middle half: mid.
function tagFilterValue(tags, cat){
  if (cat === 'fit') return tags && tags.notrans ? 'notrans' : tags && tags.unsettled ? 'unreliable' : 'reliable';
  if (!tags || tags.notrans || tags.unsettled) return null;
  if ((cat === 'speed' || cat === 'timing') && tags.noscale && tags.noscale[cat]) return null;
  if (cat === 'timing') return (tags.timing && tags.timing.v) || 'mid';
  return (tags[cat] && tags[cat].v) || null;
}
// filters = { cat: Set(values) } holding only groups with a selection.
function tagFilterPasses(tags, filters, skipCat){
  for (const cat of Object.keys(filters)) {
    if (cat === skipCat) continue;
    const v = tagFilterValue(tags, cat);
    if (!v || !filters[cat].has(v)) return false;
  }
  return true;
}
// Live chip counts: for every chip, how many items the result would hold if
// that chip were the selection of its group, with the OTHER groups'
// selections applied (the usual facet count; an already selected chip shows
// its own share). items = rows after the non-tag filters; tagsOf(item) →
// that item's tag set.
function tagFilterCounts(items, filters, tagsOf){
  const out = {};
  for (const g of TAG_FILTER_GROUPS) { out[g.cat] = {}; for (const [v] of g.values) out[g.cat][v] = 0; }
  for (const it of items) {
    const tags = tagsOf(it);
    for (const g of TAG_FILTER_GROUPS) {
      if (!tagFilterPasses(tags, filters, g.cat)) continue;
      const v = tagFilterValue(tags, g.cat);
      if (v && v in out[g.cat]) out[g.cat][v]++;
    }
  }
  return out;
}

if (typeof module !== 'undefined') module.exports = { TAG_PAST_THRESHOLD, TAG_TARGET_YEAR, statusTagFor,
  TAG_MIN_GROUP, TAG_LOW_Q, TAG_HIGH_Q, TAG_PARENT, tagVariantKey, tagGroupOf, tagIsReference, tagGroupLabel,
  tagQuantile, tagGroupCutoffs, timingTagFor, speedTagFor, tagSlopeAtInflection, tagComputeAll,
  TAG_FILTER_GROUPS, tagFilterValue, tagFilterPasses, tagFilterCounts, tagFmtYearMonth };
