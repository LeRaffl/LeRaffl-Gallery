#!/usr/bin/env python3
"""TEMPORARY probe for the Argentina source investigation. Delete when done."""
import collections, csv, io, json, os, re, subprocess, sys, zipfile
import requests

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (LeRaffl-Gallery probe)"
MODE = os.environ.get("PROBE_MODE", "all")


def sec(t):
    print("\n" + "=" * 20 + " " + t + " " + "=" * 20, flush=True)


def get(url, **kw):
    try:
        r = S.get(url, timeout=kw.pop("timeout", 120), **kw)
        print(f"GET {url} -> {r.status_code} {len(r.content)}B {r.headers.get('content-type')}")
        return r
    except Exception as e:  # noqa
        print(f"GET {url} -> ERR {e}")
        return None


def ckan():
    sec("CKAN")
    for base in ("https://datos.jus.gob.ar", "https://datos.gob.ar"):
        r = get(f"{base}/api/3/action/package_search?q=dnrpa&rows=100")
        if r is not None and r.ok:
            for p in r.json()["result"]["results"]:
                print("PKG", p["name"], "|", p.get("title"), "|", p.get("metadata_modified"))
    r = get("https://datos.jus.gob.ar/api/3/action/package_show?id=inscripciones-iniciales-de-autos")
    res = []
    if r is not None and r.ok:
        for x in r.json()["result"]["resources"]:
            print("RES", x.get("name"), "|", x.get("url"), "|", x.get("last_modified") or x.get("created"))
            res.append(x)
    return res


def load_rows(url):
    r = get(url, timeout=600)
    if r is None or not r.ok:
        return []
    data = r.content
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        print("ZIP members", z.namelist())
        rows = []
        for n in z.namelist():
            if n.endswith(".csv"):
                rows += list(csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig")))
        return rows
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig", "replace"))))


def analyse(rows, label):
    sec(f"ANALYSE {label} n={len(rows)}")
    if not rows:
        return
    print("COLUMNS", list(rows[0].keys()))
    for i in range(3):
        print("ROW", json.dumps(rows[i], ensure_ascii=False))
    for col in ("tramite_tipo", "automotor_tipo_descripcion", "automotor_uso_descripcion",
                "titular_tipo_persona", "automotor_origen"):
        c = collections.Counter(r.get(col) for r in rows)
        print(f"-- {col}: {len(c)} distinct")
        for k, v in c.most_common(80):
            print(f"   {v:8d}  {k}")
    months = collections.Counter((r.get("tramite_fecha") or "")[:7] for r in rows)
    print("-- tramite month:", sorted(months.items()))
    months = collections.Counter((r.get("fecha_inscripcion_inicial") or "")[:7] for r in rows)
    print("-- inscripcion month:", sorted(months.items())[-30:])
    extra = [c for c in rows[0].keys() if re.search(r"combust|motor_|energ|propul", c, re.I)]
    print("-- fuel-like columns:", extra)
    mm = collections.Counter((r.get("automotor_tipo_descripcion"), r.get("automotor_marca_descripcion"),
                              r.get("automotor_modelo_descripcion")) for r in rows)
    kw = re.compile(r"HEV|HIBRID|HYBRID|ELECTR|\bEV\b|E-|PHEV|DM-?I|DM-?P|KWH|48V|MHEV|BEV|E-TECH|\bE\b|PLUG|ENCHUF", re.I)
    print("-- keyword model matches")
    for (t, b, m), v in sorted(mm.items(), key=lambda x: -x[1]):
        if kw.search(m or ""):
            print(f"KW {v:6d} | {t} | {b} | {m}")
    ev_brands = {"BYD", "TESLA", "JAC", "SERO", "CORADIR", "VOLT", "LEAPMOTOR", "GWM", "GREAT WALL", "ZEEKR",
                 "CHANGAN", "DEEPAL", "GEELY", "XPENG", "NIO", "KAIYI", "DONGFENG", "JETOUR", "CHERY", "BAIC",
                 "HAVAL", "ORA", "NETA", "OMODA", "JAECOO", "AVATR", "MG", "POLESTAR", "VOYAH", "ZXAUTO",
                 "SHINERAY", "FOTON", "RIDDARA", "HONGQI", "LYNK & CO", "TANK", "SWM", "DFSK", "KYC", "HALEI",
                 "MOBILITY", "TITO", "OLIMPIA", "WULING", "KARRY", "SOUEAST", "MAXUS", "HYUNDAI", "KIA", "VOLVO",
                 "MINI", "BMW", "MERCEDES", "PORSCHE", "AUDI", "NISSAN", "RENAULT", "PEUGEOT", "CITROEN",
                 "FIAT", "TOYOTA", "LEXUS", "FORD", "HONDA", "SUBARU", "MITSUBISHI", "JEEP", "RAM", "DS", "CUPRA",
                 "CHEVROLET", "VOLKSWAGEN", "SUZUKI", "LAND ROVER", "JAGUAR"}
    print("-- all (marca, modelo) for suspected EV/new-energy brands, count>=3, sorted")
    for (t, b, m), v in sorted(mm.items(), key=lambda x: (x[0][1] or "", -x[1])):
        bb = (b or "").upper()
        if v >= 3 and any(bb.startswith(e) for e in ev_brands):
            print(f"BM {v:6d} | {t} | {b} | {m}")


def acara():
    sec("ACARA")
    urls = [
        "https://autoblog.com.ar/wp-content/uploads/2026/06/2026.05-ACARA.-Informe-de-Mercado-4W_Instit.pdf",
        "https://www.acara.org.ar/estudios_economicos/estadisticas.php",
        "https://www.acara.org.ar/",
        "https://api.acara.org.ar/storage/files/circulars/download/socios/autos0301.pdf",
    ]
    for u in urls:
        r = get(u)
        if r is None or not r.ok:
            continue
        if r.content[:4] == b"%PDF":
            open("/tmp/p.pdf", "wb").write(r.content)
            out = subprocess.run(["pdftotext", "-layout", "/tmp/p.pdf", "-"], capture_output=True, text=True).stdout
            print(out[:30000])
        else:
            t = r.text
            for m in sorted(set(re.findall(r'href="([^"]+)"', t))):
                if re.search(r"pdf|informe|estad|electro|patent", m, re.I):
                    print("LINK", m)


if __name__ == "__main__":
    if MODE in ("all", "acara"):
        acara()
    if MODE in ("all", "dnrpa"):
        res = ckan()
        yr = [x for x in res if re.search(r"2026", (x.get("name") or "") + (x.get("url") or ""))]
        for x in yr[:2]:
            analyse(load_rows(x["url"]), x["url"])
