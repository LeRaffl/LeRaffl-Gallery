/* Tag boxplots — one horizontal boxplot per reference group and metric
   (Speed, Timing), with curly braces over the lower 25 %, middle 50 % and
   upper 25 % in the tag colours, labelled with the tag and its cut-off.

   Used in two places, always with the live params.csv:
   • sources/tags.html ("How the tags work", built by build_source_pages.py):
     TagBoxplots.mount(el, {params:'../params.csv'}) after loading
     assets/fit_core.js + assets/tag_system.js — the same files the gallery
     loads, so the page can never drift from the gallery's tags.
   • index.html's tag popover: TagBoxplots.svg(...) with the hovered market
     highlighted, fed from window.__bevTagPoints / __bevTagCutoffs.
   Needs fit_core.js + tag_system.js loaded first (globals). */
(function(){
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const METRICS = {
    timing: { name: 'Timing', axis: 'fitted year at 10 % BEV share',
      fmt: v => String(Math.round(v)), fmtCut: v => v.toFixed(1), fmtFine: v => v.toFixed(1),
      bands: [ { v: 'early', label: 'Early starter', short: 'Early', col: 'var(--accent,#1d4f91)', op: '≤' },
               { v: 'mid', label: 'no timing pill', short: '', col: 'var(--muted-2,#8a877e)' },
               { v: 'late_start', label: 'Late starter', short: 'Late', col: 'var(--thr-late-txt,#c0562b)', op: '≥' } ] },
    speed: { name: 'Speed', axis: 'slope at inflection, %/yr',
      fmt: v => (v * 100).toFixed(1), fmtCut: v => (v * 100).toFixed(1), fmtFine: v => (v * 100).toFixed(2) + ' %/yr',
      bands: [ { v: 'slow', label: 'Slow', col: 'var(--warn,#9a6a00)', op: '≤' },
               { v: 'avg', label: 'Avg speed', short: '', col: 'var(--muted-2,#8a877e)' },
               { v: 'fast', label: 'Fast', col: 'var(--thr-past-txt,#2e8a57)', op: '≥' } ] },
  };
  const val = (p, metric) => metric === 'timing' ? p.t10 : p.speed;

  // points: enriched rows (tagComputeAll); only eligible reference rows of the
  // group are drawn; `highlight` = one enriched row (may be a subset row).
  function svg(o){
    const { group, metric, cut, points, highlight, compact } = o;
    const M = METRICS[metric], d = cut && cut[metric];
    if (!d) return '';
    const pts = (points || []).filter(p => p.group === group && p.ref && p.eligible && isFinite(val(p, metric)));
    const W = compact ? 300 : 720, padL = 14, padR = 14;
    const yBrace = compact ? 30 : 40, yBox = compact ? 58 : 78, boxH = compact ? 14 : 22;
    const H = compact ? 90 : 128;
    if (!d.ok){
      return `<svg class="tbp" viewBox="0 0 ${W} 40" width="100%" role="img" aria-label="${esc(M.name)}: too few markets">` +
        `<text x="${W/2}" y="24" text-anchor="middle" class="tbp-dim">${d.n} market${d.n === 1 ? '' : 's'} — fewer than 4, no ${esc(M.name.toLowerCase())} tag</text></svg>`;
    }
    const vs = pts.map(p => val(p, metric)).sort((a, b) => a - b);
    const iqr = d.hi - d.lo || 1;
    const med = vs.length ? vs[Math.floor((vs.length - 1) / 2)] * ((vs.length % 2) ? 1 : 0.5) + ((vs.length % 2) ? 0 : vs[vs.length / 2] * 0.5) : NaN;
    // Long tails (extrapolated 2090s, near-vertical slopes) are clipped at
    // 2 IQR beyond the box and drawn as an arrow at the edge.
    const lo = Math.max(vs[0], d.lo - 2 * iqr), hi = Math.min(vs[vs.length - 1], d.hi + 2 * iqr);
    const span = (hi - lo) || 1, x0 = lo - span * 0.03, x1 = hi + span * 0.03;
    const X = v => padL + (Math.min(Math.max(v, x0), x1) - x0) / (x1 - x0) * (W - padL - padR);
    const segs = [[x0, d.lo], [d.lo, d.hi], [d.hi, x1]];
    const out = [];
    out.push(`<svg class="tbp" viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="${esc(M.name)} boxplot">`);
    segs.forEach(([a, b], i) => {
      const band = M.bands[i], xa = X(a) + (i ? 2 : 0), xb = X(b) - (i < 2 ? 2 : 0), m = (xa + xb) / 2;
      const r = Math.max(1, Math.min(8, (xb - xa) / 4)), h = compact ? 7 : 9;
      out.push(`<rect x="${xa}" y="${yBrace}" width="${Math.max(0, xb - xa)}" height="${yBox - yBrace - 4}" rx="3" fill="${band.col}" opacity="0.10"/>`);
      out.push(`<path d="M${xa},${yBrace + h} Q${xa},${yBrace} ${xa + r},${yBrace} L${m - r},${yBrace} Q${m},${yBrace} ${m},${yBrace - h} ` +
               `Q${m},${yBrace} ${m + r},${yBrace} L${xb - r},${yBrace} Q${xb},${yBrace} ${xb},${yBrace + h}" fill="none" stroke="${band.col}" stroke-width="2" stroke-linecap="round"/>`);
      const cutTxt = i === 0 ? ` ${band.op} ${M.fmtCut(d.lo)}` : i === 2 ? ` ${band.op} ${M.fmtCut(d.hi)}` : '';
      // Outer labels hug the outer edge, so three labels never collide even
      // when a band is narrow; the compact (popover) variant uses short names.
      const name = compact && band.short != null ? band.short : band.label;
      const anchor = i === 0 ? 'start' : i === 2 ? 'end' : 'middle';
      const lx = i === 0 ? xa : i === 2 ? xb : m;
      out.push(`<text x="${lx}" y="${yBrace - h - 5}" text-anchor="${anchor}" class="tbp-lab${compact ? ' tbp-lab--c' : ''}" fill="${band.col}">${esc(name)}${esc(cutTxt)}</text>`);
    });
    const yc = yBox + boxH / 2;
    out.push(`<line x1="${X(vs[0])}" x2="${X(vs[vs.length - 1])}" y1="${yc}" y2="${yc}" class="tbp-wh"/>`);
    out.push(`<rect x="${X(d.lo)}" y="${yBox}" width="${X(d.hi) - X(d.lo)}" height="${boxH}" rx="3" class="tbp-box"/>`);
    if (isFinite(med)) out.push(`<line x1="${X(med)}" x2="${X(med)}" y1="${yBox}" y2="${yBox + boxH}" class="tbp-med"/>`);
    pts.forEach((p, i) => {
      const v = val(p, metric), clipped = v < x0 || v > x1;
      const jy = yc + (((i * 37) % 11) - 5) * (boxH / 14);
      out.push(`<circle cx="${X(v)}" cy="${jy}" r="${compact ? 2.2 : 3}" class="tbp-dot${clipped ? ' tbp-dot--clip' : ''}">` +
               `<title>${esc(p.country)}: ${esc(M.fmtFine(v))}${clipped ? ' (off scale)' : ''}</title></circle>`);
    });
    if (highlight && isFinite(val(highlight, metric))){
      const hx = X(val(highlight, metric));
      out.push(`<line x1="${hx}" x2="${hx}" y1="${yBox - 6}" y2="${yBox + boxH + 6}" class="tbp-hl-line"/>` +
               `<circle cx="${hx}" cy="${yc}" r="${compact ? 4.5 : 6}" class="tbp-hl"><title>${esc(highlight.key || highlight.country)}</title></circle>`);
    }
    out.push(`<text x="${padL}" y="${H - 4}" class="tbp-dim">${esc(M.fmt(lo))}</text>` +
             `<text x="${W - padR}" y="${H - 4}" text-anchor="end" class="tbp-dim">${esc(M.fmt(hi))}</text>` +
             `<text x="${W / 2}" y="${H - 4}" text-anchor="middle" class="tbp-dim">${esc(M.axis)} · ${d.n} markets</text>`);
    out.push('</svg>');
    return out.join('');
  }

  const CSS = `.tbp{display:block;overflow:visible;font-family:inherit}
.tbp-lab{font-size:12px;font-weight:700;letter-spacing:.03em}
.tbp-lab--c{font-size:11px}
.tbp-dim{font-size:11px;fill:var(--muted,#55534c)}
.tbp-box{fill:var(--accent-wash,#eaf0f8);stroke:var(--accent,#1d4f91);stroke-width:1.2}
.tbp-wh{stroke:var(--muted-2,#8a877e);stroke-width:1.2}
.tbp-med{stroke:var(--accent,#1d4f91);stroke-width:2.2}
.tbp-dot{fill:var(--text,#1a1a18);opacity:.55}
.tbp-dot:hover{opacity:1;r:5}
.tbp-dot--clip{fill:var(--muted-2,#8a877e)}
.tbp-hl{fill:var(--thr-late-txt,#c0562b);stroke:var(--bg,#fff);stroke-width:2}
.tbp-hl-line{stroke:var(--thr-late-txt,#c0562b);stroke-width:1.5;stroke-dasharray:3 2}
.tbp-group{margin:0 0 26px}
.tbp-group h3{font-size:15px;margin:18px 0 4px}
.tbp-group .tbp-sub{font-size:12px;color:var(--muted,#55534c);margin:0 0 6px}
.tbp-pick{margin:0 0 14px;font-size:14px}`;
  function injectCss(){
    if (document.getElementById('tbpCss')) return;
    const st = document.createElement('style'); st.id = 'tbpCss'; st.textContent = CSS;
    document.head.appendChild(st);
  }

  async function mount(el, urls){
    injectCss();
    el.innerHTML = '<p class="tbp-sub">Loading the live cut-offs…</p>';
    try {
      const csv = await fetch(urls.params).then(r => r.text());
      const { enriched, cutoffs } = tagComputeAll(parseCSV(csv));
      const subsetsOf = g => Object.entries(TAG_PARENT).filter(([, p]) => p === g).map(([k]) => k);
      const groups = Object.keys(cutoffs).sort((a, b) =>
        (a === 'whole' ? -1 : b === 'whole' ? 1 : cutoffs[b].timing.n - cutoffs[a].timing.n));
      const opts = enriched.filter(e => e.eligible).map(e => e.key).sort();
      const render = hlKey => {
        const hl = enriched.find(e => e.key === hlKey);
        el.querySelector('.tbp-list').innerHTML = groups.map(g => {
          const c = cutoffs[g], subs = subsetsOf(g);
          const h = hl && hl.group === g ? hl : null;
          return `<div class="tbp-group"><h3>${esc(c.label)}</h3>` +
            `<p class="tbp-sub">${subs.length ? 'Also the scale for: ' + esc(subs.join(', ')) + '. ' : ''}` +
            `Reference rows: ${c.timing.n} (timing) / ${c.speed.n} (speed) markets.</p>` +
            svg({ group: g, metric: 'timing', cut: c, points: enriched, highlight: h }) +
            svg({ group: g, metric: 'speed',  cut: c, points: enriched, highlight: h }) + '</div>';
        }).join('');
      };
      el.innerHTML = `<label class="tbp-pick">Highlight a market: <select><option value="">—</option>${
        opts.map(k => `<option>${esc(k)}</option>`).join('')}</select></label><div class="tbp-list"></div>`;
      el.querySelector('select').addEventListener('change', e => render(e.target.value));
      render(new URLSearchParams(location.search).get('market') || '');
      if (location.search) { const s = el.querySelector('select'); s.value = new URLSearchParams(location.search).get('market') || ''; }
    } catch (e) {
      el.innerHTML = '<p class="tbp-sub">The live boxplots could not be loaded.</p>';
    }
  }

  window.TagBoxplots = { svg, mount, injectCss };
})();
