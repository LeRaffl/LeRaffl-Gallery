"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Round 2: does Traficom's monthly make/model workbook (MM.xlsx) or the
first-registration workbooks carry a fuel / hybrid split, and what update
cadence does the open-data FAQ give the vehicle snapshot?
"""
import io
from pathlib import Path

import requests
import openpyxl
from pypdf import PdfReader

OUT = Path("probe_out"); OUT.mkdir(exist_ok=True)
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (research probe)"
B = "https://tieto.traficom.fi"
for url in (B + "/files/media/file/MM.xlsx",
            B + "/files/media/file/Ensirekister%C3%B6innit-ajoneuvoluokan-ja-k%C3%A4yt%C3%B6n-mukaan.xlsx",
            B + "/files/media/file/Yksitt%C3%A4inmaahantuotujen-uusien-autojen-m%C3%A4%C3%A4r%C3%A4t-kuukausittain.xlsx"):
    say("== xlsx", url)
    try:
        r = s.get(url, timeout=120); say("HTTP", r.status_code, len(r.content))
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
        for ws in wb.worksheets:
            say(f"  sheet '{ws.title}' dims={ws.max_row}x{ws.max_column}")
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= 14: break
                say("   ", [c for c in row[:16]])
            hits = set()
            for row in ws.iter_rows(values_only=True):
                for c in row:
                    if isinstance(c, str) and ("hybrid" in c.lower() or "käyttövoima" in c.lower()):
                        hits.add(c.strip()[:80])
            say("   hybrid/käyttövoima cells:", sorted(hits)[:30])
    except Exception as e:
        say("ERR", e)

for url in (B + "/files/media/file/Avoin%20Data%20Usein%20Kysytyimm%C3%A4t%20Kysymykset.pdf",):
    say("== pdf", url)
    try:
        r = s.get(url, timeout=120); say("HTTP", r.status_code, len(r.content))
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
        for ln in text.splitlines():
            if any(w in ln.lower() for w in ("päivit", "neljännes", "kuukau", "kerran", "vuodessa")):
                say("  ", ln.strip()[:200])
    except Exception as e:
        say("ERR", e)

say("== zip HEAD")
try:
    r = s.head("https://opendata.traficom.fi/Content/Ajoneuvorekisteri.zip", timeout=60, allow_redirects=True)
    say("HTTP", r.status_code, {k: r.headers.get(k) for k in ("Last-Modified", "Content-Length", "ETag")})
except Exception as e:
    say("ERR", e)

(OUT / "finland_probe2.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
