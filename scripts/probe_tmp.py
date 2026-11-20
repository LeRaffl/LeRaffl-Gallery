"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

Round 2 of the daily-Traficom question: what does the OData service at
opendata.traficom.fi/api/v1 expose, and what update cadence does the
open-data page give the vehicle dataset? probe_out/finland_daily2.txt.
"""
import re
from pathlib import Path

import requests

OUT = Path("probe_out"); OUT.mkdir(exist_ok=True)
lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

s = requests.Session(); s.headers["User-Agent"] = "Mozilla/5.0 (research probe)"
r = s.get("https://opendata.traficom.fi/api/v1/", timeout=60)
say("service doc:", r.text[:2000])
m = s.get("https://opendata.traficom.fi/api/v1/$metadata", timeout=60)
say("$metadata HTTP", m.status_code, len(m.text))
for es in re.findall(r'<EntitySet Name="([^"]+)" EntityType="([^"]+)"', m.text):
    say("  entity set:", es)
for et in re.findall(r'<EntityType Name="([^"]+)"', m.text):
    say("  entity type:", et)
try:
    for name in [n for n, _ in re.findall(r'<EntitySet Name="([^"]+)" EntityType="([^"]+)"', m.text)]:
        if re.search(r"ajoneuv|vehic|rekist|ensirek", name, re.I):
            rr = s.get(f"https://opendata.traficom.fi/api/v1/{name}", params={"$top": 2}, timeout=60)
            say(f"  sample {name}: HTTP {rr.status_code}", rr.text[:800])
except Exception as e:
    say("ERR", e)

r = s.get("https://tieto.traficom.fi/fi/avoin-data", timeout=60)
html = r.text.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026nbsp;", " ")
text = re.sub(r"<[^>]+>", " ", html); text = re.sub(r"\s+", " ", text)
for m2 in re.finditer(r"Ajoneuvojen avoin data -aineisto sisältää.{0,900}", text):
    say("vehicle section:", m2.group(0))
    break
(OUT / "finland_daily2.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
