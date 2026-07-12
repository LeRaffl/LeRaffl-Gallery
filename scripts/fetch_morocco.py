#!/usr/bin/env python3
"""
Morocco (AIVAM) fetcher — currently PROBE ONLY.

Usage
-----
    python scripts/fetch_morocco.py --probe
        Run from CI (the dev sandbox has no external network). Crawls
        AIVAM's publication pages, lists downloadable PDFs, downloads the
        most recent one(s) and dumps their text — to answer the open
        question from docs/architecture/29-expansion-candidates.md: does
        AIVAM's own monthly PDF carry the per-energy split (BEV / PHEV /
        HEV / MHEV / petrol / diesel) that the Moroccan press quotes, or
        does that table only exist in press relays?

AIVAM (Association des Importateurs de Véhicules au Maroc) is the importers'
association; Morocco's formal new-vehicle market flows through its members,
including the Chinese brands, so completeness is expected to be OK.
"""
import argparse
import io
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"}

PAGES = [
    "https://www.aivam.ma/fr/documentation-et-etudes",
    "https://www.aivam.ma/fr/statistiques",
    "https://www.aivam.ma/",
    "https://aivam.ma/",
]


def probe() -> None:
    print("=== PROBE: AIVAM (Morocco) publications ===", flush=True)
    s = requests.Session()
    s.headers.update(UA)

    pdf_links: list[str] = []
    for url in PAGES:
        try:
            r = s.get(url, timeout=60)
            print(f"\n[{url}] HTTP {r.status_code} final={r.url} len={len(r.text)}", flush=True)
            if not r.ok:
                continue
            links = re.findall(r'href="([^"]+)"', r.text)
            pdfs = [l for l in links if ".pdf" in l.lower()]
            others = [l for l in links if any(k in l.lower() for k in ("statist", "document", "etude", "marche", "vente"))
                      and ".pdf" not in l.lower()]
            print(f"  pdf links ({len(pdfs)}):")
            for l in pdfs[:25]:
                print(f"    {l}")
            print(f"  stats-ish page links ({len(others)}):")
            for l in sorted(set(others))[:15]:
                print(f"    {l}")
            for l in pdfs:
                full = l if l.startswith("http") else ("https://www.aivam.ma" + (l if l.startswith("/") else "/" + l))
                if full not in pdf_links:
                    pdf_links.append(full)
        except requests.RequestException as e:
            print(f"\n[{url}] FAILED: {e}", flush=True)

    if not pdf_links:
        print("\nNo PDFs found on the crawled pages.")
        return

    try:
        import pdfplumber
    except ImportError:
        raise SystemExit("pdfplumber required for the probe: pip install pdfplumber")

    # Dump the first few PDFs (most sites list newest first)
    for url in pdf_links[:3]:
        print(f"\n=== PDF: {url}", flush=True)
        try:
            r = s.get(url, timeout=90)
            print(f"  HTTP {r.status_code}, {len(r.content):,} bytes")
            if not r.ok:
                continue
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                print(f"  pages: {len(pdf.pages)}")
                for i, page in enumerate(pdf.pages[:6]):
                    text = (page.extract_text() or "").strip()
                    print(f"  --- page {i+1} ---")
                    print("  " + "\n  ".join(text.splitlines()[:40]))
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
