#!/usr/bin/env python3
"""TEMPORARY probe for the Argentina source investigation. Delete when done.

Aggregates every DNRPA inscripciones-iniciales yearly zip to
(month, tipo, marca, modelo, titular_tipo_persona, uso) counts and prints the
result gzip+base64 so the dev sandbox (which cannot reach datos.jus.gob.ar)
can rebuild it from the job log.
"""
import base64, collections, csv, gzip, io, zipfile
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (LeRaffl-Gallery probe)"
PKG = "https://datos.jus.gob.ar/api/3/action/package_show?id=inscripciones-iniciales-de-autos"

res = S.get(PKG, timeout=60).json()["result"]["resources"]
agg = collections.Counter()
for x in res:
    url = x["url"]
    if not url.endswith(".zip"):
        continue
    r = S.get(url, timeout=900)
    print("GET", url, r.status_code, len(r.content), flush=True)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    for n in z.namelist():
        if not n.endswith(".csv"):
            continue
        k = 0
        for row in csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")):
            k += 1
            agg[((row.get("tramite_fecha") or "")[:7],
                 row.get("tramite_tipo") or "",
                 row.get("automotor_tipo_descripcion") or "",
                 row.get("automotor_marca_descripcion") or "",
                 row.get("automotor_modelo_descripcion") or "",
                 (row.get("titular_tipo_persona") or "")[:1],
                 (row.get("automotor_uso_descripcion") or "")[:3],
                 row.get("automotor_anio_modelo") or "")] += 1
        print("  member", n, k, "rows", flush=True)

buf = io.StringIO()
w = csv.writer(buf, lineterminator="\n")
w.writerow(["month", "tramite", "tipo", "marca", "modelo", "persona", "uso", "anio", "n"])
for key, n in sorted(agg.items()):
    w.writerow(list(key) + [n])
blob = base64.b64encode(gzip.compress(buf.getvalue().encode(), 9)).decode()
print("AGG rows", len(agg), "b64 chars", len(blob), flush=True)
for i in range(0, len(blob), 2000):
    print("B64:" + blob[i:i + 2000])
print("B64END")
