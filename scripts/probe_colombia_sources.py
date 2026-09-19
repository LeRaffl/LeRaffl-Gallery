#!/usr/bin/env python3
"""TEMPORARY probe: where did the monthly Colombia boletín go?

ANDI replaced the monthly list on the Cámara Automotriz page with a year-end
archive some time between 2026-09-02 and 2026-09-05, so discovery stalls at
the Dec-2025 file. This walks a handful of candidate listing pages and reports
which of them still link an "INFORME … SECTOR … AUTOMOTOR" PDF, and whether
any of those name 2026.

Run from CI (andi.com.co is not reachable from every dev sandbox):
    python scripts/probe_colombia_sources.py
"""
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_colombia import HREF_PDF_RE, _basename, classify_pdf_name  # noqa: E402

SEEDS = [
    "https://www.andi.com.co/Home/Camara/4-automotriz",
    "https://www.andi.com.co/Home/Publicaciones",
    "https://www.andi.com.co/Home/Noticias",
    "https://fenalco.com.co/",
    "https://fenalco.com.co/blog/gremial-4",
    "https://fenalco.com.co/informes",
]

# Every shape ANDI has used for a monthly file, with the ticks suffix dropped —
# some uploads carry one, some do not, so an unticked guess is worth a HEAD.
GUESS_TEMPLATES = [
    "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO2026_PRENSA.pdf",
    "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGOSTO2026_PRENSA.pdf",
    "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGOSTO%202026_PRENSA.pdf",
    "https://www.andi.com.co/Uploads/08.%20INFORME%20SECTOR%20AUTOMOTOR%20AGO_PRENSA-INDUSTRIA%202026.pdf",
    # the known-good Jul-2026 URL — proves whether unlinked /Uploads/ files survive
    "https://www.andi.com.co/Uploads/07.%20INFORME%20SECTOR%20AUTOMOTOR%20JUL2026_PRENSA_639237910436235821.pdf",
]

AUTOMOTOR_LINK_RE = re.compile(r'<a[^>]+href\s*=\s*["\']([^"\']+)["\'][^>]*>(.{0,120}?)</a>',
                               re.IGNORECASE | re.DOTALL)


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    s.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, connect=3, read=2, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET", "HEAD"])))
    return s


def probe_page(s: requests.Session, url: str) -> None:
    print(f"\n=== {url}")
    try:
        r = s.get(url, timeout=30)
    except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
        print(f"  ERROR {type(exc).__name__}: {exc}")
        return
    print(f"  HTTP {r.status_code}, {len(r.text)} chars, final url {r.url}")
    if r.status_code != 200:
        return

    bulletins = []
    for m in HREF_PDF_RE.finditer(r.text):
        href = m.group(1)
        info = classify_pdf_name(_basename(href))
        if info:
            bulletins.append((info, urljoin(url, href)))
    print(f"  bulletin PDFs: {len(bulletins)}")
    for (year, month, monthly), link in sorted(bulletins, reverse=True)[:12]:
        print(f"    {year}-{month:02d} {'monthly' if monthly else 'annual '} {_basename(link)}")

    # Anything at all whose link text or URL says "automotor" — the monthlies
    # may now sit behind a landing page rather than a direct PDF link.
    seen = set()
    for m in AUTOMOTOR_LINK_RE.finditer(r.text):
        href, label = m.group(1), " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())
        blob = f"{unquote(href)} {label}".upper()
        if "AUTOMOTOR" not in blob and "BOLET" not in blob:
            continue
        key = (href, label)
        if key in seen:
            continue
        seen.add(key)
        print(f"    link {urljoin(url, href)}  «{label}»")


def probe_guess(s: requests.Session, url: str) -> None:
    try:
        r = s.head(url, timeout=30, allow_redirects=True)
        note = ""
        if r.status_code == 405:  # some hosts refuse HEAD
            r = s.get(url, timeout=30, stream=True)
            note = " (via GET)"
        ctype = r.headers.get("Content-Type", "?")
        clen = r.headers.get("Content-Length", "?")
        print(f"  HTTP {r.status_code}{note} {ctype} {clen}B  {_basename(url)}")
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR {type(exc).__name__}: {exc}  {_basename(url)}")


def main() -> None:
    s = session()
    for url in SEEDS:
        probe_page(s, url)
    print("\n=== constructed /Uploads/ guesses")
    for url in GUESS_TEMPLATES:
        probe_guess(s, url)


if __name__ == "__main__":
    main()
