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

PAGES = [
    "https://naamsa.net/press-releases/",
    "https://naamsa.net/quarterly-review/",
    "https://naamsa.net/newsroom/",
]


def probe() -> None:
    print("=== PROBE: naamsa (South Africa) publications ===", flush=True)
    s = requests.Session()
    s.headers.update(UA)

    pdfs: list[str] = []
    for url in PAGES:
        try:
            r = s.get(url, timeout=60)
            print(f"\n[{url}] HTTP {r.status_code} final={r.url} len={len(r.text)}", flush=True)
            if not r.ok:
                continue
            links = re.findall(r'href="([^"]+\.pdf)"', r.text, re.I)
            uniq = sorted(set(links))
            print(f"  pdf links ({len(uniq)}):")
            for l in uniq[:30]:
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

    # Prefer one flash report + one quarterly review + one media release
    picks = []
    for kw in ("flash", "quarterly", "media"):
        for u in pdfs:
            if kw in u.lower():
                picks.append(u)
                break
    for url in picks or pdfs[:3]:
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
