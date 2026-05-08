/**
 * Cloudflare Worker — LeRaffl Gallery proxy
 *
 * GET  /issues          → fetch GitHub issues, map to our shape, cache 60 s
 * POST /issues          → validate + create a new GitHub issue
 * POST /submissions     → validate, upsert rows into data/<Country>.csv on a
 *                         new branch, open a PR for review
 *
 * Required secret (set via `wrangler secret put GITHUB_TOKEN`):
 *   GITHUB_TOKEN — fine-grained PAT on leraffl-gallery with
 *     Issues: Read+Write, Contents: Read+Write,
 *     Pull requests: Read+Write, Metadata: Read.
 */

const GITHUB_OWNER = 'leraffl';
const GITHUB_REPO  = 'leraffl-gallery';
const MAINTAINER   = 'leraffl';            // GitHub username whose replies get is_maintainer: true
const FEEDBACK_LABEL = 'feedback';
const HIDDEN_LABEL   = 'hidden';
const PINNED_LABEL   = 'pinned';

// Allowed origin — update if you serve from a custom domain
const ALLOWED_ORIGIN = 'https://leraffl.github.io';

// Rate-limiting: max submissions per IP per window
const RATE_LIMIT_MAX    = 3;
const RATE_LIMIT_WINDOW = 60 * 60; // 1 hour in seconds

// ── helpers ────────────────────────────────────────────────────────────────

function corsHeaders(origin) {
  const allowed = origin === ALLOWED_ORIGIN || origin === 'http://localhost' || (origin && origin.startsWith('http://127.'));
  return {
    'Access-Control-Allow-Origin':  allowed ? origin : ALLOWED_ORIGIN,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age':       '86400',
  };
}

