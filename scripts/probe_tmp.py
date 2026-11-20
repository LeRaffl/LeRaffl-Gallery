"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Is there a DAILY (or monthly) Traficom vehicle source with the hybrid
class, the way Spain has DGT's daily microdata? Reads the open-data FAQ,
the opendata.traficom.fi API description, the avoindata.fi catalogue and
Traficom's open-data page. Writes probe_out/finland_daily.txt.
"""
import io
import re
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path("probe_out"); OUT.mkdir(exist_ok=True)
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (research probe)"

say("== FAQ (full text)")
try:
    r = s.get("https://tieto.traficom.fi/files/media/file/Avoin%20Data%20Usein%20Kysytyimm%C3%A4t%20Kysymykset.pdf", timeout=120)
    say("\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages))
except Exception as e:
    say("ERR", e)

say("\n== opendata.traficom.fi API description")
for url in ("https://opendata.traficom.fi/swagger/docs/v1", "https://opendata.traficom.fi/swagger/v1/swagger.json",
            "https://opendata.traficom.fi/api/v1/", "https://opendata.traficom.fi/Content/"):
    try:
        r = s.get(url, timeout=60)
        say(url, "HTTP", r.status_code, r.headers.get("Content-Type"), len(r.content))
        if r.ok and "json" in (r.headers.get("Content-Type") or ""):
            d = r.json()
            for path, ops in (d.get("paths") or {}).items():
                summ = "; ".join((op.get("summary") or op.get("description") or "")[:100]
                                 for op in ops.values() if isinstance(op, dict))
                say("  ", path, "-", summ)
        elif r.ok:
            say("  ", re.sub(r"\s+", " ", r.text[:600]))
    except Exception as e:
        say("ERR", url, e)

say("\n== avoindata.fi catalogue (Traficom vehicle datasets)")
for q in ("ajoneuvo traficom", "ensirekisteröinnit", "ajoneuvojen avoin data"):
    for base in ("https://www.avoindata.fi/data/api/3/action/package_search",
                 "https://avoindata.suomi.fi/data/api/3/action/package_search"):
        try:
            r = s.get(base, params={"q": q, "rows": 10}, timeout=60)
            say(base, q, "HTTP", r.status_code)
            if r.ok:
                for pkg in r.json()["result"]["results"]:
                    extras = {e["key"]: e["value"] for e in pkg.get("extras", [])}
                    say("  ", pkg.get("name"), "|", (pkg.get("organization") or {}).get("name"),
                        "| freq:", pkg.get("update_frequency") or extras.get("update_frequency"),
                        "| modified:", pkg.get("metadata_modified"))
                    for res in pkg.get("resources", [])[:6]:
                        say("      res:", res.get("name"), res.get("url"), res.get("last_modified"))
                break
        except Exception as e:
            say("ERR", base, q, e)

say("\n== tieto.traficom.fi open-data page: vehicle section")
try:
    r = s.get("https://tieto.traficom.fi/fi/avoin-data", timeout=60)
    text = re.sub(r"<[^>]+>", " ", r.text); text = re.sub(r"\s+", " ", text)
    for m in re.finditer(r"(.{0,300}(ajoneuv|Ajoneuv).{0,500})", text):
        say("  ...", m.group(1))
except Exception as e:
    say("ERR", e)

(OUT / "finland_daily.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
