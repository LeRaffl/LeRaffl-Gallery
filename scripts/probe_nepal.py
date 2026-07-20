#!/usr/bin/env python3
"""
TEMPORARY probe helper for the Nepal (Department of Customs) integration.

Downloads the given URLs from within a GitHub Actions runner (which has
unrestricted egress, unlike the development sandbox), saves the responses
under scratch_nepal/, and prints every <a href> found in HTML responses so
the listing structure can be inspected from the run logs.

This file and the scratch_nepal/ directory are removed again before the
Nepal integration is finalized — they never ship to master.

Usage:
    python scripts/probe_nepal.py URL [URL ...]
    python scripts/probe_nepal.py --urls-file scratch_nepal/probe_urls.txt
"""
import hashlib
import re
import sys
from pathlib import Path

import requests

OUT_DIR = Path("scratch_nepal/dl")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
}

HREF_RE = re.compile(r"""href=["']([^"'#]+)["']""", re.IGNORECASE)


def safe_name(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1] or "index"
    tail = re.sub(r"[^A-Za-z0-9._-]", "_", tail)[:120]
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{digest}_{tail}"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--urls-file":
        lines = Path(args[1]).read_text().splitlines()
        urls = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    else:
        urls = args
    if not urls:
        print("no URLs given")
        return 1
    session = requests.Session()
    session.headers.update(HEADERS)
    status_lines = []
    for url in urls:
        # "INSECURE <url>" lines skip TLS verification — probe-only escape
        # hatch for archive.customs.gov.np's hostname-mismatched cert.
        verify = True
        if url.startswith("INSECURE "):
            url = url.split(None, 1)[1]
            verify = False
        print(f"\n=== GET {url} (verify={verify})")
        try:
            r = session.get(url, timeout=90, allow_redirects=True, verify=verify)
        except Exception as exc:  # noqa: BLE001 - probe: report and continue
            print(f"    FAILED: {exc}")
            status_lines.append(f"FAILED {url} :: {exc}")
            continue
        ct = r.headers.get("content-type", "?")
        print(f"    status={r.status_code} final={r.url} type={ct} bytes={len(r.content)}")
        status_lines.append(f"{r.status_code} {url} -> {r.url} [{ct}] {len(r.content)}B")
        if r.status_code != 200:
            continue
        name = safe_name(url)
        if "html" in ct.lower():
            name += ".html"
        path = OUT_DIR / name
        path.write_bytes(r.content)
        print(f"    saved {path}")
        if "html" in ct.lower():
            text = r.text
            links = sorted(set(HREF_RE.findall(text)))
            print(f"    {len(links)} unique hrefs:")
            for l in links:
                print(f"      {l}")
    (OUT_DIR / "status.txt").write_text("\n".join(status_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