function json(data, status = 200, origin = '') {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

function err(msg, status = 400, origin = '') {
  return json({ error: msg }, status, origin);
}

// ── GitHub API ──────────────────────────────────────────────────────────────

async function ghFetch(path, token, opts = {}) {
  const res = await fetch(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}${path}`, {
    ...opts,
    headers: {
      Accept:        'application/vnd.github+json',
      Authorization: `Bearer ${token}`,
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent':  'LeRaffl-Gallery-Worker/1.0',
      ...(opts.headers || {}),
    },
  });
  return res;
}

// Map a raw GitHub issue + its comments to our public shape
function mapIssue(ghIssue, comments = []) {
  const labels = (ghIssue.labels || []).map(l => l.name);

  // Derive category from feedback:{category} label
  const catLabel = labels.find(l => l.startsWith('feedback:'));
  const category = catLabel ? catLabel.replace('feedback:', '') : 'question';

  // Derive status: closed → resolved; maintainer replied → answered; else open
  let status = 'open';
  if (ghIssue.state === 'closed') {
    status = 'resolved';
  } else if (comments.some(c => c.user?.login?.toLowerCase() === MAINTAINER.toLowerCase())) {
    status = 'answered';
  }

  // Parse context + version stored in issue body as trailing JSON block
  let body = ghIssue.body || '';
  let context = {};
  let version = {};

  const ctxMatch = body.match(/\n*<!-- context:([\s\S]*?)-->/);
  if (ctxMatch) {
    try { context = JSON.parse(ctxMatch[1].trim()); } catch (_) {}
    body = body.replace(ctxMatch[0], '').trim();
  }
  const verMatch = body.match(/\n*<!-- version:([\s\S]*?)-->/);
  if (verMatch) {
    try { version = JSON.parse(verMatch[1].trim()); } catch (_) {}
    body = body.replace(verMatch[0], '').trim();
  }

  // Strip the "Submitted by: X" footer we append on POST
  const authorMatch = body.match(/\n*---\n\*Submitted by: (.+?)\*/s);
  const author = authorMatch ? authorMatch[1].trim() : (ghIssue.user?.login || 'Anonymous');
  if (authorMatch) body = body.replace(authorMatch[0], '').trim();

  return {
    number:     ghIssue.number,
    title:      ghIssue.title,
    body,
    category,
    status,
    author,
    pinned:     labels.includes(PINNED_LABEL),
    created_at: ghIssue.created_at,
    updated_at: ghIssue.updated_at,
    context,
    version,
    comments: comments.map(c => ({
      author:        c.user?.login || 'Unknown',
      is_maintainer: c.user?.login?.toLowerCase() === MAINTAINER.toLowerCase(),
      body:          c.body || '',
      created_at:    c.created_at,
    })),
  };
}

// ── GET /issues ─────────────────────────────────────────────────────────────

async function handleGet(request, env, ctx) {
  const origin = request.headers.get('Origin') || '';
  const cacheKey = new Request('https://internal-cache/issues-v1', { method: 'GET' });
  const cache = caches.default;

  // Try Cloudflare cache first
  const cached = await cache.match(cacheKey);
  if (cached) {
    const body = await cached.json();
    return json(body, 200, origin);
  }

  const token = env.GITHUB_TOKEN;

  // Fetch all open + closed issues with the feedback label (up to 100)
  const ghRes = await ghFetch(
    `/issues?labels=${FEEDBACK_LABEL}&state=all&per_page=100&sort=created&direction=desc`,
    token,
  );
  if (!ghRes.ok) {
    return err('Failed to fetch issues from GitHub', 502, origin);
  }
  const ghIssues = await ghRes.json();

  // Filter out hidden issues
  const visible = ghIssues.filter(i => !(i.labels || []).some(l => l.name === HIDDEN_LABEL));

  // Fetch comments for each issue in parallel (max 50 per issue)
  const issuesWithComments = await Promise.all(
    visible.map(async issue => {
      if (issue.comments === 0) return mapIssue(issue, []);
      const cRes = await ghFetch(`/issues/${issue.number}/comments?per_page=50`, token);
      const comments = cRes.ok ? await cRes.json() : [];
      return mapIssue(issue, comments);
    })
  );

  const payload = {
    updated: new Date().toISOString(),
    issues:  issuesWithComments,
  };

  // Store in Cloudflare cache for 60 seconds
  ctx.waitUntil(
    cache.put(cacheKey, new Response(JSON.stringify(payload), {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'public, max-age=60',
      },
    }))
  );

  return json(payload, 200, origin);
}

// ── POST /issues ─────────────────────────────────────────────────────────────

async function handlePost(request, env, ctx) {
  const origin = request.headers.get('Origin') || '';
  const ip     = request.headers.get('CF-Connecting-IP') || 'unknown';

  // Rate limiting via KV (requires a KV namespace bound as RATE_KV in wrangler.toml)
  if (env.RATE_KV) {
    const kvKey  = `rl:${ip}`;
    const stored = await env.RATE_KV.get(kvKey);
    const count  = stored ? parseInt(stored, 10) : 0;
    if (count >= RATE_LIMIT_MAX) {
      return err('Too many submissions. Please try again later.', 429, origin);
    }
    ctx.waitUntil(
      env.RATE_KV.put(kvKey, String(count + 1), { expirationTtl: RATE_LIMIT_WINDOW })
    );
  }

  let payload;
  try {
    payload = await request.json();
  } catch (_) {
    return err('Invalid JSON body', 400, origin);
  }

  // ── Server-side honeypot check ──
  if (payload._hp && payload._hp !== '') {
    // Silently accept (to fool bots) but don't create the issue
    return json({ number: 0, ok: true }, 200, origin);
  }

  // ── Validate required fields ──
  const { title, body, category, author, context, version, math_answer, math_expected } = payload;

  if (!title || typeof title !== 'string' || title.trim().length < 5) {
    return err('Title must be at least 5 characters.', 400, origin);
  }
  if (!body || typeof body !== 'string' || body.trim().length < 10) {
    return err('Description must be at least 10 characters.', 400, origin);
  }
  const validCategories = ['question', 'data', 'idea', 'bug'];
  if (!validCategories.includes(category)) {
    return err('Invalid category.', 400, origin);
  }

  // ── Server-side math captcha check ──
  // math_expected is the correct answer (number), math_answer is what the user typed.
  // We sent math_expected as part of the form payload — verify they match.
  if (math_expected === undefined || math_answer === undefined) {
    return err('Missing captcha fields.', 400, origin);
  }
  if (parseInt(String(math_answer).trim(), 10) !== parseInt(String(math_expected).trim(), 10)) {
    return err('Incorrect answer to the captcha. Please try again.', 400, origin);
  }

  // ── Sanitise strings ──
  const safeTitle  = title.trim().slice(0, 200);
  const safeBody   = body.trim().slice(0, 5000);
  const safeAuthor = (author || 'Anonymous').trim().slice(0, 60) || 'Anonymous';

  // ── Build GitHub issue body ──
  const contextBlock  = context  ? `\n<!-- context:${JSON.stringify(context)}-->` : '';
  const versionBlock  = version  ? `\n<!-- version:${JSON.stringify(version)}-->` : '';
  const ghBody = `${safeBody}\n\n---\n*Submitted by: ${safeAuthor}*${contextBlock}${versionBlock}`;

  // ── Create GitHub issue ──
  const token = env.GITHUB_TOKEN;
  const ghRes = await ghFetch('/issues', token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title:  safeTitle,
      body:   ghBody,
      labels: [FEEDBACK_LABEL, `feedback:${category}`],
    }),
  });

  if (!ghRes.ok) {
    const text = await ghRes.text();
    console.error('GitHub issue creation failed:', ghRes.status, text);
    return err('Failed to submit feedback. Please try again.', 502, origin);
  }

  const created = await ghRes.json();

  // Invalidate the GET cache so next load picks up the new issue
  ctx.waitUntil(caches.default.delete(new Request('https://internal-cache/issues-v1')));

  // Return the new issue in our shape (no comments yet)
  const mapped = mapIssue(created, []);
  // Patch author back since we embed it in the body footer
  mapped.author = safeAuthor;

  return json(mapped, 201, origin);
}

// ── Router ───────────────────────────────────────────────────────────────────

export default {
  async fetch(request, env, ctx) {
    const url    = new URL(request.url);
    const method = request.method.toUpperCase();
    const origin = request.headers.get('Origin') || '';

    // Preflight
    if (method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }

    if (url.pathname === '/issues') {
      if (method === 'GET')  return handleGet(request, env, ctx);
      if (method === 'POST') return handlePost(request, env, ctx);
    }

    if (url.pathname === '/submissions' && method === 'POST') {
      return handleSubmission(request, env, ctx);
    }

    return new Response('Not found', { status: 404, headers: corsHeaders(origin) });
  },
};

// ── POST /submissions ────────────────────────────────────────────────────────
// Body shape:
// {
//   country: "Germany",
//   variant: "Whole",
//   source:  "KBA",
//   rows: [
//     { period: "2026-04", time_interval: "monthly",
//       fuels: { BEV: 70000, PHEV: 30000, HEV: 87000, PETROL: 67000,
//                DIESEL: 38000, OTHERS: 1000, TOTAL: 293000 },
//       notes: "" }
//   ],
//   author: "optional name",
//   _hp: ""  // honeypot
// }
//
// Per-row upsert key is (period, variant). Existing rows for the same key are
// replaced; new rows are inserted in chronological order. The CSV's existing
// column set is preserved — we only overwrite the columns the submission
// names. New fuel categories not currently in the CSV are appended as new
// columns (so submitting EREV for a country that didn't have it adds the
// column with NA in pre-existing rows).

const ALLOWED_TIME_INTERVALS = new Set(['monthly', 'quarterly', 'yearly']);
const ALLOWED_FUEL_COLS = new Set([
  'BEV','PHEV','EREV','HEV','MHEV','PETROL','DIESEL','GAS','CNG','LPG',
  'FLEXFUEL','ETHANOL','OTHERS','ICE','TOTAL'
]);

async function handleSubmission(request, env, ctx) {
  const origin = request.headers.get('Origin') || '';
  const ip     = request.headers.get('CF-Connecting-IP') || 'unknown';

  // Rate limit (separate bucket from feedback so a chatty submitter doesn't
  // lock themselves out of asking questions).
  if (env.RATE_KV) {
    const kvKey  = `sub:${ip}`;
    const stored = await env.RATE_KV.get(kvKey);
    const count  = stored ? parseInt(stored, 10) : 0;
    if (count >= RATE_LIMIT_MAX) {
      return err('Too many submissions. Please try again later.', 429, origin);
    }
    ctx.waitUntil(
      env.RATE_KV.put(kvKey, String(count + 1), { expirationTtl: RATE_LIMIT_WINDOW })
    );
  }

  let payload;
  try { payload = await request.json(); }
  catch (_) { return err('Invalid JSON body', 400, origin); }

  if (payload._hp && payload._hp !== '') {
    return json({ ok: true, pr_url: null }, 200, origin);  // silently swallow bots
  }

  const { country, variant = 'Whole', source = '', rows = [], author = 'Anonymous' } = payload;

  if (typeof country !== 'string' || !country.trim()) return err('country is required', 400, origin);
  if (typeof variant !== 'string' || !variant.trim()) return err('variant is required', 400, origin);
  if (!Array.isArray(rows) || rows.length === 0)      return err('at least one row required', 400, origin);
  if (rows.length > 36)                               return err('too many rows in one submission', 400, origin);

  // Validate each row.
  const safeRows = [];
  for (const r of rows) {
    if (!r || typeof r !== 'object')                  return err('invalid row', 400, origin);
    if (!/^\d{4}-\d{2}$/.test(String(r.period || ''))) return err(`invalid period "${r.period}" (expected YYYY-MM)`, 400, origin);
    if (!ALLOWED_TIME_INTERVALS.has(r.time_interval)) return err(`invalid time_interval "${r.time_interval}"`, 400, origin);
    const fuels = r.fuels || {};
    if (typeof fuels !== 'object')                    return err('row.fuels must be an object', 400, origin);
    const cleanFuels = {};
    for (const [k, v] of Object.entries(fuels)) {
      if (!ALLOWED_FUEL_COLS.has(k))                  return err(`unknown fuel column "${k}"`, 400, origin);
      if (v === '' || v === null || v === undefined) continue;
      const n = Number(v);
      if (!Number.isFinite(n) || n < 0)               return err(`fuel ${k} must be a non-negative number`, 400, origin);
      cleanFuels[k] = n;
    }
    if (cleanFuels.TOTAL === undefined)               return err(`row ${r.period}: TOTAL is required`, 400, origin);
    if (cleanFuels.BEV === undefined)                 return err(`row ${r.period}: BEV is required`, 400, origin);
    // Sum sanity check: BEV + PHEV + EREV must not exceed TOTAL.
    const bev = cleanFuels.BEV || 0, phev = cleanFuels.PHEV || 0, erev = cleanFuels.EREV || 0;
    if (bev + phev + erev > cleanFuels.TOTAL * 1.005) {
      return err(`row ${r.period}: BEV+PHEV+EREV exceeds TOTAL`, 400, origin);
    }
    safeRows.push({
      period:        r.period,
      time_interval: r.time_interval,
      fuels:         cleanFuels,
      notes:         (typeof r.notes === 'string' ? r.notes : '').slice(0, 200),
    });
  }

  const safeCountry = country.trim().slice(0, 60);
  const safeVariant = variant.trim().slice(0, 30);
  const safeSource  = (source || '').trim().slice(0, 200);
  const safeAuthor  = (author || 'Anonymous').trim().slice(0, 60) || 'Anonymous';

  // ── Read current data/<Country>.csv from GitHub ──
  // Filename: matches render_country.R's expectation.
  // Whole variant → data/<Country>.csv ; non-Whole → data/<Country>_<Variant>.csv
  const filename = safeVariant === 'Whole'
    ? `data/${safeCountry}.csv`
    : `data/${safeCountry}_${safeVariant}.csv`;

  const token = env.GITHUB_TOKEN;
  const fileRes = await ghFetch(`/contents/${encodeURIComponent(filename).replace(/%2F/g, '/')}?ref=master`, token);
  let existing = null;   // { sha, content (utf8 string) }
  if (fileRes.status === 200) {
    const fileJson = await fileRes.json();
    existing = { sha: fileJson.sha, content: atob((fileJson.content || '').replace(/\n/g, '')) };
  } else if (fileRes.status !== 404) {
    return err(`Failed to read ${filename}`, 502, origin);
  }

  // ── Apply upserts ──
  const { newCsv, summary } = upsertRows(existing?.content, safeVariant, safeSource, safeRows);

  if (newCsv === existing?.content) {
    return err('Submission would not change the file (identical to current data).', 400, origin);
  }

  // ── Branch name ──
  const ts = new Date().toISOString().replace(/[:.TZ-]/g, '').slice(0, 14);
  const slug = `${safeCountry}-${safeVariant}`.replace(/[^A-Za-z0-9]+/g, '-').toLowerCase();
  const branch = `submit/${slug}-${ts}`;

  // ── Get master's head sha ──
  const refRes = await ghFetch(`/git/ref/heads/master`, token);
  if (!refRes.ok) return err('Failed to read master ref', 502, origin);
  const masterSha = (await refRes.json()).object.sha;

  // ── Create branch ──
  const createRefRes = await ghFetch(`/git/refs`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: `refs/heads/${branch}`, sha: masterSha }),
  });
  if (!createRefRes.ok) {
    const text = await createRefRes.text();
    console.error('Branch create failed:', createRefRes.status, text);
    return err('Failed to create branch', 502, origin);
  }

  // ── Commit new CSV onto branch ──
  const putRes = await ghFetch(`/contents/${encodeURIComponent(filename).replace(/%2F/g, '/')}`, token, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: `data: ${safeCountry} (${safeVariant}) — ${summary.added} added, ${summary.replaced} corrected`,
      content: btoa(unescape(encodeURIComponent(newCsv))),
      branch,
      ...(existing ? { sha: existing.sha } : {}),
    }),
  });
  if (!putRes.ok) {
    const text = await putRes.text();
    console.error('Commit failed:', putRes.status, text);
    return err('Failed to commit CSV', 502, origin);
  }

  // ── Open PR ──
  const prBody = buildPrBody({ country: safeCountry, variant: safeVariant, source: safeSource,
                                author: safeAuthor, summary, rows: safeRows });
  const prRes = await ghFetch(`/pulls`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: `data: ${safeCountry} (${safeVariant}) — ${summary.added} added, ${summary.replaced} corrected`,
      head:  branch,
      base:  'master',
      body:  prBody,
    }),
  });
  if (!prRes.ok) {
    const text = await prRes.text();
    console.error('PR open failed:', prRes.status, text);
    return err('Failed to open PR', 502, origin);
  }
  const pr = await prRes.json();

  return json({ ok: true, pr_url: pr.html_url, pr_number: pr.number, branch, summary }, 201, origin);
}

// ── CSV upsert ──────────────────────────────────────────────────────────────
// Returns { newCsv, summary: { added, replaced, replacedDetails: [...] } }.
// Header semantics: existing header is preserved; new fuel cols are appended
// to the end (so old rows stay byte-identical, only the touched rows + the
// header line move).

function upsertRows(existingCsv, variant, source, rows) {
  // Parse existing
  let lines = existingCsv ? existingCsv.replace(/\r\n/g, '\n').split('\n') : [];
  while (lines.length && lines[lines.length - 1] === '') lines.pop();
  let header;
  let existingDataLines;
  if (lines.length === 0) {
    // Brand new file. Build a sensible default header from the union of the
    // submitted columns, with the canonical order.
    const cols = ['period','time_interval','variant','source'];
    const fuelOrder = ['BEV','PHEV','EREV','HEV','MHEV','PETROL','DIESEL','GAS','CNG','LPG','FLEXFUEL','ETHANOL','OTHERS','ICE','TOTAL'];
    const presentFuels = new Set();
    for (const r of rows) for (const k of Object.keys(r.fuels)) presentFuels.add(k);
    for (const f of fuelOrder) if (presentFuels.has(f)) cols.push(f);
    cols.push('notes');
    header = cols.join(',');
    existingDataLines = [];
  } else {
    header = lines[0];
    existingDataLines = lines.slice(1);
  }

  let cols = header.split(',');
  // Ensure every submitted fuel column exists; append if missing.
  const submittedFuels = new Set();
  for (const r of rows) for (const k of Object.keys(r.fuels)) submittedFuels.add(k);
  const fuelOrder = ['BEV','PHEV','EREV','HEV','MHEV','PETROL','DIESEL','GAS','CNG','LPG','FLEXFUEL','ETHANOL','OTHERS','ICE','TOTAL'];
  const newFuelCols = [];
  for (const f of fuelOrder) {
    if (submittedFuels.has(f) && !cols.includes(f)) newFuelCols.push(f);
  }
  if (newFuelCols.length) {
    // Insert before "notes" if present; else append at end.
    const notesIdx = cols.indexOf('notes');
    if (notesIdx >= 0) cols = [...cols.slice(0, notesIdx), ...newFuelCols, ...cols.slice(notesIdx)];
    else cols = [...cols, ...newFuelCols];
    header = cols.join(',');
    // Pad existing lines with empty values for the new columns.
    existingDataLines = existingDataLines.map(line => padLineForNewCols(line, cols, newFuelCols, notesIdx));
  }

  const periodIdx  = cols.indexOf('period');
  const variantIdx = cols.indexOf('variant');
  if (periodIdx < 0 || variantIdx < 0) {
    throw new Error('CSV missing period/variant columns');
  }

  // Build a map keyed by (period, variant) for existing rows we may replace.
  // Also keep a parallel array of the line text for unchanged passthrough.
  const replaced = [];
  const added    = [];
  const newLines = [];
  const submittedKeys = new Set(rows.map(r => `${r.period}|${variant}`));

  // Helper to format a fuel value compactly. Integers stay as integers; one
  // decimal otherwise. NA → empty string.
  const fmt = v => {
    if (v === undefined || v === null || v === '') return '';
    if (Number.isInteger(v)) return String(v);
    return String(v);
  };

  for (const dl of existingDataLines) {
    const parts = dl.split(',');
    const key = `${parts[periodIdx]}|${parts[variantIdx]}`;
    if (submittedKeys.has(key)) {
      // We'll re-emit this row from the submission; capture old value for diff.
      const old = {};
      cols.forEach((c, i) => { old[c] = parts[i] ?? ''; });
      replaced.push({ key, old });
      continue;
    }
    newLines.push(dl);
  }

  // Build replacement / insert lines from the submission.
  for (const r of rows) {
    const key = `${r.period}|${variant}`;
    const wasReplaced = replaced.some(x => x.key === key);
    const fields = cols.map(c => {
      switch (c) {
        case 'period':        return r.period;
        case 'time_interval': return r.time_interval;
        case 'variant':       return variant;
        case 'source':        return source;
        case 'notes':         return r.notes || '';
        default:
          if (r.fuels[c] !== undefined) return fmt(r.fuels[c]);
          return '';
      }
    });
    const line = fields.join(',');
    newLines.push(line);
    if (!wasReplaced) added.push({ period: r.period });
  }

  // Sort by period (chronological), keeping yearly/quarterly mixed in by date.
  newLines.sort((a, b) => {
    const ap = a.split(',')[periodIdx];
    const bp = b.split(',')[periodIdx];
    return ap < bp ? -1 : ap > bp ? 1 : 0;
  });

  const newCsv = [header, ...newLines].join('\n') + '\n';
  return {
    newCsv,
    summary: {
      added: added.length,
      replaced: replaced.length,
      replacedDetails: replaced,
    },
  };
}

function padLineForNewCols(line, allCols, newCols, notesIdx) {
  const parts = line.split(',');
  // The original line was written with the OLD column count. New cols got
  // inserted before notes (or appended). Reconstruct so values stay aligned.
  if (notesIdx < 0) {
    // Appended at end — just push empties.
    while (parts.length < allCols.length) parts.push('');
    return parts.join(',');
  }
  // Inserted before notes: split parts at original notes position.
  const oldNotesIdx = notesIdx;       // notes index in OLD cols == same as in NEW cols up to insertion point
  const before = parts.slice(0, oldNotesIdx);
  const notesAndAfter = parts.slice(oldNotesIdx);
  return [...before, ...newCols.map(() => ''), ...notesAndAfter].join(',');
}

function buildPrBody({ country, variant, source, author, summary, rows }) {
  const lines = [];
  lines.push(`Submitted by **${author}** via Submit Data form.`);
  lines.push('');
  lines.push(`- **Country:** ${country}`);
  lines.push(`- **Variant:** ${variant}`);
  if (source) lines.push(`- **Source:** ${source}`);
  lines.push(`- **Added:** ${summary.added}`);
  lines.push(`- **Corrected:** ${summary.replaced}`);
  lines.push('');

  if (summary.replaced > 0) {
    lines.push('### Corrections');
    for (const det of summary.replacedDetails) {
      const period = det.key.split('|')[0];
      const submittedRow = rows.find(r => r.period === period);
      lines.push('');
      lines.push(`**${period}**`);
      lines.push('');
      lines.push('| field | before | after |');
      lines.push('|---|---|---|');
      for (const k of Object.keys(submittedRow.fuels)) {
        const before = det.old[k] ?? '';
        const after  = String(submittedRow.fuels[k]);
        if (String(before) !== after) lines.push(`| ${k} | ${before || '_(empty)_'} | ${after} |`);
      }
    }
    lines.push('');
  }

  if (summary.added > 0) {
    lines.push('### New rows');
    for (const r of rows) {
      const wasReplaced = summary.replacedDetails.some(d => d.key.startsWith(`${r.period}|`));
      if (wasReplaced) continue;
      const parts = Object.entries(r.fuels).map(([k, v]) => `${k}=${v}`).join(', ');
      lines.push(`- **${r.period}** (${r.time_interval}) — ${parts}`);
    }
    lines.push('');
  }

  lines.push('---');
  lines.push('');
  lines.push('After merge, trigger the **Render country charts** Action to regenerate plots.');
  return lines.join('\n');
}
