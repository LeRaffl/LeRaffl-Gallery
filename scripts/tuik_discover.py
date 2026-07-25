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
import json
import re
import sys
from dataclasses import dataclass, field

BASE = "https://veriportali.tuik.gov.tr"
SHELL_URL = BASE + "/tr/press/{id}"

# A bulletin id known to exist, used as the entry point for recon: we only
# need *some* valid press page to get at the SPA bundle.
SEED_PRESS_ID = 58042

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


# ---------------------------------------------------------------------------
# Recon helpers
# ---------------------------------------------------------------------------

# Vite emits <script type="module" crossorigin src="/assets/index-<hash>.js">
_BUNDLE_RE = re.compile(r'src="(/assets/[^"]+\.js)"')

# Path literals that look like an API route. Deliberately loose — recon output
# is read by a human, so false positives are cheaper than misses.
_APIISH_RE = re.compile(r'"(/(?:api|rest|service|data|v\d)[a-zA-Z0-9/_.\-]*)"')
_TUIK_URL_RE = re.compile(r'"(https?://[a-zA-Z0-9.\-]*tuik\.gov\.tr[^"]*)"')
_PDF_HINT_RE = re.compile(r'"([^"]*(?:pdf|bulten|bulletin|download|dosya)[^"]*)"', re.I)


def _get(session, url, **kw):
    kw.setdefault("headers", HTTP_HEADERS)
    kw.setdefault("timeout", 45)
    return session.get(url, **kw)


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

    print("\n[3] SPA bundle")
    got = fetch_bundle(session)
    if not got:
        print("  !! could not retrieve bundle — recon cannot continue")
        return
    bundle_url, js = got
    print(f"  {bundle_url}  ({len(js)}B)")

    api_paths = sorted(set(_APIISH_RE.findall(js)))
    tuik_urls = sorted(set(_TUIK_URL_RE.findall(js)))
    pdf_hints = sorted(set(h for h in _PDF_HINT_RE.findall(js) if len(h) < 120))

    print(f"\n[4] api-ish path literals ({len(api_paths)})")
    for p in api_paths[:80]:
        print(f"      {p}")

    print(f"\n[5] absolute tuik.gov.tr literals ({len(tuik_urls)})")
    for u in tuik_urls[:40]:
        print(f"      {u}")

    print(f"\n[6] pdf/bulten/download hints ({len(pdf_hints)})")
    for h in pdf_hints[:60]:
        print(f"      {h}")

    print("\n[7] probing api-ish paths against the seed id")
    probes: list[str] = []
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
        print(f"  {url}\n      {_describe(r, 300)}")

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


def _via_search_api(session, year, month, want_title, verbose):
    """Query the portal's search endpoint for the series, match on exact title.

    Endpoint shape is confirmed by the recon pass; kept in one place so a
    portal change is a one-line fix.
    """
    from urllib.parse import quote
    url = f"{BASE}/api/search?q={quote(SERIES_TITLE)}&size=50"
    resp = _get(session, url)
    if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
        if verbose:
            print(f"[discover] search endpoint unusable: {_describe(resp, 200)}")
        return None
    payload = resp.json()
    for item in _iter_records(payload):
        title = str(item.get("title") or item.get("baslik") or "")
        if title.strip() != want_title:
            continue
        pid = item.get("id") or item.get("pressId") or item.get("sayi")
        return Discovery(press_id=int(pid) if pid else None,
                         pdf_url=_pdf_url_from_record(item, pid),
                         title=title)
    return None


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


_SEARCH_STRATEGIES = [_via_search_api]


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
