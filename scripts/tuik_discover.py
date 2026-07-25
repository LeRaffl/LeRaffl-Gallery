#!/usr/bin/env python3
"""
Discover the TÜİK "Motorlu Kara Taşıtları" bulletin id + PDF URL for a month.

Why this exists
---------------
`fetch_turkey.py` used to hard-require a `--press-id` because the Veri Portalı
(https://veriportali.tuik.gov.tr) is a React SPA: `GET /tr/press/<id>` returns
a 3.4 KB `<div id="root"></div>` shell (two captured samples live in
data/58041.html and data/58042.html — byte-identical apart from the NetScaler
telemetry ids), and the bulletin content is hydrated client-side from an
undocumented JSON API. That meant the daily cron was a no-op and a human had
to dispatch the workflow with the id once a month. In practice nobody did:
between 2026-05 and 2026-07 the gallery silently sat on Nisan 2026 data.

Two separate unknowns have to be solved to remove the manual step:

  1. (year, month) → bulletin id.  The ids are NOT chronological — observed:
     58041=Mart 2026, 58042=Nisan 2026, 58043=Haziran 2026, 58044=Mayıs 2026,
     58051=Ocak 2026. So "last id + 1" is actively wrong and would silently
     fetch the wrong month. (`fetch_turkey.py`'s narrative month-check would
     catch it and refuse to write, but only after a full OCR round-trip.)
  2. bulletin id → PDF URL.  The `/tr/press/<id>` page is not the PDF.

Recon mode
----------
Because the sandbox this was developed in cannot reach *.tuik.gov.tr (egress
policy), `--debug` runs a self-contained reconnaissance pass whose output is
read back out of the GitHub Actions log:

    python scripts/tuik_discover.py --debug --year 2026 --month 6

It parses the SPA shell for the hashed Vite bundle, pulls every API-ish path
and tuik.gov.tr URL literal out of that bundle, then probes the candidates and
prints status + content-type + a body prefix for each. Nothing is written and
a failure exits 0 — it is a diagnostic, not a fetch step.

Public API
----------
    discover(year, month, session=None, verbose=False) -> Discovery | None

`Discovery.pdf_url` is what `fetch_turkey.py` feeds to `load_pdf_bytes()`;
`Discovery.press_id` is recorded in the CSV `source` column. Callers must
still run the existing narrative month-check — discovery is best-effort and
is never allowed to be the only thing standing between a wrong bulletin and
a written row.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from itertools import zip_longest
from pathlib import Path
from dataclasses import dataclass, field

BASE = "https://veriportali.tuik.gov.tr"
SHELL_URL = BASE + "/tr/press/{id}"

# The bulletin JSON endpoint, confirmed from a browser DevTools capture:
#   GET /api/tr/press/58043  ->  Accept: application/json
# No Authorization header is involved; the request carries only cookies the
# site itself sets (Google Analytics plus a NetScaler/WAF pair). We therefore
# never hard-code a captured cookie — warm_session() fetches the press page
# first so the same cookies are issued to us, exactly as a browser gets them.
PRESS_API = BASE + "/api/{lang}/press/{id}"

# A bulletin id known to exist, used as the entry point for recon: we only
# need *some* valid press page to get at the SPA bundle.
SEED_PRESS_ID = 58042

# How far either side of the anchor id the scan looks before giving up.
SCAN_AHEAD = 14
SCAN_BEHIND = 6

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
}

MONTHS_TR = {
    "Ocak": 1, "Şubat": 2, "Mart": 3, "Nisan": 4, "Mayıs": 5, "Haziran": 6,
    "Temmuz": 7, "Ağustos": 8, "Eylül": 9, "Ekim": 10, "Kasım": 11, "Aralık": 12,
}
MONTHS_TR_BY_NUM = {v: k for k, v in MONTHS_TR.items()}

# The bulletin series we care about. TÜİK titles it exactly
# "Motorlu Kara Taşıtları, <Month> <Year>".
SERIES_TITLE = "Motorlu Kara Taşıtları"


@dataclass
class Discovery:
    press_id: int | None
    pdf_url: str | None
    title: str = ""
    notes: list[str] = field(default_factory=list)
    # The bulletin record straight from the API. `record["content"]` is the
    # full bulletin HTML, which is what the caller parses instead of OCRing
    # the PDF — see fetch_turkey.parse_content_html().
    record: dict | None = None


# ---------------------------------------------------------------------------
# Recon helpers
# ---------------------------------------------------------------------------

# Vite emits <script type="module" crossorigin src="/assets/index-<hash>.js">
_BUNDLE_RE = re.compile(r'src="(/assets/[^"]+\.js)"')

# Round 1 of recon found the entry chunk is only ~31 KB and contains zero API
# literals: it is a Vite loader, and the real code sits in lazily-imported
# chunks it references by hash. So the crawl has to follow the module graph
# rather than grep the entry chunk alone.
_ASSET_REF_RE = re.compile(r'["\'(]([./]*assets/[A-Za-z0-9_.\-]+\.js)["\')]')

# Path literals that look like an API route. Deliberately loose — recon output
# is read by a human, so false positives are cheaper than misses.
_APIISH_RE = re.compile(r'"(/(?:api|rest|service|data|v\d)[a-zA-Z0-9/_.\-]*)"')
_ABS_URL_RE = re.compile(r'"(https?://[a-zA-Z0-9.\-]+\.[a-z]{2,}[^"\s]{0,120})"')
_PDF_HINT_RE = re.compile(r'"([^"]*(?:pdf|bulten|bulletin|download|dosya)[^"]*)"', re.I)

# Fixed candidates worth a shot regardless of what the bundle says.
#
# The legacy portal data.tuik.gov.tr is the interesting one: it is server-
# rendered (no SPA), it is what data/Türkiye.csv cited as `source` for every
# row up to 2026-03, and Google has it indexed with per-bulletin slugs of the
# form /Bulten/Index?p=Motorlu-Kara-Tasitlari-<Month>-<Year>-<id>. If it still
# carries 2026 bulletins, discovery becomes plain HTML scraping and the whole
# SPA problem goes away.
# Round 2 ruled out the legacy portal entirely: data.tuik.gov.tr now serves the
# same 1947-byte SPA shell for both a search URL and a known-good 2025 bulletin,
# so it has been folded into the SPA and is no longer scrapeable HTML.
#
# It did however pin down the API's shape. /api/* answers with a genuine
# plaintext "Sayfa bulunamadı" 404 while /tr/* returns the SPA shell, i.e.
# /api/* is a separate backend that knows its own routes — a 404 there means
# "no such route", not "no API". Two real path literals came out of the lazily
# loaded chunks, /api/tr/captcha/challenges and /api/tr/infographics, giving
# the pattern /api/{lang}/{resource}. Round 2 probed /tr/api/press/<id> and
# /api/press/<id> — both wrong against that pattern. /api/tr/press/<id> is the
# obvious untried candidate, and /tr/press/<id>/metadata is a route the public
# site is known to expose.
# /api/tr/press/<id> is confirmed and handled separately (see press_json).
# What is still missing is the reverse direction: month -> id. These are the
# listing/search shapes worth trying for that; whichever answers with JSON
# becomes the basis of discovery.
FIXED_PROBES = [
    BASE + "/api/tr/press?page=1&size=20",
    BASE + "/api/tr/press/list?page=1&size=20",
    BASE + "/api/tr/presses?page=1&size=20",
    BASE + "/api/tr/search?q=Motorlu%20Kara%20Ta%C5%9F%C4%B1tlar%C4%B1",
    BASE + f"/api/tr/press/{SEED_PRESS_ID}/metadata",
    BASE + "/api/tr/categories",
    BASE + "/api/tr/themes",
]

# Printed in full rather than truncated: the round-2 probe showed robots.txt
# naming AI crawler user-agents (anthropic-ai, ClaudeBot, GPTBot, …) but the
# 300-char preview cut off before the Allow/Disallow that applies to them.
# Whether this pipeline's browser-UA fetches are in scope is a call the
# maintainer should make against the actual text, so show the actual text.
FULL_PRINT = {BASE + "/robots.txt"}


def _get(session, url, **kw):
    kw.setdefault("headers", HTTP_HEADERS)
    kw.setdefault("timeout", 45)
    return session.get(url, **kw)


def warm_session(session, press_id: int = SEED_PRESS_ID):
    """Fetch the press page so the WAF/analytics cookies get issued to us.

    The captured browser request carried NSC_ESNS (NetScaler) and a long hex
    cookie alongside the GA ids. Rather than embedding someone's captured
    session, do what the browser does: request the HTML page first and let the
    cookie jar fill itself, then call the API from the same session.
    """
    try:
        _get(session, SHELL_URL.format(id=press_id))
    except Exception as e:
        print(f"[warm] shell fetch failed ({e}) — continuing without cookies")
    return session


def press_json(session, press_id: int, lang: str = "tr"):
    """GET /api/<lang>/press/<id>, returning parsed JSON or None."""
    url = PRESS_API.format(lang=lang, id=press_id)
    r = _get(session, url, headers={
        **HTTP_HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": SHELL_URL.format(id=press_id),
    })
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        return None
    try:
        return r.json()
    except ValueError:
        return None


def _describe(resp, limit: int = 400) -> str:
    ct = resp.headers.get("content-type", "?")
    body = resp.content[:limit]
    try:
        shown = body.decode("utf-8", "replace")
    except Exception:  # pragma: no cover - defensive
        shown = repr(body)
    shown = shown.replace("\n", " ")
    return f"HTTP {resp.status_code}  {ct}  {len(resp.content)}B\n      {shown}"


def fetch_bundle(session, press_id: int = SEED_PRESS_ID) -> tuple[str, str] | None:
    """Return (bundle_url, bundle_js) for the SPA's main chunk, or None."""
    resp = _get(session, SHELL_URL.format(id=press_id))
    if resp.status_code != 200:
        print(f"  shell {press_id}: {_describe(resp)}")
        return None
    m = _BUNDLE_RE.search(resp.text)
    if not m:
        print("  shell parsed but no /assets/*.js <script> found")
        return None
    url = BASE + m.group(1)
    js = _get(session, url)
    if js.status_code != 200:
        print(f"  bundle: {_describe(js)}")
        return None
    return url, js.text


