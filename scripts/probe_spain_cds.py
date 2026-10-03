#!/usr/bin/env python3
"""
TEMPORARY probe — why is cardatasales.com's Spanish turismo market ~4 %
below our Whole (both built from DGT registrations)?

For 2026-07 and 2026-08 (monthly files) it:
  * pulls cardatasales' per-model monthly matrix (sums exactly to their totals);
  * counts our Whole records per brand / model;
  * diffs per brand and per model;
  * for every candidate attribute, lists value counts inside Whole and which
    single value (or value set) removed from Whole lands on their total;
  * dumps attribute mixes of the records of the models we over-count.
"""
from __future__ import annotations

import collections
import io
import json
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_spain as fs  # noqa: E402

CDS = "https://cardatasales.com/api/analytics/monthly-matrix"
MONTH_KEY = {"01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may",
             "06": "jun", "07": "jul", "08": "ago", "09": "sep", "10": "oct",
             "11": "nov", "12": "dic"}
ATTRS = ["COD_TIPO", "COD_CLASE_MAT", "CLAVE_TRAMITE", "COD_PROCEDENCIA_ITV",
         "PERSONA_FISICA_JURIDICA", "SERVICIO", "RENTING",
         "CATEGORIA_HOMOLOGACION_EUROPEA_ITV", "CARROCERIA",
         "CLASIFICACION_REGLAMENTO_VEHICULOS_ITV", "COD_POSESION",
         "COD_TUTELA", "IND_BAJA_DEF", "IND_BAJA_TEMP", "IND_SUSTRACCION",
         "IND_PRECINTO", "IND_EMBARGO", "NUM_TITULARES", "NUM_TRANSMISIONES",
         "CATEGORIA_VEHICULO_ELECTRICO", "COD_PROPULSION_ITV", "NUM_PLAZAS",
         "COD_PROVINCIA_MAT", "TIPO_ALIMENTACION_ITV"]
SL = {a: fs._slice(a) for a in ATTRS}
SL_FECMAT = fs._slice("FEC_MATRICULA")
SL_FECPRIM = fs._slice("FEC_PRIM_MATRICULACION")
SL_BAJA_TEL = fs._slice("BAJA_TELEMATICA")


def field(line, a):
    s, e = SL[a]
    return line[s:e].strip()


def cds_matrix(session):
    r = session.get(CDS, params={"year": "2026", "limit": "5000",
                                 "sort_by": "total", "sort_dir": "desc"},
                    timeout=180)
    r.raise_for_status()
    return r.json()


def norm(s):
    return " ".join(s.upper().split())


