"""Temporary probe: where are CADAM's extra 2025 BEVs? Not for master."""
import csv, io, re, json, collections, pathlib, sys, time
sys.path.insert(0, "scripts")
import fetch_paraguay as fp
OUT = pathlib.Path("probe_out"); OUT.mkdir(exist_ok=True)
S = fp.make_session()

# CADAM press releases
for slug in ["importaciones-de-vehiculos-hibridos-y-electricos-crecieron-657-en-2025",
             "importaciones-de-vehiculos-hibridos-y-electricos-crecieron-628-en-noviembre-de-2025",
             "importaciones-de-vehiculos-hibridos-y-electricos-crecieron-70-en-octubre",
             "importaciones-de-vehiculos-hibridos-y-electricos-crecieron-138-al-mes-de-febrero"]:
    for base in ("https://www.cadam.com.py/detalle/", "https://www.cadam.com.py/noticia/"):
        try:
            r = S.get(base + slug, timeout=60)
            if r.ok and len(r.text) > 5000:
                txt = re.sub(r"<script.*?</script>|<style.*?</style>", " ", r.text, flags=re.S)
                txt = re.sub(r"<[^>]+>", " ", txt); txt = re.sub(r"\s+", " ", txt)
                (OUT / f"cadam_{slug[:60]}.txt").write_text(txt)
                imgs = re.findall(r'src="([^"]+\.(?:png|jpe?g|webp))"', r.text)
                (OUT / f"cadam_{slug[:60]}.imgs.txt").write_text("\n".join(imgs))
                print("ok", base + slug, len(txt)); break
        except Exception as e:
            print("ERR", slug, e)

files = fp.list_month_urls(S)
agg = collections.Counter()      # (period, sub, uso, dest, op) -> units
brand = collections.Counter()    # (period, sub, uso, dest, brand) for 8703.80/8704.60/8703.10
ofi = collections.Counter()      # (file period, oficializacion month) for counted new BEV
text10 = collections.Counter()   # 8703.10 descriptions
text8704 = collections.Counter() # 8704.60 descriptions
for m in range(1, 13):
    p = f"2025-{m:02d}"
    size = fp.head(S, files[p])[0]
    t = time.time(); raw = fp.download(S, files[p], size); txt = fp.decode(raw)
    rd = csv.reader(io.StringIO(txt)); col = fp.resolve_columns(next(rd))
    hdr_extra = None
    n = 0
    for r in rd:
        if len(r) <= max(col.values()): continue
        pos = r[col["POSICION"]]
        if not pos.startswith(("8703", "8704")): continue
        sub = fp.subheading(pos); uso = fp.norm(r[col["USO"]]); d = fp.norm(r[col["DESTINACION"]])
        op = r[col["OPERACION"]]
        units = fp.units_of(fp.num(r[col["CANTIDAD ESTADISTICA"]]), fp.num(r[col["KILO NETO"]]))
        agg[(p, sub, uso, d, op)] += units
        tx = fp.norm(r[col["MERCADERIA"]])
        b = fp.display_brand(r[col["MARCA ITEM"]])
        if sub in ("8703.80", "8704.60", "8703.10") or (sub.startswith("8704") and re.search(r"ELECTRIC", tx)):
            brand[(p, sub, uso, d, b)] += units
        if sub == "8703.10": text10[(b, tx[:90])] += units
        if sub.startswith("8704") and re.search(r"ELECTRIC|\bEV\b", tx): text8704[(sub, b, tx[:90])] += units
        n += 1
    print(p, f"{len(raw)/1e6:.0f}MB {time.time()-t:.0f}s, {n} vehicle items", flush=True)
with open(OUT / "delta_agg.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["period","sub","uso","dest","op","units"])
    for k, v in sorted(agg.items()): w.writerow([*k, v])
with open(OUT / "delta_brand.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["period","sub","uso","dest","brand","units"])
    for k, v in sorted(brand.items()): w.writerow([*k, v])
(OUT / "text_8703_10.json").write_text(json.dumps(text10.most_common(80), ensure_ascii=False, indent=0))
(OUT / "text_8704_ev.json").write_text(json.dumps(text8704.most_common(80), ensure_ascii=False, indent=0))
