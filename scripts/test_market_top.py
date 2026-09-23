#!/usr/bin/env python3
"""Offline tests for the top brands / models summaries (scripts/market_top.py
and the Spain / Malaysia fetchers that feed it). No network.

    python scripts/test_market_top.py
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_top as mt  # noqa: E402


def test_build_top_ranks_and_scopes():
    units = {("BEV", "BYD", "DOLPHIN"): 30, ("BEV", "TESLA", "MODEL Y"): 50,
             ("BEV", "TESLA", "MODEL 3"): 20, ("HEV", "TOYOTA", "YARIS"): 40,
             ("PETROL", "SEAT", "IBIZA"): 860, ("OTHERS", "DACIA", "SANDERO GLP"): 0}
    top = mt.build_top("X", "SRC", "2026-08", units, 1000, "u")
    assert top["window"] == {"from": "2025-09", "to": "2026-08", "months": 12}
    assert list(top["classes"]) == ["BEV", "HEV"]            # ICE never listed
    bev = top["classes"]["BEV"]
    assert bev["units"] == 100 and bev["share_of_market"] == 0.1
    assert bev["brands"][0] == {"brand": "TESLA", "units": 70, "share_of_class": 0.7}
    assert [m["model"] for m in bev["models"]] == ["MODEL Y", "DOLPHIN", "MODEL 3"]


def test_ties_are_order_independent_and_file_is_stable():
    a = {("PHEV", "B", "M1"): 5, ("PHEV", "A", "M2"): 5}
    b = dict(reversed(list(a.items())))
    ta, tb = (mt.build_top("X", "S", "2026-01", u, 10, "u") for u in (a, b))
    assert mt.dumps(ta) == mt.dumps(tb)
    assert [x["brand"] for x in ta["classes"]["PHEV"]["brands"]] == ["A", "B"]
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.json"
        assert mt.write_top(ta, p) is True
        assert mt.write_top(tb, p) is False                   # unchanged → no write
        assert mt.top_as_of(p) == "2026-01"
    assert mt.top_as_of(Path("/nonexistent/x.json")) is None


def test_clean_and_guarded():
    assert mt.clean("  model   y ") == "MODEL Y" and mt.clean(None) == ""
    assert mt.strip_brand("BYD", "BYD DOLPHIN SURF") == "DOLPHIN SURF"
    assert mt.strip_brand("MG", "MGS5") == "MGS5"             # not a word prefix
    assert mt.strip_brand("KIA", "KIA") == "KIA"

    def boom():
        raise KeyError("maker")
    mt.guarded(boom)                                          # must not raise


def _dgt_record(tipo, nu, cat_elec, prop, marca, modelo, clave="1"):
    import fetch_spain as fs
    rec = [" "] * fs.RECORD_LEN

    def put(name, val):
        a, b = fs._slice(name)
        rec[a:b] = list(val.ljust(b - a)[: b - a])
    put("FEC_MATRICULA", "01082026")
    put("COD_TIPO", tipo)
    put("IND_NUEVO_USADO", nu)
    put("CATEGORIA_VEHICULO_ELECTRICO", cat_elec)
    put("COD_PROPULSION_ITV", prop)
    put("MARCA_ITV", marca)
    put("MODELO_ITV", modelo)
    put("CLAVE_TRAMITE", clave)
    return "".join(rec)


def test_spain_aggregate_models():
    import fetch_spain as fs
    lines = ["Fichero de microdatos (banner line)",
             _dgt_record("40", "N", "BEV", "2", "TESLA", "MODEL Y"),
             _dgt_record("40", "N", "BEV", "2", "TESLA", "MODEL  Y "),   # same model
             _dgt_record("40", "N", "BEV", "2", "TESLA", "TESLA MODEL Y"),  # brand repeated
             _dgt_record("25", "N", "PHEV", "0", "BYD", "SEAL U DM-I"),
             _dgt_record("40", "N", "", "0", "SEAT", "IBIZA"),
             _dgt_record("40", "U", "BEV", "2", "TESLA", "MODEL 3"),      # used → out
             _dgt_record("50", "N", "BEV", "2", "SILENCE", "S01")]        # moto → out
    txt = ("\n".join(lines) + "\n").encode("latin-1")
    units, total = fs.aggregate_models(txt)
    assert total == 5, total
    assert units == {("BEV", "TESLA", "MODEL Y"): 3, ("PHEV", "BYD", "SEAL U DM-I"): 1,
                     ("PETROL", "SEAT", "IBIZA"): 1}, units
    # The total must equal what aggregate() writes to data/Spain.csv (scaled
    # past its 2,000-record corruption guard).
    big = ("\n".join([lines[0]] + lines[1:] * 600) + "\n").encode("latin-1")
    counts = fs.aggregate(big, "2026-08", ["Whole"])["Whole"]
    big_units, big_total = fs.aggregate_models(big)
    assert big_total == counts["TOTAL"] == 3000
    for cls in ("BEV", "PHEV", "PETROL"):
        assert sum(n for (c, _, _), n in big_units.items() if c == cls) == counts[cls]


def test_spain_latest_dgt_period():
    import fetch_spain as fs
    rows = [{"period": "2026-07", "variant": "Whole", "source": "DGT"},
            {"period": "2026-08", "variant": "Whole", "source": "DGT"},
            {"period": "2026-09", "variant": "Whole", "source": "ACEA"}]
    assert fs.latest_dgt_period(rows) == "2026-08"
    assert fs.latest_dgt_period([]) is None


def test_malaysia_build_top():
    try:
        import pandas as pd
    except ImportError:
        print("   (pandas missing — Malaysia test skipped)")
        return
    import fetch_malaysia as fm
    df = pd.DataFrame({
        "date_reg": ["2026-08-03", "2026-08-09", "2025-09-01", "2025-08-31", "2026-08-10", "2026-02-02"],
        "maker":    ["BYD", "byd ", "Proton", "BYD", "Toyota", "Proton"],
        "model":    ["Atto 3", "ATTO 3", "e.MAS 7", "Atto 3", "Vios", "Saga"],
        "fuel":     ["electric", "Electric", "electric", "electric", "hybrid_petrol", "petrol"],
    })
    top = fm.build_top([df], "2026-08")
    assert top["total_registrations"] == 5                  # 2025-08 is outside
    bev = top["classes"]["BEV"]
    assert bev["units"] == 3 and bev["brands"][0] == {"brand": "BYD", "units": 2,
                                                       "share_of_class": 0.6667}
    assert bev["models"][0]["model"] == "ATTO 3"
    assert top["classes"]["HEV"]["units"] == 1 and "PETROL" not in top["classes"]
    json.dumps(top)                                          # numpy ints would fail here


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