def recon(session, year: int, month: int) -> None:
    """Print everything a human needs to write the real discovery logic."""
    print("=" * 72)
    print(f"TÜİK Veri Portalı recon — target {MONTHS_TR_BY_NUM[month]} {year}")
    print("=" * 72)

    print("\n[1] press shell")
    resp = _get(session, SHELL_URL.format(id=SEED_PRESS_ID))
    print(f"  GET /tr/press/{SEED_PRESS_ID}\n      {_describe(resp)}")

    print("\n[2] same URL with Accept: application/pdf")
    r2 = _get(session, SHELL_URL.format(id=SEED_PRESS_ID),
              headers={**HTTP_HEADERS, "Accept": "application/pdf"})
    print(f"      {_describe(r2)}")

    print("\n[2b] confirmed bulletin endpoint /api/tr/press/<id>")
    warm_session(session)
    for pid in (58043, SEED_PRESS_ID):
        data = press_json(session, pid)
        if data is None:
            print(f"  id={pid}: no JSON (endpoint or cookies wrong)")
            continue
        rec = data.get("data") if isinstance(data, dict) else None
        if not isinstance(rec, dict):
            print(f"  id={pid}: unexpected envelope {sorted(data)[:6]}")
            continue
        print(f"  id={pid}  title={rec.get('title')!r}  period={rec.get('period')!r}"
              f"  date={rec.get('date')!r}  fields={sorted(rec)}")

        # The decisive question: the PDF hides the fuel table in a raster image
        # (hence the whole pdfimages+tesseract pipeline). If the API's HTML
        # `content` carries it as real markup instead, OCR can go away entirely.
        html = str(rec.get("content") or "")
        stripped = re.sub(r'src="data:image/[^"]*"', 'src="[b64]"', html)
        print(f"  content: {len(html)}B raw, {len(stripped)}B without base64")
        for label in ("Benzin", "Hibrit", "Elektrik", "Dizel", "LPG"):
            i = stripped.find(label)
            print(f"    {label:9s} {'at %d' % i if i >= 0 else 'NOT FOUND'}")
        i = stripped.find("Benzin")
        if i >= 0:
            print(f"  --- markup around 'Benzin' ---\n{stripped[max(0, i - 1200):i + 1800]}")

    print("\n[3] SPA module graph")
    got = fetch_bundle(session)
    if not got:
        print("  !! could not retrieve entry chunk — recon cannot continue")
        return
    bundle_url, entry_js = got
    print(f"  entry {bundle_url}  ({len(entry_js)}B)")

    # Breadth-first over the chunk graph. Two levels past the entry has been
    # enough for every Vite build seen so far; the cap keeps a pathological
    # graph from turning recon into a crawl of the whole site.
    seen: dict[str, str] = {bundle_url: entry_js}
    frontier = [bundle_url]
    for depth in (1, 2):
        nxt = []
        for src in frontier:
            for ref in set(_ASSET_REF_RE.findall(seen[src])):
                url = BASE + "/" + ref.lstrip("./")
                if url in seen or len(seen) >= 40:
                    continue
                try:
                    r = _get(session, url)
                except Exception as e:
                    print(f"  L{depth} {url} !! {e}")
                    continue
                if r.status_code == 200:
                    seen[url] = r.text
                    nxt.append(url)
        print(f"  level {depth}: +{len(nxt)} chunks (total {len(seen)})")
        frontier = nxt

    js = "\n".join(seen.values())
    print(f"  crawled {len(seen)} chunks, {len(js)}B total")

    api_paths = sorted(set(_APIISH_RE.findall(js)))
    abs_urls = sorted(set(u for u in _ABS_URL_RE.findall(js)
                          if "w3.org" not in u and "schema.org" not in u))
    pdf_hints = sorted(set(h for h in _PDF_HINT_RE.findall(js) if len(h) < 120))

    print(f"\n[4] api-ish path literals ({len(api_paths)})")
    for p in api_paths[:80]:
        print(f"      {p}")

    print(f"\n[5] absolute URL literals ({len(abs_urls)})")
    for u in abs_urls[:60]:
        print(f"      {u}")

    print(f"\n[6] pdf/bulten/download hints ({len(pdf_hints)})")
    for h in pdf_hints[:60]:
        print(f"      {h}")

    print("\n[7] probing fixed candidates + discovered paths")
    probes: list[str] = list(FIXED_PROBES) + [BASE + "/robots.txt"]
    for p in api_paths[:40]:
        if "{" in p or "$" in p:
            continue
        probes.append(BASE + p)
        if p.rstrip("/").endswith(("press", "haberbulteni", "bulten")):
            probes.append(f"{BASE}{p.rstrip('/')}/{SEED_PRESS_ID}")
    for url in dict.fromkeys(probes):
        try:
            r = _get(session, url)
        except Exception as e:
            print(f"  {url}\n      !! {e}")
            continue
        limit = 4000 if url in FULL_PRINT else 300
        print(f"  {url}\n      {_describe(r, limit)}")

    print("\n" + "=" * 72)
    print("recon done — feed the interesting endpoints into discover()")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover(year: int, month: int, session=None, verbose: bool = False) -> Discovery | None:
    """Best-effort (year, month) → bulletin id + PDF URL.

    Returns None when the portal shape is not understood, which the caller
    must treat as "fall back to a manually supplied --press-id", never as
    "there is no bulletin".
    """
    if session is None:
        import requests
        session = requests.Session()

    want_title = f"{SERIES_TITLE}, {MONTHS_TR_BY_NUM[month]} {year}"
    if verbose:
        print(f"[discover] looking for: {want_title}")

    for attempt in _SEARCH_STRATEGIES:
        try:
            hit = attempt(session, year, month, want_title, verbose)
        except Exception as e:
            if verbose:
                print(f"[discover] {attempt.__name__} raised: {e}")
            continue
        if hit:
            if verbose:
                print(f"[discover] {attempt.__name__} → id={hit.press_id} pdf={hit.pdf_url}")
            return hit
    if verbose:
        print("[discover] no strategy matched")
    return None