def main():
    session = fs.make_session()
    matrix = cds_matrix(requests.Session())
    for period in ("2026-08", "2026-07"):
        mk = MONTH_KEY[period[5:]]
        cds_total = sum(r[mk] for r in matrix)
        cds_brand = collections.Counter()
        cds_model = collections.Counter()
        for r in matrix:
            cds_brand[norm(r["marca"])] += r[mk]
            cds_model[(norm(r["marca"]), norm(r["modelo"]))] += r[mk]

        txt, url = fs.download_month(session, period)
        whole = []
        stream = io.TextIOWrapper(io.BytesIO(txt), encoding="latin-1")
        for i, line in enumerate(stream):
            if i == 0 and not line[:1].isdigit():
                continue
            line = line.rstrip("\r\n")
            if len(line) == fs.RECORD_LEN and "Whole" in fs.record_variants(line):
                whole.append(line)
        del txt
        n = len(whole)
        gap = n - cds_total
        print(f"\n\n================ {period}: ours {n:,}  cds {cds_total:,}  "
              f"gap {gap:+,} ({gap / cds_total * 100:+.2f} %)")

        def bm(line):
            b = fs.market_top.clean(line[fs.SL_MARCA[0]:fs.SL_MARCA[1]])
            m = fs.market_top.strip_brand(
                b, fs.market_top.clean(line[fs.SL_MODELO[0]:fs.SL_MODELO[1]]))
            return norm(b), norm(m)

        our_brand = collections.Counter(bm(l)[0] for l in whole)
        our_model = collections.Counter(bm(l) for l in whole)

        print("\n### brands, ours - cds (|diff| >= 30)")
        rows = sorted(set(our_brand) | set(cds_brand),
                      key=lambda b: -(our_brand[b] - cds_brand[b]))
        for b in rows:
            d = our_brand[b] - cds_brand[b]
            if abs(d) >= 30:
                print(f"  {b:<32} ours {our_brand[b]:>6,} cds {cds_brand[b]:>6,} "
                      f"diff {d:>+6,}")
        pos = sum(max(0, our_brand[b] - cds_brand[b]) for b in rows)
        neg = sum(min(0, our_brand[b] - cds_brand[b]) for b in rows)
        print(f"  brand-level: +{pos:,} / {neg:,}")

        print("\n### models, ours - cds (top 40 positive)")
        mods = sorted(set(our_model) | set(cds_model),
                      key=lambda k: -(our_model[k] - cds_model[k]))
        for k in mods[:40]:
            print(f"  {k[0]:<20} {k[1]:<26} ours {our_model[k]:>5,} "
                  f"cds {cds_model[k]:>5,} diff {our_model[k] - cds_model[k]:>+5,}")
        print("  … top 15 negative")
        for k in mods[-15:]:
            print(f"  {k[0]:<20} {k[1]:<26} ours {our_model[k]:>5,} "
                  f"cds {cds_model[k]:>5,} diff {our_model[k] - cds_model[k]:>+5,}")

        print("\n### attribute value counts inside Whole (values >= 50 or "
              "within 15 % of the gap)")
        for a in ATTRS:
            c = collections.Counter(field(l, a) for l in whole)
            hits = [(v, k) for v, k in c.items()
                    if abs(k - gap) <= max(150, 0.15 * gap)]
            show = ", ".join(f"{v!r}:{k:,}" for v, k in c.most_common(14))
            print(f"  {a:<40} {show}")
            if hits:
                print(f"     >>> value(s) matching the gap: {hits}")

        # first-registration date before this month = previously registered
        # abroad? (Whole is IND_NUEVO_USADO = N, but check anyway)
        prev = sum(1 for l in whole
                   if l[SL_FECPRIM[0]:SL_FECPRIM[1]].strip()
                   and l[SL_FECPRIM[0]:SL_FECPRIM[1]][4:8] + l[SL_FECPRIM[0]:SL_FECPRIM[1]][2:4]
                   < period.replace("-", ""))
        bt = sum(1 for l in whole if l[SL_BAJA_TEL[0]:SL_BAJA_TEL[1]].strip())
        fm = collections.Counter(
            l[SL_FECMAT[0]:SL_FECMAT[1]][4:8] + "-" + l[SL_FECMAT[0]:SL_FECMAT[1]][2:4]
            for l in whole)
        print(f"  FEC_PRIM_MATRICULACION before {period}: {prev:,}; "
              f"BAJA_TELEMATICA set: {bt:,}; FEC_MATRICULA months: "
              f"{dict(fm.most_common(4))}")

        # --- decomposition of the gap ---------------------------------
        t25 = [l for l in whole if field(l, "COD_TIPO") == "25"]
        t40 = [l for l in whole if field(l, "COD_TIPO") == "40"]
        b25 = collections.Counter(bm(l)[0] for l in t25)
        m25 = collections.Counter(bm(l) for l in t25)
        print(f"\n### DECOMP tipo 25 todo terreno: {len(t25):,} "
              f"(gap left after removing it: {gap - len(t25):+,})")
        print("  brands: " + ", ".join(f"{b} {n}" for b, n in b25.most_common(15)))
        print("  models: " + ", ".join(f"{b} {m} {n}" for (b, m), n in m25.most_common(20)))
        b40 = collections.Counter(bm(l)[0] for l in t40)
        print("### DECOMP tipo 40 only, brand diff vs cds (|d|>=20):")
        for b in sorted(set(b40) | set(cds_brand), key=lambda b: -(b40[b] - cds_brand[b])):
            d = b40[b] - cds_brand[b]
            if abs(d) >= 20:
                print(f"  {b:<28} ours40 {b40[b]:>6,} cds {cds_brand[b]:>6,} diff {d:>+5,}")
        gapb = {b for b in b40 if b40[b] - cds_brand[b] >= 20}
        for b in sorted(gapb, key=lambda b: -(b40[b] - cds_brand[b]))[:10]:
            mm = collections.Counter((bm(l)[1], field(l, "CARROCERIA"),
                                      field(l, "NUM_PLAZAS"))
                                     for l in t40 if bm(l)[0] == b)
            print(f"  {b}: " + "; ".join(f"{m} [{c},{p}] {n}" for (m, c, p), n
                                          in mm.most_common(18)))
        for a in ("CARROCERIA", "CLASIFICACION_REGLAMENTO_VEHICULOS_ITV",
                  "NUM_PLAZAS"):
            c = collections.Counter(field(l, a) for l in t40)
            print(f"  tipo40 {a}: {dict(c.most_common(10))}")

        # attribute mix of the over-counted models' records
        over = {k for k in mods[:40] if our_model[k] - cds_model[k] > 0}
        sub = [l for l in whole if bm(l) in over]
        print(f"\n### attribute mix of the {len(sub):,} records of the 40 most "
              f"over-counted models vs all of Whole (share %)")
        for a in ATTRS:
            cs = collections.Counter(field(l, a) for l in sub)
            cw = collections.Counter(field(l, a) for l in whole)
            line = ", ".join(f"{v!r}:{cs[v] / len(sub) * 100:.0f}/"
                             f"{cw[v] / n * 100:.0f}"
                             for v, _ in cs.most_common(6))
            print(f"  {a:<40} {line}")

        # does the gap concentrate in specific models fully missing at cds?
        missing = [(k, our_model[k]) for k in our_model if cds_model[k] == 0]
        missing.sort(key=lambda x: -x[1])
        print(f"\n### models absent at cds: {len(missing)} models, "
              f"{sum(x[1] for x in missing):,} records; top 30:")
        for k, v in missing[:30]:
            print(f"  {k[0]:<20} {k[1]:<26} {v:>5,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
