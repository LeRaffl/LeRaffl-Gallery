#!/usr/bin/env python3
"""TEMPORARY probe v2 for Ukraine (MIA/HSC registrations on data.gov.ua).
Streams the 2025 + 2026 yearly zips and profiles operations / fuel / kind,
new-passenger-car monthly counts by fuel, and electrified brands/models.
Removed before merge."""
import collections, csv, io, re, zipfile
import requests

PKG = "https://data.gov.ua/api/3/action/package_show?id=0ffd8b75-0628-48cc-952a-9302f9799ec0"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 LeRaffl-Gallery probe"
res = S.get(PKG, timeout=120).json()["result"]["resources"]
urls = {}
for r in res:
    m = re.search(r"(20\d\d)", r.get("name", ""))
    if m:
        urls.setdefault(m.group(1), []).append((r.get("last_modified") or r.get("created"), r["url"]))

def stream(url):
    r = S.get(url, timeout=1800); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    print("zip", url.rsplit("/",1)[-1], [(i.filename, i.file_size) for i in z.infolist()], flush=True)
    for name in z.namelist():
        raw = z.open(name).read()
        for enc in ("utf-8-sig", "cp1251"):
            try: text = raw.decode(enc); break
            except UnicodeDecodeError: pass
        first = text[:2000].splitlines()[0]
        delim = ";" if first.count(";") > first.count(",") else ","
        print("member", name, "enc", enc, "delim", repr(delim), "header", first, flush=True)
        yield from csv.DictReader(io.StringIO(text), delimiter=delim)

for year in ("2025", "2026"):
    url = sorted(urls[year])[-1][1]
    ops = collections.Counter(); kinds = collections.Counter(); fuels = collections.Counter()
    newops = collections.Counter(); months = collections.Counter()
    nf = collections.defaultdict(collections.Counter)  # month -> fuel (new, ЛЕГКОВИЙ)
    body = collections.Counter(); purpose = collections.Counter(); person = collections.Counter()
    elb = collections.Counter(); elm = collections.Counter(); hyb = collections.Counter()
    n = 0
    for row in stream(url):
        n += 1
        R = {k.strip().upper(): (v or "").strip() for k, v in row.items() if k}
        if n <= 3: print("ROW", R)
        op = f"{R.get('OPER_CODE')} {R.get('OPER_NAME')}"
        ops[op] += 1; kinds[R.get("KIND")] += 1; fuels[R.get("FUEL")] += 1
        d = R.get("D_REG", ""); mon = d[:7] if re.match(r"\d{4}-", d) else (d[-4:] + "-" + d[3:5] if re.match(r"\d\d\.\d\d\.\d{4}", d) else d)
        months[mon] += 1
        if "НОВ" in (R.get("OPER_NAME") or "").upper():
            newops[op] += 1
            if R.get("KIND") == "ЛЕГКОВИЙ":
                f = R.get("FUEL"); nf[mon][f] += 1
                body[R.get("BODY")] += 1; purpose[R.get("PURPOSE")] += 1; person[R.get("PERSON")] += 1
                if re.search(r"ЕЛЕКТР|ГІБРИД", f or "", re.I):
                    elb[(f, R.get("BRAND"))] += 1; elm[(f, R.get("BRAND"), R.get("MODEL"))] += 1
                if f and "АБО" in f: hyb[(f, R.get("BRAND"), R.get("MODEL"))] += 1
    print(f"\n######## {year}: rows {n}")
    for title, c, k in (("OPS", ops, 80), ("NEW OPS", newops, 40), ("KIND", kinds, 30), ("FUEL all", fuels, 40),
                        ("MONTH", months, 30), ("new-car BODY", body, 25), ("new-car PURPOSE", purpose, 15),
                        ("new-car PERSON", person, 5), ("new-car el (fuel,brand)", elb, 50),
                        ("new-car el (fuel,brand,model)", elm, 70), ("new-car 'АБО' fuels (fuel,brand,model)", hyb, 40)):
        print(f"\n-- {title} ({len(c)} distinct)")
        for v, m in c.most_common(k): print(f"   {m:8d}  {v}")
    print("\n-- NEW ЛЕГКОВИЙ by month x fuel")
    for mon in sorted(nf):
        tot = sum(nf[mon].values())
        print(f"   {mon} total={tot}  " + "; ".join(f"{f}={v}" for f, v in nf[mon].most_common()))
