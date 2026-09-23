#!/usr/bin/env python3
"""TEMPORARY probe for the Argentina source investigation. Delete when done.

v3: pull the SIOMAA/ACARA electromobility report PDFs (mirrored by the press)
to audit the model→powertrain classifier against ACARA's own per-model tables.
"""
import subprocess
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
URLS = [
    "https://autoblog.com.ar/wp-content/uploads/2026/01/SIOMAA.-Informe-Electromovilidad.-20251.pdf",
    "https://autoblog.com.ar/wp-content/uploads/2026/06/2026.05-ACARA.-Informe-de-Mercado-4W_Instit.pdf",
]
for u in URLS:
    try:
        r = requests.get(u, timeout=120, headers={"User-Agent": UA, "Referer": "https://autoblog.com.ar/"})
    except Exception as e:  # noqa
        print("ERR", u, e)
        continue
    print("GET", u, r.status_code, len(r.content), r.headers.get("content-type"), flush=True)
    if r.ok and r.content[:4] == b"%PDF":
        open("/tmp/p.pdf", "wb").write(r.content)
        out = subprocess.run(["pdftotext", "-layout", "/tmp/p.pdf", "-"],
                             capture_output=True, text=True).stdout
        print("=" * 30, u)
        print(out)
