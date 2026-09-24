#!/usr/bin/env python3
"""TEMPORARY probe for Ukraine (MIA/HSC vehicle-registration open data on
data.gov.ua). Run from CI; prints dataset/resource inventory and a
value-count profile of the newest file. Removed before merge."""
import collections, csv, io, json, re, sys, zipfile
import requests

API = "https://data.gov.ua/api/3/action/"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 LeRaffl-Gallery probe"

def api(action, **params):
    r = S.get(API + action, params=params, timeout=120)
    print(f"[{action} {params}] HTTP {r.status_code}", flush=True)
    r.raise_for_status()
    return r.json()["result"]

seen = {}
for q in ["транспортні засоби реєстрація", "реєстрації транспортних засобів",
          "Відомості про транспортні засоби та їх власників", "ГСЦ МВС"]:
    try:
        res = api("package_search", q=q, rows=20)
    except Exception as e:
        print("ERR", e); continue
    for p in res["results"]:
        if p["id"] in seen: continue
        seen[p["id"]] = p
        print(f"\nPKG {p['id']} name={p['name']} org={(p.get('organization') or {}).get('title')}")
        print(f"    title={p['title']}  n_res={len(p.get('resources', []))}")

# pick the registration-operations dataset
cands = [p for p in seen.values() if re.search(r"транспортн.*власник|реєстраці", p["title"], re.I)]
for p in cands:
    print(f"\n=== RESOURCES of {p['name']} ({p['title']})")
    for r in p.get("resources", []):
        print(f"  {r.get('last_modified') or r.get('created')}  {r.get('size')}  {r.get('format')}  {r.get('name')}  {r.get('url')}")

def profile(url, limit=None):
    print(f"\n=== PROFILE {url}", flush=True)
    r = S.get(url, timeout=900)
    print("HTTP", r.status_code, "bytes", len(r.content), flush=True)
    data = r.content
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        print("zip members", z.namelist())
        data = z.read(z.namelist()[0])
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc); break
        except UnicodeDecodeError: continue
    first = text.splitlines()[0]
    delim = ";" if first.count(";") > first.count(",") else ","
    rd = csv.DictReader(io.StringIO(text), delimiter=delim)
    print("enc", enc, "delim", repr(delim), "header", rd.fieldnames)
    cnt = {k: collections.Counter() for k in ("OPER_NAME", "FUEL", "KIND", "BODY", "PURPOSE", "month")}
    newfuel = collections.Counter(); newbrand_el = collections.Counter(); newmodel = collections.Counter()
    n = 0
    up = {f.upper(): f for f in rd.fieldnames}
    g = lambda row, k: (row.get(up.get(k, k)) or "").strip()
    for row in rd:
        n += 1
        op = g(row, "OPER_NAME"); cnt["OPER_NAME"][f"{g(row,'OPER_CODE')} {op}"] += 1
        cnt["FUEL"][g(row, "FUEL")] += 1; cnt["KIND"][g(row, "KIND")] += 1
        cnt["BODY"][g(row, "BODY")] += 1; cnt["PURPOSE"][g(row, "PURPOSE")] += 1
        cnt["month"][g(row, "D_REG")[:7] or g(row, "D_REG")[-7:]] += 1
        if "НОВ" in op.upper() and g(row, "KIND") == "ЛЕГКОВИЙ":
            f = g(row, "FUEL"); newfuel[f] += 1
            if "ЕЛЕКТ" in f.upper() or "ГІБРИД" in f.upper():
                newbrand_el[(f, g(row, "BRAND"))] += 1
                newmodel[(f, g(row, "BRAND"), g(row, "MODEL"))] += 1
        if n <= 3: print("ROW", row)
        if limit and n >= limit: break
    print("rows", n)
    for k, c in cnt.items():
        print(f"\n-- {k} ({len(c)} distinct)")
        for v, m in c.most_common(80): print(f"   {m:8d}  {v}")
    print("\n-- NEW passenger by FUEL")
    for v, m in newfuel.most_common(): print(f"   {m:8d}  {v}")
    print("\n-- NEW passenger electrified by (FUEL, BRAND) top 60")
    for v, m in newbrand_el.most_common(60): print(f"   {m:8d}  {v}")
    print("\n-- NEW passenger electrified by (FUEL, BRAND, MODEL) top 80")
    for v, m in newmodel.most_common(80): print(f"   {m:8d}  {v}")

urls = []
for p in cands:
    for r in p.get("resources", []):
        if (r.get("format") or "").lower() in ("csv", "zip") or r.get("url", "").lower().endswith((".csv", ".zip")):
            urls.append((r.get("last_modified") or r.get("created") or "", r["url"], r.get("name")))
urls.sort()
print("\nCSV/ZIP resources:", len(urls))
if urls:
    profile(urls[-1][1])
