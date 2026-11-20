"""TEMPORARY probe (42-adding-a-country.md Phase 0). Removed before merge.

opendata.rdw.nl has no DNS record (RDW's own nameserver answers NOERROR,
no address). Where do RDW's Socrata datasets live now? Asks Socrata's
discovery API, tries candidate hosts directly and through NL_PROXY / the
Swing relay session, and saves probe_out/netherlands_rdw_host.txt.
"""
import os
import socket
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402

lines = []
def say(*a):
    s = " ".join(str(x) for x in a); print(s); lines.append(s)

s = requests.Session(); s.headers["User-Agent"] = "LeRaffl-Gallery/1.0 (research probe)"
for cat in ("https://api.us.socrata.com/api/catalog/v1", "https://api.eu.socrata.com/api/catalog/v1"):
    for q in ({"ids": "m9d7-ebf2"}, {"ids": "8ys7-d773"}, {"domains": "opendata.rdw.nl", "limit": 3},
              {"q": "gekentekende voertuigen", "limit": 5}):
        try:
            r = s.get(cat, params=q, timeout=60)
            say("==", cat, q, "HTTP", r.status_code)
            if r.ok:
                for res in r.json().get("results", [])[:5]:
                    md = res.get("metadata", {}); rs = res.get("resource", {})
                    say("   ", rs.get("id"), "|", rs.get("name"), "| domain:", md.get("domain"),
                        "| link:", res.get("link"), "| updated:", rs.get("data_updated_at"))
        except Exception as e:
            say("ERR", cat, q, e)

for host in ("opendata.rdw.nl", "data.rdw.nl", "opendata-rdw.nl", "rdw.data.socrata.com"):
    try:
        say("DNS", host, socket.getaddrinfo(host, 443)[0][4])
    except OSError as e:
        say("DNS", host, "fails:", e)

say("NL_PROXY set:", bool(os.environ.get("NL_PROXY")), "| NL_FETCH_RELAY set:", bool(os.environ.get("NL_FETCH_RELAY")))
if os.environ.get("NL_PROXY"):
    try:
        sess = fn.make_swing_session()
        r = sess.get("https://opendata.rdw.nl/resource/m9d7-ebf2.json?$limit=1", timeout=60)
        say("via NL_PROXY: HTTP", r.status_code, r.text[:200])
    except Exception as e:
        say("via NL_PROXY: ERR", type(e).__name__, str(e)[:300])

Path("probe_out").mkdir(exist_ok=True)
Path("probe_out/netherlands_rdw_host.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