def _via_id_scan(session, year, month, want_title, verbose):
    """Scan a bounded window of bulletin ids and match on title + period.

    Every listing/search shape probed (/api/tr/press, .../list, /presses,
    /search, /categories, /themes) answers 404, so there is no index to query —
    but /api/tr/press/<id> returns `title` ("Motorlu Kara Taşıtları") and
    `period` ("Haziran 2026") for any id, which is enough to identify a
    bulletin exactly.

    The scan is cheap because the series occupies a contiguous id block, just
    not in date order within it: 58041=Mart, 58042=Nisan, 58043=Haziran,
    58044=Mayıs, 58051=Ocak 2026 are all this same series. So anchoring on the
    id already recorded in the CSV and walking outward finds the target in a
    handful of requests. Match is on BOTH fields — period alone repeats across
    series, title alone repeats across months.
    """
    want_period = f"{MONTHS_TR_BY_NUM[month]} {year}"
    anchor = _anchor_id(session)
    if anchor is None:
        if verbose:
            print("[discover] no anchor id available, cannot scan")
        return None

    # Outward from the anchor, nearest first: the next bulletin is usually
    # within a couple of ids, and stopping early keeps the daily cron light
    # (each record is ~340 KB because `content` embeds base64 chart images).
    # zip() would silently truncate to the shorter side (SCAN_BEHIND), so
    # interleave with zip_longest and drop the padding instead.
    offsets = [d for pair in zip_longest(range(1, SCAN_AHEAD + 1),
                                         range(-1, -SCAN_BEHIND - 1, -1))
               for d in pair if d is not None]
    for off in offsets:
        pid = anchor + off
        rec = press_json(session, pid)
        if not rec:
            continue
        data = rec.get("data") if isinstance(rec, dict) else None
        if not isinstance(data, dict):
            continue
        title, period = str(data.get("title", "")), str(data.get("period", ""))
        if verbose:
            print(f"[discover]   id={pid}: {title!r} / {period!r}")
        if title.strip() == SERIES_TITLE and period.strip() == want_period:
            return Discovery(press_id=pid, pdf_url=None, title=want_title,
                             notes=[f"matched by scan at offset {off:+d}"],
                             record=data)
    return None


