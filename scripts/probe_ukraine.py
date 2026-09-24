#!/usr/bin/env python3
"""TEMPORARY probe v3 for Ukraine (MIA/HSC registrations on data.gov.ua).
Streams every yearly zip (2013 →), keeps first registrations only and writes
an aggregate (month, op, kind, wt, fuel, person, brand, model, age, n) to
probe_out/ukraine_agg.csv.gz, plus a per-year op inventory. Also dumps
Ukrautoprom's monthly market posts for a cross-check. Removed before merge."""
import collections, csv, gzip, io, os, re, sys, zipfile
import requests

PKG = "https://data.gov.ua/api/3/action/package_show?id=0ffd8b75-0628-48cc-952a-9302f9799ec0"
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 LeRaffl-Gallery probe"
csv.field_size_limit(10**7)

def resources():
    res = S.get(PKG, timeout=120).json()["result"]["resources"]
    out = {}
    for r in res:
        m = re.search(r"(20\d\d)", r.get("name", "") or "")
        if m:
            out.setdefault(int(m.group(1)), []).append(((r.get("last_modified") or r.get("created") or ""), r["url"]))
    return {y: sorted(v)[-1][1] for y, v in out.items()}

def month_of(d):
    d = d.strip()
    m = re.match(r"(\d{4})-(\d\d)-\d\d", d)
    if m: return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"(\d\d)\.(\d\d)\.(\d{2,4})", d)
    if m:
        y = m.group(3); y = ("20" + y) if len(y) == 2 else y
        return f"{y}-{m.group(2)}"
    return None

agg = collections.Counter()
inv = collections.Counter()           # (year, op_code, op_name, kind) all ops
for year, url in sorted(resources().items()):
    print(f"\n=== {year} {url}", flush=True)
    r = S.get(url, timeout=1800); r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content)); del r
    for info in z.infolist():
        if not info.filename.lower().endswith(".csv"): continue
        raw = z.read(info.filename)
        try: text = raw.decode("utf-8-sig"); enc = "utf-8"
        except UnicodeDecodeError: text = raw.decode("cp1251"); enc = "cp1251"
        del raw
        first = text[:3000].splitlines()[0]
        delim = ";" if first.count(";") > first.count(",") else ","
        print("member", info.filename, info.file_size, enc, repr(delim), first, flush=True)
        rd = csv.reader(io.StringIO(text), delimiter=delim)
        hdr = [h.strip().strip('"').upper() for h in next(rd)]
        ix = {h: i for i, h in enumerate(hdr)}
        opcol = next((h for h in hdr if "OPER" in h and "NAME" not in h and "CODE" in h), None)
        namecol = "OPER_NAME" if "OPER_NAME" in ix else None
        def get(row, k):
            i = ix.get(k); return row[i].strip() if i is not None and i < len(row) else ""
        n = 0; bad = 0
        for row in rd:
            n += 1
            opraw = get(row, opcol) if opcol else ""
            m = re.match(r"\s*(\d+)\s*(?:-\s*(.*))?$", opraw)
            if not m: bad += 1; continue
            code = int(m.group(1)); name = (m.group(2) or get(row, namecol) or "").strip()
            kind = get(row, "KIND")
            inv[(year, code, name[:90], kind)] += 1
            first_reg = (code in (69,70,71,72,74,75,76,77,99,100,102,105,180,184,185)
                         or "ПЕРВИН" in name.upper())
            if not first_reg: continue
            mon = month_of(get(row, "D_REG")) or "?"
            try: tw = float(get(row, "TOTAL_WEIGHT") or 0)
            except ValueError: tw = 0
            wt = "?" if tw <= 0 else ("le3500" if tw <= 3500 else "gt3500")
            try: my = int(get(row, "MAKE_YEAR"))
            except ValueError: my = 0
            age = "?" if not my else str(max(-1, min(int(mon[:4]) - my if mon[:4].isdigit() else 99, 30)))
            agg[(mon, code, kind, wt, get(row, "BODY"), get(row, "FUEL"), get(row, "PERSON"),
                 get(row, "BRAND"), get(row, "MODEL"), age)] += 1
        del text
        print(f"rows {n} unparsed-op {bad} agg-keys {len(agg)}", flush=True)

os.makedirs("probe_out", exist_ok=True)
with gzip.open("probe_out/ukraine_agg.csv.gz", "wt", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh); w.writerow(["month","op","kind","wt","body","fuel","person","brand","model","age","n"])
    for k, v in sorted(agg.items(), key=lambda kv: tuple(str(x) for x in kv[0])): w.writerow(list(k) + [v])
with open("probe_out/ukraine_ops.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh); w.writerow(["year","op","name","kind","n"])
    for k, v in sorted(inv.items(), key=lambda kv: tuple(str(x) for x in kv[0])): w.writerow(list(k) + [v])
print("written", os.path.getsize("probe_out/ukraine_agg.csv.gz"), flush=True)

# Ukrautoprom cross-check (best effort)
try:
    from html.parser import HTMLParser
    class T(HTMLParser):
        def __init__(s): super().__init__(); s.out=[]; s.links=[]; s.skip=0
        def handle_starttag(s,t,a):
            if t in("script","style"): s.skip+=1
            if t=="a":
                h=dict(a).get("href") or ""
                s.links.append(h)
        def handle_endtag(s,t):
            if t in("script","style"): s.skip-=1
        def handle_data(s,d):
            if not s.skip and d.strip(): s.out.append(d.strip())
    seen=set(); pages=["https://ukrautoprom.com.ua/"]+[f"https://ukrautoprom.com.ua/page/{i}/" for i in range(2,8)]
    posts=[]
    for p in pages:
        rr=S.get(p,timeout=60); t=T(); t.feed(rr.text)
        print("UAP", p, rr.status_code, len(rr.text))
        for h in t.links:
            if "ukrautoprom.com.ua" in h and h not in seen and re.search(r"\d{4}/\d\d|/[a-z0-9-]*(rynok|legkov|elektr|avto)", h, re.I):
                seen.add(h); posts.append(h)
    with open("probe_out/ukrautoprom.txt","w",encoding="utf-8") as fh:
        for h in posts[:80]:
            rr=S.get(h,timeout=60); t=T(); t.feed(rr.text)
            body=" | ".join(t.out)
            if re.search(r"легков|електро", body, re.I):
                fh.write(f"\n##### {h}\n{body[:6000]}\n")
    print("ukrautoprom posts", len(posts))
except Exception as e:
    print("UAP ERR", e)
