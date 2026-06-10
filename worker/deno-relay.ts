// Deno Deploy fetch-relay — same contract as the Cloudflare Worker /fetch
// endpoint in worker/index.js, but egressing from Google Cloud IP ranges
// instead of Cloudflare's. Used for hosts (duurzamemobiliteit.databank.nl)
// that 403 Cloudflare egress IPs as well as GitHub's Azure ranges.
//
// Deploy (gratis, no credit card):
//   1. https://dash.deno.com → sign in with GitHub → New Playground
//   2. Paste this file, Save & Deploy
//   3. Project Settings → Environment Variables → RELAY_TOKEN=<random secret>
//   4. Repo secrets: NL_FETCH_RELAY=https://<project>.deno.dev/fetch?url=
//                    NL_RELAY_TOKEN=<same random secret>
//
// Contract (identical to the CF worker, see scripts/fetch_netherlands.py _get):
//   GET /fetch?url=<urlencoded https URL>     host-allowlisted
//   X-Relay-Token           → must match RELAY_TOKEN env (if set)
//   X-Fwd-User-Agent        → forwarded upstream as User-Agent
//   X-Fwd-Cookie            → forwarded upstream as Cookie
//   X-Fwd-Referer           → forwarded upstream as Referer
//   X-Fwd-Accept-Language   → forwarded upstream as Accept-Language
//   response X-Upstream-Set-Cookie ← upstream Set-Cookie headers, \n-joined

const ALLOW_HOSTS = new Set([
  "duurzamemobiliteit.databank.nl", // Netherlands (RDW via Swing)
  "www.statistik.at",               // Austria (fallback if CF relay dies)
  "data.statistik.gv.at",
]);

Deno.serve(async (req: Request) => {
  const url = new URL(req.url);
  if (url.pathname !== "/fetch" || req.method !== "GET") {
    return new Response("Not found", { status: 404 });
  }

  const token = Deno.env.get("RELAY_TOKEN");
  if (token && req.headers.get("X-Relay-Token") !== token) {
    return new Response("Unauthorized", { status: 401 });
  }

  const target = url.searchParams.get("url");
  if (!target) return new Response("missing url param", { status: 400 });

  let t: URL;
  try {
    t = new URL(target);
  } catch {
    return new Response("bad url", { status: 400 });
  }
  if (t.protocol !== "https:" || !ALLOW_HOSTS.has(t.hostname)) {
    return new Response(`host not allowed: ${t.hostname}`, { status: 403 });
  }

  const upstreamHeaders: Record<string, string> = {
    "User-Agent": req.headers.get("X-Fwd-User-Agent") ?? "LeRaffl-Gallery-Relay/1.0",
    "Accept": "*/*",
  };
  const fwdCookie = req.headers.get("X-Fwd-Cookie");
  const fwdReferer = req.headers.get("X-Fwd-Referer");
  const fwdLang = req.headers.get("X-Fwd-Accept-Language");
  if (fwdCookie) upstreamHeaders["Cookie"] = fwdCookie;
  if (fwdReferer) upstreamHeaders["Referer"] = fwdReferer;
  if (fwdLang) upstreamHeaders["Accept-Language"] = fwdLang;

  let upstream: Response;
  try {
    upstream = await fetch(t.toString(), { headers: upstreamHeaders });
  } catch (e) {
    return new Response(`relay upstream error: ${e}`, { status: 502 });
  }

  const responseHeaders: Record<string, string> = {
    "Content-Type": upstream.headers.get("Content-Type") ?? "application/octet-stream",
    "Cache-Control": "no-store",
  };
  const setCookies = upstream.headers.getSetCookie();
  if (setCookies.length > 0) {
    responseHeaders["X-Upstream-Set-Cookie"] = setCookies.join("\n");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
});
