/* Fleet figures — the charts on sources/fleet.html ("How the Fleet tab is
   calculated", built by scripts/build_source_pages.py from
   docs/architecture/65-fleet-model.md).

   Every figure is drawn from the files the Fleet tab itself reads, at page
   load, so the explainer can never show a number the tab does not use:
     fleet/fleet_calibration.json   turnover, age bands, inflow mix, mileage
     fleet/survival_fit.csv         the Weibull fits
     fleet/grid_mix.csv             grid CO2e intensity

   Usage:  FleetFigures.mount(document, {base: '../'})
   fills every element carrying data-fleet-fig="<name>" (see FIGURES below).
   Each figure gets a hover readout and a "Show the numbers" table.

   Colours. Charts stay light in dark mode like every chart on the site
   (docs/architecture/02-components.md §2.12), so each figure sits in a
   data-theme="light" frame. The four series colours were checked with the
   dataviz palette validator (lightness band, chroma floor, colour-vision
   separation, contrast): petrol / diesel / battery / hybrid. "Other" is a
   neutral grey on purpose — it is a remainder, not a series. */
(function(){
  const C = { petrol:'#3a78b5', diesel:'#c2622d', bev:'#1f9a8a', hybrid:'#8a5fb5',
              other:'#8a877e', ink:'#1a1a18', muted:'#55534c', faint:'#8a877e',
              grid:'#e4e2dd', accent:'#1d4f91', surface:'#ffffff' };
  const SEQ = ['#c5d6ec', '#86a9d6', '#4477b6', '#1d4f91'];   // one hue, light -> dark
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const int = v => Math.round(v).toLocaleString('en-US');
  const pct = (v, d) => (v * 100).toFixed(d == null ? 1 : d) + '%';
  const W = 720;

  function parseCSV(text){
    const lines = text.trim().split(/\r?\n/), head = lines.shift().split(',');
    return lines.map(l => { const c = l.split(','), o = {}; head.forEach((h, i) => o[h] = c[i]); return o; });
  }

  /* ---- shared pieces ------------------------------------------------------ */
  function legend(items){
    return '<div class="ff-legend">' + items.map(i =>
      `<span><i style="background:${i.c}${i.line ? ';height:3px;border-radius:0' : ''}"></i>${esc(i.label)}</span>`).join('') + '</div>';
  }
  function table(head, rows){
    return '<details class="ff-table"><summary>Show the numbers</summary><div class="ff-scroll"><table><thead><tr>'
      + head.map(h => `<th>${esc(h)}</th>`).join('') + '</tr></thead><tbody>'
      + rows.map(r => '<tr>' + r.map((c, i) => `<td${i ? ' class="n"' : ''}>${esc(c)}</td>`).join('') + '</tr>').join('')
      + '</tbody></table></div></details>';
  }
  function frame(el, title, sub, body){
    el.innerHTML = `<figure class="ff" data-theme="light"><figcaption><b>${esc(title)}</b><span>${esc(sub)}</span></figcaption>${body}<div class="ff-tip" hidden></div></figure>`;
    const tip = el.querySelector('.ff-tip'), fig = el.querySelector('.ff');
    el.querySelectorAll('[data-tip]').forEach(m => {
      const show = e => {
        tip.innerHTML = m.getAttribute('data-tip'); tip.hidden = false;
        const r = fig.getBoundingClientRect();
        const x = Math.min(Math.max(8, e.clientX - r.left + 12), r.width - tip.offsetWidth - 8);
        tip.style.left = x + 'px'; tip.style.top = (e.clientY - r.top + 14) + 'px';
      };
      m.addEventListener('mousemove', show);
      m.addEventListener('mouseenter', show);
      m.addEventListener('mouseleave', () => { tip.hidden = true; });
    });
  }
  // Horizontal axis with a few gridlines; returns {svg, x}.
  function xAxis(min, max, ticks, left, right, top, bottom, fmt){
    const x = v => left + (v - min) / (max - min) * (W - left - right);
    let s = '';
    ticks.forEach(t => {
      s += `<line x1="${x(t).toFixed(1)}" y1="${top}" x2="${x(t).toFixed(1)}" y2="${bottom}" stroke="${t === 0 ? C.faint : C.grid}" stroke-width="1"/>`
         + `<text x="${x(t).toFixed(1)}" y="${bottom + 14}" text-anchor="middle" class="ff-ax">${esc(fmt(t))}</text>`;
    });
    return { svg: s, x };
  }
  const rowLabel = (y, name) => `<text x="150" y="${(y + 4).toFixed(1)}" text-anchor="end" class="ff-lab">${esc(name)}</text>`;

  /* ---- 1. observed turnover ----------------------------------------------- */
  function turnover(el, d){
    const rows = Object.entries(d.cal.countries).filter(([, e]) => e.attrition)
      .map(([c, e]) => ({ c, v: e.attrition.rate, from: e.attrition.from, to: e.attrition.to }))
      .sort((a, b) => b.v - a.v);
    const rh = 19, top = 8, left = 158, H = top + rows.length * rh + 26;
    const ax = xAxis(-0.03, 0.10, [-0.02, 0, 0.02, 0.04, 0.06, 0.08, 0.10], left, 46, top, H - 22, v => pct(v, 0));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Observed net attrition of the car stock per country">` + ax.svg;
    rows.forEach((r, i) => {
      const y = top + i * rh + rh / 2, x0 = ax.x(0), x1 = ax.x(r.v);
      s += rowLabel(y, r.c)
        + `<rect x="${Math.min(x0, x1).toFixed(1)}" y="${(y - 5).toFixed(1)}" width="${Math.max(1.5, Math.abs(x1 - x0)).toFixed(1)}" height="10" rx="2" fill="${r.v < 0.01 ? C.diesel : C.accent}"/>`
        + `<text x="${(Math.max(x0, x1) + 5).toFixed(1)}" y="${(y + 4).toFixed(1)}" class="ff-val">${pct(r.v)}</text>`
        + `<rect x="0" y="${(y - rh / 2).toFixed(1)}" width="${W}" height="${rh}" fill="transparent" data-tip="<b>${esc(r.c)}</b><br>${pct(r.v, 2)} of the stock left per year, net<br>median of ${r.from}&ndash;${r.to}"/>`;
    });
    s += `<line x1="${ax.x(0.01).toFixed(1)}" y1="${top}" x2="${ax.x(0.01).toFixed(1)}" y2="${H - 22}" stroke="${C.muted}" stroke-width="1" stroke-dasharray="3 3"/></svg>`;
    frame(el, 'Observed net attrition of the car stock, per year',
      'last year’s stock + new registrations − this year’s stock, median of five years',
      legend([{ c: C.accent, label: 'modelled as cars leaving' }, { c: C.diesel, label: 'below 1%: the rest is booked as net used imports' }]) + s
      + table(['Country', 'Net attrition per year', 'Years'], rows.map(r => [r.c, pct(r.v, 2), r.from + '–' + r.to])));
  }

  /* ---- 2. age structure ---------------------------------------------------- */
  function ages(el, d){
    const names = ['under 5 years', '5–10', '10–20', 'over 20 years'];
    const rows = Object.entries(d.cal.countries).filter(([, e]) => e.age_bands).map(([c, e]) => {
      const y = Object.keys(e.age_bands).sort().pop(); return { c, y, b: e.age_bands[y] }; })
      .sort((a, b) => a.b[3] - b.b[3]);
    const rh = 19, top = 8, left = 158, H = top + rows.length * rh + 26;
    const ax = xAxis(0, 1, [0, 0.25, 0.5, 0.75, 1], left, 20, top, H - 22, v => pct(v, 0));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Age structure of the car stock per country">` + ax.svg;
    rows.forEach((r, i) => {
      const y = top + i * rh + rh / 2; let acc = 0;
      s += rowLabel(y, r.c);
      r.b.forEach((v, k) => {
        const x0 = ax.x(acc), x1 = ax.x(acc + v); acc += v;
        s += `<rect x="${(x0 + 1).toFixed(1)}" y="${(y - 6).toFixed(1)}" width="${Math.max(0, x1 - x0 - 2).toFixed(1)}" height="12" fill="${SEQ[k]}" data-tip="<b>${esc(r.c)}</b> ${r.y}<br>${names[k]}: ${pct(v)}"/>`;
      });
    });
    frame(el, 'How old each country’s cars are', 'share of the stock by age band, latest year on record (Eurostat)',
      legend(names.map((n, k) => ({ c: SEQ[k], label: n }))) + s + '</svg>'
      + table(['Country', 'Year', ...names], rows.map(r => [r.c, r.y, ...r.b.map(v => pct(v))])));
  }

  /* ---- 3. survival curve ---------------------------------------------------- */
  function gammaFn(z){   // Lanczos, good to 1e-10 for z > 0.5
    const g = 7, p = [0.99999999999980993, 676.5203681218851, -1259.1392167224028, 771.32342877765313,
      -176.61502916214059, 12.507343278686905, -0.13857109526572012, 9.9843695780195716e-6, 1.5056327351493116e-7];
    z -= 1; let x = p[0]; for (let i = 1; i < g + 2; i++) x += p[i] / (z + i);
    const t = z + g + 0.5; return Math.sqrt(2 * Math.PI) * Math.pow(t, z + 0.5) * Math.exp(-t) * x;
  }
  function survival(el, d){
    const fits = d.fit.filter(r => r.usable === 'yes').sort((a, b) => a.shape - b.shape);
    const shapes = fits.map(r => +r.shape);
    const lo = Math.min(...shapes), hi = Math.max(...shapes);
    const sorted = shapes.slice().sort((a, b) => a - b), mid = sorted.length / 2;
    const med = +(sorted.length % 2 ? sorted[Math.floor(mid)] : (sorted[mid - 1] + sorted[mid]) / 2).toFixed(1);
    const mean = 18;   // same average life for all three, so only the shape differs
    const series = [{ k: lo, c: C.diesel, label: `shape ${lo.toFixed(1)} (lowest fit)` },
                    { k: med, c: C.accent, label: `shape ${med.toFixed(1)} (median, the default)` },
                    { k: hi, c: C.bev, label: `shape ${hi.toFixed(1)} (highest fit)` }];
    const S = (a, k) => Math.exp(-Math.pow(a / (mean / gammaFn(1 + 1 / k)), k));
    const left = 46, right = 16, top = 12, H = 260, bottom = H - 34, maxA = 40;
    const x = a => left + a / maxA * (W - left - right), y = v => bottom - v * (bottom - top);
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Share of cars still in the fleet by age, for three Weibull shapes">`;
    [0, 0.25, 0.5, 0.75, 1].forEach(v => { s += `<line x1="${left}" y1="${y(v).toFixed(1)}" x2="${W - right}" y2="${y(v).toFixed(1)}" stroke="${C.grid}"/><text x="${left - 6}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end" class="ff-ax">${pct(v, 0)}</text>`; });
    [0, 10, 20, 30, 40].forEach(a => { s += `<text x="${x(a).toFixed(1)}" y="${bottom + 16}" text-anchor="middle" class="ff-ax">${a}</text>`; });
    s += `<text x="${(W - right)}" y="${H - 3}" text-anchor="end" class="ff-ax">age of the car, years</text>`;
    series.forEach(q => {
      let p = ''; for (let a = 0; a <= maxA; a += 0.5) p += (a ? 'L' : 'M') + x(a).toFixed(1) + ',' + y(S(a, q.k)).toFixed(1) + ' ';
      s += `<path d="${p}" fill="none" stroke="${q.c}" stroke-width="2"/>`;
    });
    for (let a = 1; a <= maxA; a++) {
      s += `<rect x="${(x(a) - (x(1) - x(0)) / 2).toFixed(1)}" y="${top}" width="${(x(1) - x(0)).toFixed(1)}" height="${bottom - top}" fill="transparent" data-tip="<b>${a} years old</b><br>${series.map(q => `shape ${q.k.toFixed(1)}: ${pct(S(a, q.k), 0)} still in the fleet`).join('<br>')}"/>`;
    }
    frame(el, 'How many cars are still in the fleet at each age',
      `Weibull survival curve, same average life (${mean} years), three shapes`,
      legend(series.map(q => ({ c: q.c, label: q.label, line: true }))) + s + '</svg>'
      + table(['Country', 'Fitted shape', 'Mean life (years)', 'Share over 20 years: observed', 'fitted'],
          fits.map(r => [r.country, r.shape, r.mean_life, pct(+r.share_gt20_observed), pct(+r.share_gt20_fitted)])));
  }

  /* ---- 4. mileage ------------------------------------------------------------ */
  function mileage(el, d){
    const rows = Object.entries(d.cal.countries).filter(([, e]) => e.mileage).map(([c, e]) => ({ c, m: e.mileage }))
      .sort((a, b) => b.m.ALL - a.m.ALL);
    const def = d.cal.mileage_default;
    if (def) rows.push({ c: 'Median (used for all other countries)', m: def, def: true });
    const keys = [['PETROL', 'petrol', C.petrol], ['DIESEL', 'diesel', C.diesel], ['BEV', 'battery', C.bev]];
    const rh = 22, top = 8, left = 158, H = top + rows.length * rh + 26;
    const ax = xAxis(0, 20000, [0, 5000, 10000, 15000, 20000], left, 20, top, H - 22, v => int(v));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Kilometres per car and year by fuel, per country">` + ax.svg;
    rows.forEach((r, i) => {
      const y = top + i * rh + rh / 2;
      const name = r.def ? 'Median' : r.c;
      const vals = keys.filter(k => r.m[k[0]] > 0).map(k => r.m[k[0]]);
      s += `<text x="150" y="${(y + 4).toFixed(1)}" text-anchor="end" class="ff-lab"${r.def ? ' font-weight="700"' : ''}>${esc(name)}</text>`;
      if (vals.length > 1) s += `<line x1="${ax.x(Math.min(...vals)).toFixed(1)}" y1="${y}" x2="${ax.x(Math.max(...vals)).toFixed(1)}" y2="${y}" stroke="${C.grid}" stroke-width="2"/>`;
      s += `<line x1="${ax.x(r.m.ALL).toFixed(1)}" y1="${y - 7}" x2="${ax.x(r.m.ALL).toFixed(1)}" y2="${y + 7}" stroke="${C.ink}" stroke-width="2"/>`;
      keys.forEach(k => { if (r.m[k[0]] > 0) s += `<circle cx="${ax.x(r.m[k[0]]).toFixed(1)}" cy="${y}" r="5" fill="${k[2]}" stroke="${C.surface}" stroke-width="2"/>`; });
      const tip = `<b>${esc(r.c)}</b>${r.m.year ? ' ' + r.m.year : ''}<br>all cars: ${int(r.m.ALL)} km`
        + keys.map(k => r.m[k[0]] > 0 ? `<br>${k[1]}: ${int(r.m[k[0]])} km` : '').join('');
      s += `<rect x="0" y="${(y - rh / 2).toFixed(1)}" width="${W}" height="${rh}" fill="transparent" data-tip="${tip}"/>`;
    });
    frame(el, 'How far a car is driven per year', 'km per car of the year-end stock, latest year (Eurostat; SSB for Norway)',
      legend([{ c: C.ink, label: 'all cars', line: true }, ...keys.map(k => ({ c: k[2], label: k[1] }))]) + s + '</svg>'
      + table(['Country', 'Year', 'All cars', 'Petrol', 'Diesel', 'Battery', 'Plug-in hybrid', 'Full hybrid'],
          rows.map(r => [r.c, r.m.year || '', ...['ALL', 'PETROL', 'DIESEL', 'BEV', 'PHEV', 'HEV'].map(k => r.m[k] > 0 ? int(r.m[k]) : '—')])));
  }

  /* ---- 5. inflow mix ---------------------------------------------------------- */
  function inflow(el, d){
    const keys = [['HEV', 'full hybrid', C.hybrid], ['PETROL', 'petrol', C.petrol], ['DIESEL', 'diesel', C.diesel], ['OTHERS', 'gas and other', C.other]];
    const rows = Object.entries(d.cal.countries).filter(([, e]) => e.inflow_mix).map(([c, e]) => ({ c, m: e.inflow_mix }))
      .sort((a, b) => b.m.HEV - a.m.HEV);
    const rh = 19, top = 8, left = 158, H = top + rows.length * rh + 26;
    const ax = xAxis(0, 1, [0, 0.25, 0.5, 0.75, 1], left, 20, top, H - 22, v => pct(v, 0));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Split of combustion-side registrations per country">` + ax.svg;
    rows.forEach((r, i) => {
      const y = top + i * rh + rh / 2; let acc = 0;
      s += rowLabel(y, r.c);
      keys.forEach(k => {
        const v = r.m[k[0]] || 0, x0 = ax.x(acc), x1 = ax.x(acc + v); acc += v;
        if (v > 0) s += `<rect x="${(x0 + 1).toFixed(1)}" y="${(y - 6).toFixed(1)}" width="${Math.max(0, x1 - x0 - 2).toFixed(1)}" height="12" fill="${k[2]}" data-tip="<b>${esc(r.c)}</b><br>${k[1]}: ${pct(v)} of non-plug-in registrations<br>${esc(r.m.window)}"/>`;
      });
    });
    frame(el, 'What the cars that are not plug-ins are', 'last 12 months of registrations, share of everything that is neither battery nor plug-in hybrid',
      legend(keys.map(k => ({ c: k[2], label: k[1] }))) + s + '</svg>'
      + table(['Country', ...keys.map(k => k[1]), 'Months'], rows.map(r => [r.c, ...keys.map(k => pct(r.m[k[0]] || 0)), r.m.window])));
  }

  /* ---- 6. grid ------------------------------------------------------------------ */
  function grid(el, d){
    const last = {};
    d.grid.forEach(r => { if (r.gco2_kwh !== '') last[r.country] = r; });
    const rows = Object.values(last).map(r => ({ c: r.country, y: r.year, v: +r.gco2_kwh })).sort((a, b) => a.v - b.v);
    const rh = 19, top = 8, left = 158, H = top + rows.length * rh + 26;
    const ax = xAxis(0, 800, [0, 200, 400, 600, 800], left, 44, top, H - 22, v => int(v));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Grid CO2e intensity per country">` + ax.svg;
    rows.forEach((r, i) => {
      const y = top + i * rh + rh / 2, world = r.c === 'World';
      s += `<text x="150" y="${(y + 4).toFixed(1)}" text-anchor="end" class="ff-lab"${world ? ' font-weight="700"' : ''}>${esc(r.c)}</text>`
        + `<rect x="${ax.x(0).toFixed(1)}" y="${(y - 5).toFixed(1)}" width="${Math.max(1.5, ax.x(r.v) - ax.x(0)).toFixed(1)}" height="10" rx="2" fill="${world ? C.ink : C.accent}"/>`
        + `<text x="${(ax.x(r.v) + 5).toFixed(1)}" y="${(y + 4).toFixed(1)}" class="ff-val">${int(r.v)}</text>`
        + `<rect x="0" y="${(y - rh / 2).toFixed(1)}" width="${W}" height="${rh}" fill="transparent" data-tip="<b>${esc(r.c)}</b> ${r.y}<br>${int(r.v)} gCO₂e per kWh generated"/>`;
    });
    frame(el, 'How clean the electricity is', 'gCO₂e per kWh generated, latest year (Ember)',
      legend([{ c: C.accent, label: 'country' }, { c: C.ink, label: 'world average, the old value for every country' }]) + s + '</svg>'
      + table(['Country', 'Year', 'gCO₂e/kWh'], rows.map(r => [r.c, r.y, int(r.v)])));
  }

  const FIGURES = { turnover, ages, survival, mileage, inflow, grid };
  const CSS = `
.ff{position:relative;margin:14px 0 6px;padding:14px 14px 10px;background:#fff;border:1px solid var(--line,#e4e2dd);border-radius:10px;color:#1a1a18}
.ff figcaption{display:flex;flex-direction:column;gap:2px;margin-bottom:8px}
.ff figcaption b{font-size:14.5px}.ff figcaption span{font-size:12.5px;color:#55534c}
.ff svg{display:block;font-family:var(--font-ui,system-ui,sans-serif)}
.ff .ff-ax{font-size:10.5px;fill:#8a877e}.ff .ff-lab{font-size:11.5px;fill:#1a1a18}.ff .ff-val{font-size:10.5px;fill:#55534c}
.ff-legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin:0 0 8px;font-size:12px;color:#55534c}
.ff-legend i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.ff-tip{position:absolute;z-index:5;pointer-events:none;max-width:280px;padding:7px 10px;font-size:12px;line-height:1.45;background:#1a1a18;color:#fff;border-radius:6px}
.ff-table{margin-top:8px;font-size:12.5px}.ff-table summary{cursor:pointer;color:#1d4f91}
.ff-scroll{overflow-x:auto;margin-top:6px}
.ff-table table{border-collapse:collapse;width:100%}.ff-table th,.ff-table td{padding:3px 8px;border-bottom:1px solid #e4e2dd;text-align:left;white-space:nowrap}
.ff-table td.n,.ff-table th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}
.ff-miss{font-size:13px;color:var(--muted,#55534c)}`;

  async function mount(root, opts){
    const base = (opts && opts.base) || '';
    const els = [...(root || document).querySelectorAll('[data-fleet-fig]')];
    if (!els.length) return;
    if (!document.getElementById('ff-css')) {
      const st = document.createElement('style'); st.id = 'ff-css'; st.textContent = CSS; document.head.appendChild(st);
    }
    const get = async (p, kind) => { const r = await fetch(base + p, { cache: 'no-store' }); if (!r.ok) throw new Error(p + ' ' + r.status); return kind === 'json' ? r.json() : r.text(); };
    let d;
    try {
      const [cal, fit, grd] = await Promise.all([get('fleet/fleet_calibration.json', 'json'), get('fleet/survival_fit.csv'), get('fleet/grid_mix.csv')]);
      d = { cal, fit: parseCSV(fit), grid: parseCSV(grd) };
    } catch (e) {
      els.forEach(el => { el.innerHTML = '<p class="ff-miss">This figure is drawn from the live data files and could not load them.</p>'; });
      return;
    }
    els.forEach(el => {
      const f = FIGURES[el.getAttribute('data-fleet-fig')];
      try { if (f) f(el, d); } catch (e) { el.innerHTML = '<p class="ff-miss">This figure could not be drawn.</p>'; console.warn('fleet figure', e); }
    });
  }
  // `draw` and `parseCSV` are exported for scripts/test_fleet_explainer.py.
  window.FleetFigures = { mount, names: Object.keys(FIGURES), draw: (name, el, data) => FIGURES[name](el, data), parseCSV };
})();
