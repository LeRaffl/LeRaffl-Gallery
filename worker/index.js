/**
 * Cloudflare Worker — LeRaffl Gallery feedback proxy
 *
 * GET  /issues          → fetch GitHub issues, map to our shape, cache 60 s
 * POST /issues          → validate + create a new GitHub issue
 *
 * Required secret (set via `wrangler secret put GITHUB_TOKEN`):
 *   GITHUB_TOKEN  — fine-grained PAT, Issues: Read+Write on leraffl-gallery
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

    return new Response('Not found', { status: 404, headers: corsHeaders(origin) });
  },
};
