"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Is there a monthly Traficom source that splits non-plug-in hybrids?
Lists every trafi2.stat.fi TraFi table with its driving-power values, the
links on Traficom's first-registration power-source statistics pages, and the
open-data snapshot's metadata. Writes probe_out/finland_probe.txt.
"""
import json
import re
import sys
from pathlib import Path

import requests

OUT = Path("probe_out"); OUT.mkdir(exist_ok=True)
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

s = requests.Session()
s.headers["User-Agent"] = "Mozilla/5.0 (research probe)"

def walk(base, path="", depth=0):
    url = base + path
    try:
        r = s.get(url, timeout=60)
    except Exception as e:
        say("ERR", url, e); return
    if not r.ok:
        say("HTTP", r.status_code, url); return
    for t in r.json():
        if t.get("type") == "l":
            say("  " * depth + f"[folder] {t.get('text')} ({t['id']})")
            walk(base, f"{path}/{t['id']}", depth + 1)
        else:
            turl = f"{url}/{t['id']}"
            say("  " * depth + f"[table] {t.get('text')} ({turl}) updated={t.get('updated')}")
            try:
                meta = s.get(turl, timeout=60).json()
            except Exception as e:
                say("  " * depth + f"   meta ERR {e}"); continue
            for v in meta.get("variables", []):
                vals = v.get("valueTexts", [])
                key = (v.get("text") or "").lower()
                if "voima" in key or "polttoaine" in key or "hybrid" in key or len(vals) <= 6:
                    say("  " * depth + f"   var {v.get('code')} '{v.get('text')}': "
                        + " | ".join(f"{c}={x}" for c, x in zip(v.get("values", []), vals)))
                else:
                    say("  " * depth + f"   var {v.get('code')} '{v.get('text')}': {len(vals)} values, first {vals[:3]} last {vals[-2:]}")

say("== trafi2.stat.fi TraFi database")
walk("https://trafi2.stat.fi/PXWeb/api/v1/fi/TraFi")

for page in ("https://tieto.traficom.fi/fi/tilastot/ensirekisteroityjen-ajoneuvojen-kayttovoimatilastot",
             "https://tieto.traficom.fi/fi/tilastot/ensirekisteroityjen-ajoneuvojen-tilastot",
             "https://tieto.traficom.fi/en/statistics/statistics-power-sources-road-vehicles-registered-first-time",
             "https://tieto.traficom.fi/fi/datatraficom/avoin-data",
             "https://tieto.traficom.fi/en/datatraficom/open-data"):
    say("== page", page)
    try:
        r = s.get(page, timeout=60)
        say("HTTP", r.status_code, len(r.text))
        for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            text = re.sub(r"<[^>]+>", " ", text); text = " ".join(text.split())
            if re.search(r"\.(xlsx?|csv|zip|pdf)|sites/default/files|avoin|opendata|hybrid", href + text, re.I):
                say("  link:", text[:120], "->", href)
        for m in re.finditer(r"(päivitet\w+[^<]{0,160}|updated[^<]{0,160}|Aineiston päivämäärä[^<]{0,80}|Julkaisupäivä[^<]{0,80})", r.text, re.I):
            say("  text:", " ".join(m.group(1).split())[:200])
    except Exception as e:
        say("ERR", e)

say("== avoindata.fi dataset metadata")
try:
    r = s.get("https://www.avoindata.fi/data/api/3/action/package_show?id=ajoneuvojen-avoin-data", timeout=60)
    d = r.json()["result"]
    say("frequency/extras:", json.dumps({k: d.get(k) for k in ("update_frequency", "metadata_modified")}, ensure_ascii=False))
    for e in d.get("extras", []):
        say("  extra", e)
    for res in d.get("resources", []):
        say("  resource", res.get("name"), res.get("url"), res.get("last_modified") or res.get("created"), res.get("size"))
except Exception as e:
    say("ERR", e)

(OUT / "finland_probe.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
