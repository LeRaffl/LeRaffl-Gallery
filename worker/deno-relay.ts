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

// Read every Set-Cookie from an upstream response, robust across runtimes.
// Headers.getSetCookie() is the correct API but isn't present in every Deno
// Deploy runtime; when it's missing, calling it throws an uncaught TypeError
// that surfaces as an opaque "500 Internal Server Error". Fall back to a
// single combined header (imperfect for cookies whose Expires contains a
// comma, but adequate for the Swing session cookies we forward).
function readSetCookies(headers: Headers): string[] {
  const anyH = headers as unknown as { getSetCookie?: () => string[] };
  if (typeof anyH.getSetCookie === "function") {
    try {
      return anyH.getSetCookie();
    } catch {
      // fall through to the combined-header path
    }
  }
  const combined = headers.get("set-cookie");
  return combined ? [combined] : [];
}

Deno.serve(async (req: Request) => {
  // Wrap the whole handler so any unexpected throw becomes a readable message
  // instead of Deno's opaque "Internal Server Error" 500. The Python client
  // (scripts/fetch_netherlands.py fetch_table) prints the body on non-200.
  try {
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
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
    const setCookies = readSetCookies(upstream.headers);
    if (setCookies.length > 0) {
      responseHeaders["X-Upstream-Set-Cookie"] = setCookies.join("\n");
    }

    // Buffer the body rather than streaming upstream.body through. Streaming a
    // consumed/aborted body is another source of opaque 500s; a full read is
    // fine for the small HTML/JSON payloads Swing returns.
    const body = await upstream.arrayBuffer();
    return new Response(body, {
      status: upstream.status,
      headers: responseHeaders,
    });
  } catch (e) {
    const err = e as Error;
    return new Response(
      `relay handler error: ${err?.message ?? e}\n${err?.stack ?? ""}`,
      { status: 512 },
    );
  }
});
