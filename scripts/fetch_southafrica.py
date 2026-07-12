#!/usr/bin/env python3
"""
South Africa (naamsa) fetcher — currently PROBE ONLY.

Usage
-----
    python scripts/fetch_southafrica.py --probe
        Run from CI (the dev sandbox has no external network; naamsa.net is
        also proxy-blocked there). Crawls naamsa's press-release page for
        the monthly flash reports and the Quarterly Review of Business
        Conditions, downloads the newest of each and dumps their text — to
        verify where the quarterly NEV breakdown (BEV / PHEV / HEV) lives
        and whether the PDFs parse cleanly.

Plan (see docs/architecture/29-expansion-candidates.md): quarterly cadence
like Canada (middle-month rows), ICE = TOTAL − NEV with the USA single-ICE
convention, monthly totals from the flash reports.
"""
import argparse
import io
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# Probe v1 (2026-07-12): naamsa.net open from CI, 244 PDFs on the
# press-releases archive (back to 2017), flash reports parse cleanly with
# pdfplumber — but carry NO NEV split, and /quarterly-review/ 404s. Probe v2
# walks the WP sitemap for the quarterly business review's real home.
PAGES = [
    "https://naamsa.net/wp-sitemap.xml",
    "https://naamsa.net/sitemap.xml",
    "https://naamsa.net/sitemap_index.xml",
]
QUARTERLY_HINTS = ("quarterly", "business-review", "review-of-business", "nev")


def probe() -> None:
    print("=== PROBE: naamsa (South Africa) publications ===", flush=True)
    s = requests.Session()
    s.headers.update(UA)

    # 1) Walk the WP sitemaps for quarterly-review-ish page URLs
    pages: list[str] = []
    for url in PAGES:
        try:
            r = s.get(url, timeout=60)
            print(f"\n[{url}] HTTP {r.status_code} len={len(r.text)}", flush=True)
            if not r.ok:
                continue
            locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
            print(f"  {len(locs)} loc entries")
            subs = [l for l in locs if l.endswith(".xml")]
            hits = [l for l in locs if any(h in l.lower() for h in QUARTERLY_HINTS)]
            for sub in subs[:15]:
                try:
                    sr = s.get(sub, timeout=60)
                    sl = re.findall(r"<loc>([^<]+)</loc>", sr.text)
                    hits += [l for l in sl if any(h in l.lower() for h in QUARTERLY_HINTS)]
                except requests.RequestException:
                    pass
            hits = sorted(set(hits))
            print(f"  quarterly-ish URLs ({len(hits)}):")
            for h in hits[:25]:
                print(f"    {h}")
            pages += hits
            if hits:
                break
        except requests.RequestException as e:
            print(f"\n[{url}] FAILED: {e}", flush=True)

    # 2) Open the quarterly pages and collect their PDFs
    pdfs: list[str] = []
    for url in sorted(set(pages))[:6]:
        try:
            r = s.get(url, timeout=60)
            print(f"\n[{url}] HTTP {r.status_code} len={len(r.text)}", flush=True)
            if not r.ok:
                continue
            links = re.findall(r'href="([^"]+\.pdf)"', r.text, re.I)
            uniq = sorted(set(links))
            print(f"  pdf links ({len(uniq)}):")
            for l in uniq[-20:]:
                print(f"    {l}")
            for l in links:
                full = l if l.startswith("http") else "https://naamsa.net" + l
                if full not in pdfs:
                    pdfs.append(full)
        except requests.RequestException as e:
            print(f"\n[{url}] FAILED: {e}", flush=True)

    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber required: pip install pdfplumber")

    # Newest quarterly PDFs first (WP uploads sort by /YYYY/MM/ path)
    picks = sorted(pdfs, reverse=True)[:2]
    for url in picks:
        print(f"\n=== PDF: {url}", flush=True)
        try:
            r = s.get(url, timeout=90)
            print(f"  HTTP {r.status_code}, {len(r.content):,} bytes")
            if not r.ok:
                continue
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                print(f"  pages: {len(pdf.pages)}")
                for i, page in enumerate(pdf.pages[:8]):
                    text = (page.extract_text() or "").strip()
                    lines = text.splitlines()
                    # Print pages mentioning NEV/electric in full, others briefly
                    hot = any(k in text.lower() for k in
                              ("new energy", "nev", "electric", "hybrid", "battery"))
                    n = 45 if hot else 8
                    print(f"  --- page {i+1}{' [NEV]' if hot else ''} ---")
                    print("  " + "\n  ".join(lines[:n]))
        except Exception as e:
            print(f"  FAILED: {e}")

    print("\n=== PROBE DONE ===")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probe", action="store_true")
    args = ap.parse_args()
    if args.probe:
        probe()
        return
    raise SystemExit("Only --probe is implemented until the source shape is confirmed.")


if __name__ == "__main__":
    main()