def _anchor_id(session=None) -> int | None:
    """Newest bulletin id already recorded in data/Türkiye.csv.

    The CSV's `source` column carries the press URL of the row it came from
    (…/tr/press/58042), so the scan re-anchors itself every month without any
    hard-coded id drifting out of date.
    """
    path = Path("data/Türkiye.csv")
    if not path.exists():
        return None
    best = None
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            for field in (row.get("notes") or "", row.get("source") or ""):
                m = re.search(r"/press/(\d+)", field)
                if m:
                    pid = int(m.group(1))
                    best = pid if best is None else max(best, pid)
    return best


def _iter_records(payload):
    """Yield dict records from whatever envelope the API uses."""
    if isinstance(payload, list):
        for x in payload:
            if isinstance(x, dict):
                yield x
        return
    if not isinstance(payload, dict):
        return
    for key in ("data", "items", "results", "content", "hits", "list"):
        inner = payload.get(key)
        if isinstance(inner, list):
            for x in inner:
                if isinstance(x, dict):
                    yield x
            return
        if isinstance(inner, dict):
            yield from _iter_records(inner)
            return
    yield payload


def _pdf_url_from_record(item, pid):
    for key in ("pdfUrl", "pdf", "fileUrl", "dosyaUrl", "documentUrl", "url"):
        v = item.get(key)
        if isinstance(v, str) and v:
            return v if v.startswith("http") else BASE + v
    return None


_SEARCH_STRATEGIES = [_via_id_scan]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--month", type=int, required=True, choices=range(1, 13))
    ap.add_argument("--debug", action="store_true",
                    help="run the reconnaissance pass and print findings")
    args = ap.parse_args()

    import requests
    session = requests.Session()

    if args.debug:
        recon(session, args.year, args.month)
        return 0

    hit = discover(args.year, args.month, session=session, verbose=True)
    if not hit:
        print("no bulletin discovered")
        return 0
    print(json.dumps({"press_id": hit.press_id, "pdf_url": hit.pdf_url,
                      "title": hit.title}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
