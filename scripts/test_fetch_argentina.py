#!/usr/bin/env python3
"""Regression tests for scripts/fetch_argentina.py (no network).

Run:  python scripts/test_fetch_argentina.py

The fetcher's failure mode is a silently wrong fuel split: DNRPA carries no
fuel field, so the powertrain comes from the model designation. These cases
pin every rule to real DNRPA designations — especially the traps where the
obvious token lies — plus the scope filter and the line-level upsert.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_argentina as fa  # noqa: E402

# (marca, modelo) -> fuel, all real strings from the 2018–2026 microdata.
CLASSIFY_CASES = {
    # --- BEV ---
    ("BYD", "DOLPHIN MINI EV GS"): "BEV",
    ("BYD", "YUAN PRO EV GS"): "BEV",
    ("RENAULT", "KWID E-TECH ELECTRICO"): "BEV",
    ("RENAULT", "MEGANE E-TECH ELECTRICO"): "BEV",
    ("RENAULT", "KANGOO Z.E. MAXI 2A"): "BEV",
    ("NISSAN", "LEAF TEKNA"): "BEV",
    ("CHEVROLET", "SPARK EUV ACTIV"): "BEV",
    ("CHEVROLET", "BOLT EUV PREMIER"): "BEV",
    ("CHEVROLET", "CAPTIVA EV PREMIER"): "BEV",
    ("FORD", "MUSTANG MACH-E"): "BEV",
    ("TOYOTA", "BZ4X BEV 4WD"): "BEV",
    ("BMW", "IX2 XDRIVE30"): "BEV",
    ("MINI", "ACEMAN SE"): "BEV",
    ("VOLVO", "EX30 PLUS E60"): "BEV",
    ("VOLVO", "C40 P8 RECHARGE TWIN"): "BEV",
    ("AUDI", "Q8 SPORTBACK 55 E-TRON QUATTRO"): "BEV",
    ("PORSCHE", "TAYCAN 4S ELECTRIC"): "BEV",
    ("MERCEDES BENZ", "EQA 350 4MATIC"): "BEV",
    ("MERCEDES BENZ", "MERCEDES-BENZ EQE 500 SUV (BEV)"): "BEV",
    ("PEUGEOT", "E2008 GT AM25"): "BEV",
    ("GEELY", "EX5"): "BEV",
    ("GREAT WALL", "ORA 03"): "BEV",
    ("DONGFENG", "BOX"): "BEV",
    ("SMART", "SMART #1 PRO (BEV)"): "BEV",
    ("JMEV", "EVEASY 3"): "BEV",
    ("ARCFOX", "T1"): "BEV",
    ("BAIC", "EU5 ELECTRICO"): "BEV",
    ("CHANGAN", "DEEPAL S05"): "BEV",
    ("DEEPAL", "L07"): "BEV",               # Deepal registered as its own brand
    # --- EREV (range extenders) ---
    ("LEAPMOTOR", "C10 REEV DESIGN"): "EREV",
    ("FORTHING", "FRIDAY REEV"): "EREV",
    ("CHANGAN", "DEEPAL S07 REEV"): "EREV",
    # --- PHEV ---
    ("BYD", "ATTO 2 DM-I GS"): "PHEV",
    ("BYD", "SHARK DMO GS"): "PHEV",
    ("BYD", "SHARK GS"): "PHEV",            # no DM marker — must not fall to "BYD = BEV"
    ("JETOUR", "T1 I-DM"): "PHEV",
    ("CHEVROLET", "CAPTIVA PHEV PREMIER"): "PHEV",
    ("CHERY", "TIGGO 7 PRO HYBRID 1.5T PHEV PREMIUM"): "PHEV",
    ("CHANGAN", "CS55 PLUS"): "PHEV",
    ("DFSK", "E5"): "PHEV",
    ("DFSK", "E5 PLUS PHEV"): "PHEV",
    ("SHINERAY", "G03F EDI"): "PHEV",
    ("VOLVO", "XC60 T8 CORE"): "PHEV",
    ("VOLVO", "XC40 T5 TWIN ENGINE"): "PHEV",
    ("BMW", "330E"): "PHEV",
    ("BMW", "X1 XDRIVE25E"): "PHEV",
    ("BMW", "X3 XDRIVE 30E"): "PHEV",
    ("LAND ROVER", "DEFENDER P400E X-DYNAMIC"): "PHEV",
    ("MERCEDES BENZ", "GLC 300 E 4MATIC (PHEV)"): "PHEV",
    ("MERCEDES BENZ", "MERCEDES-AMG GT 63 S E PERFORMANCE (PHEV)"): "PHEV",
    ("PORSCHE", "CAYENNE S E-HYBRID COUPE"): "PHEV",
    ("PEUGEOT", "3008 GT PACK HYBRID4 AM22"): "PHEV",
    ("DS", "DS 7 CROSSBACK E-TENSE 4X4 300 BASTILLE+"): "PHEV",
    ("LEXUS", "NX 450H+"): "PHEV",
    ("JEEP", "WRANGLER UNLIMITED RUBICON 4XE"): "PHEV",
    ("FERRARI", "SF90 SPIDER"): "PHEV",
    # --- MHEV (the "HYBRID" that isn't) ---
    ("CHERY", "TIGGO 7 PRO HYBRID 1.5T MHEV PREMIUM"): "MHEV",
    ("RENAULT", "ARKANA E-TECH HYBRID ESPRIT ALPINE"): "MHEV",   # 1.3 TCe 12 V
    ("SUZUKI", "SWIFT HYBRID GLX CVT"): "MHEV",
    ("SUZUKI", "ACROSS HYBRID 1.5 AT GLX"): "MHEV",
    ("FIAT", "600 HYBRID 1.2 EDCT"): "MHEV",
    ("CITROEN", "C4 HYBRID PLUS"): "MHEV",
    ("DS", "DS 3 ETOILE HYBRID MY25"): "MHEV",
    ("MERCEDES BENZ", "GLC 300 4MATIC (MHEV)"): "MHEV",
    ("BMW", "X3 20 XDRIVE MHEV"): "MHEV",
    ("FOTON", "TUNLAND V9 4X4 AT - MHEV"): "MHEV",
    ("VOLVO", "XC40 B4"): "MHEV",
    ("AUDI", "Q5 ADVANCED PLUS"): "MHEV",
    ("AUDI", "SQ5 SPORTBACK"): "MHEV",
    # --- HEV ---
    ("FORD", "TERRITORY TREND 1.5L HIBRIDA AT"): "HEV",
    ("FORD", "MAVERICK LARIAT  FHEV 2.5L 4X2 8AT"): "HEV",
    ("FORD", "KUGA SE 2.5L HIBRIDO AT FWD"): "HEV",
    ("TOYOTA", "COROLLA CROSS SEG HEV 1.8 ECVT"): "HEV",
    ("TOYOTA", "PRIUS 1.8 CVT"): "HEV",
    ("TOYOTA", "COROLLA HV 1.8 SEG ECVT"): "HEV",   # Toyota's older "HV" badge
    ("LEXUS", "UX 250H"): "HEV",
    ("BAIC", "BJ30E"): "HEV",
    ("NISSAN", "X-TRAIL EPOWER EXCLUSIVE CVT"): "HEV",
    ("FORTHING", "T5HEV"): "HEV",
    ("RENAULT", "KOLEOS ESPRIT ALPINE FULL HYBRID E-TECH"): "HEV",
    ("MG", "ZS HYBRID+"): "HEV",
    ("HAVAL", "H6 HEV SUPREME"): "HEV",
    ("SUBARU", "CROSSTREK 2.0 HYBRID AWD CVT LIMITED ES"): "HEV",
    # --- ICE, including every trap ---
    ("TOYOTA", "HILUX 4X2 C/D DX PACK ELECTRICO 2.5 TDI - H3"): "ICE",  # electric windows
    ("CHEVROLET", "S10 2.8TDI DLX 4X2 ELECTRONIC CD"): "ICE",
    ("DS", "DS 4 PERFORMANCE LINE 215 A T8"): "ICE",                  # 8-speed gearbox
    ("JAGUAR", "E-TYPE"): "ICE",
    ("VOLKSWAGEN", "SURAN 80E"): "ICE",
    ("VOLVO", "P1800E"): "ICE",
    ("VOLVO", "XC60 T6 INSCRIPTION AWD"): "ICE",
    ("LAND ROVER", "RANGE ROVER EVOQUE P300 SE"): "ICE",
    ("CHANGAN", "MD201 BOX"): "ICE",
    ("BAIC", "X55"): "ICE",
    ("SHINERAY", "G03F"): "ICE",
    ("AUDI", "Q5 SPORTBACK 45 TFSI S LINE QUATTRO"): "ICE",           # old generation
    ("MERCEDES BENZ", "E 320 C"): "ICE",
    ("MERCEDES BENZ", "300 SE"): "ICE",
    ("SMART", "SMART FORFOUR PASSION AUTOMATICO"): "ICE",
    ("FORD", "TERRITORY TITANIUM 1.8L AT"): "ICE",
    ("FIAT", "CRONOS DRIVE 1.3 GSE BZ"): "ICE",
    ("JEEP", "COMPASS SERIE-S T270 AT6 FWD"): "ICE",
}

BODY_CASES = {
    "SEDAN 5 PUERTAS": "M1", "RURAL 5 PUERTAS": "M1", "RURAL 4/5 PUERTAS": "M1",
    "TODO TERRENO": "M1", "COUPE": "M1", "DESCAPOTABLE": "M1", "FAMILIAR": "M1",
    "PICK-UP": "PICKUP", "PICK-UP CABINA DOBLE": "PICKUP",
    "PICK-UP CARROZADA": "PICKUP", "PICK UP": "PICKUP",
    "FURGON": None, "FURGONETA": None, "UTILITARIO": None, "CHASIS C/CABINA": None,
    "TRANS.DE PASAJEROS": None, "MINIBUS (O MICROOMNIBUS)": None,
    "CUADRICICLO PESADO PASAJ-L7B": None, "VEHICULO ELECTRICO": None,
    "SEMIRREMOLQUE": None, "ARENERO": None, "SIN ESPECIFICACION": None,
}


def test_classify():
    bad = [(k, want, fa.classify(*k)) for k, want in CLASSIFY_CASES.items()
           if fa.classify(*k) != want]
    assert not bad, "\n".join(f"{k}: want {w}, got {g}" for k, w, g in bad)


def test_rules_table_is_well_formed():
    ids = [r["id"] for r in fa.RULES]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    assert [int(r["order"]) for r in fa.RULES] == list(range(1, len(fa.RULES) + 1)), \
        "order column must be 1..N with no gaps, in file order"
    for r in fa.RULES:
        assert r["class"] in fa.CLASSES, r["id"]
        assert r["kind"] in {"exclusion", "token", "brand-code", "model", "brand-all"}, r["id"]
        assert r["reason"].strip() and r["evidence"].strip(), f"{r['id']}: reason/evidence required"
        assert fa.DEFAULT_RULE != r["id"]


def test_every_rule_example_is_decided_by_its_own_rule():
    """A rule whose example is caught by an EARLIER rule is shadowed (dead)."""
    bad = []
    for r in fa.RULES:
        if not r["example_model"]:
            continue                                    # anticipatory rule
        got = fa.classify_rule(r["example_brand"], r["example_model"])
        if got != (r["class"], r["id"]):
            bad.append(f"{r['id']}: example {r['example_brand']} | {r['example_model']} -> {got}")
    assert not bad, "\n".join(bad)


def test_mapping_top_and_review_outputs():
    a = fa.Aggregator()
    add = lambda p, tipo, b, m, n: a.add(p, "INSCRIPCION INICIAL IMPORTADO", tipo, b, m, "Física", n)
    add("2026-07", "SEDAN 5 PUERTAS", "BYD", "DOLPHIN MINI EV GS", 30)
    add("2026-08", "SEDAN 5 PUERTAS", "BYD", "DOLPHIN MINI EV GS", 40)
    add("2026-08", "RURAL 5 PUERTAS", "VOLVO", "EX30", 10)
    add("2026-08", "RURAL 5 PUERTAS", "CHERY", "TIGGO 9 NEW 1.5T", 5)   # new, ICE, review brand
    add("2024-01", "SEDAN 4 PUERTAS", "FIAT", "CRONOS DRIVE 1.3 GSE BZ", 100)
    rows = fa.build_models_rows(a, "2026-08")
    dolphin = next(r for r in rows if r["model"] == "DOLPHIN MINI EV GS")
    assert (dolphin["class"], dolphin["rule"], dolphin["units_total"],
            dolphin["first_seen"], dolphin["last_seen"]) == ("BEV", "bev-token", 70, "2026-07", "2026-08")
    cronos = next(r for r in rows if r["brand"] == "FIAT")
    assert cronos["units_last_12m"] == 0 and cronos["rule"] == fa.DEFAULT_RULE
    top = fa.build_top(a, "2026-08")
    assert top["total_registrations"] == 85, top["total_registrations"]
    bev = top["classes"]["BEV"]
    assert bev["units"] == 80 and bev["brands"][0] == {"brand": "BYD", "units": 70, "share_of_class": 0.875}
    assert "ICE" not in top["classes"]
    report = fa.review_report(rows, "2026-08")
    assert "| ⚠️ | CHERY | TIGGO 9 NEW 1.5T |" in report, report
    assert "| ⚠️ | VOLVO" not in report                       # EX30 is BEV, not flagged


def test_body_class():
    bad = [(t, w, fa.body_class(t)) for t, w in BODY_CASES.items()
           if fa.body_class(t) != w]
    assert not bad, bad


def test_aggregator_scope_and_owner_split():
    a = fa.Aggregator()
    a.add("2026-08", "INSCRIPCION INICIAL IMPORTADO", "SEDAN 5 PUERTAS", "BYD", "DOLPHIN MINI EV GS", "Física", 3)
    a.add("2026-08", "INSCRIPCION INICIAL NACIONAL", "RURAL 5 PUERTAS", "TOYOTA", "COROLLA CROSS XEI HEV 1.8 ECVT", "Jurídica", 2)
    a.add("2026-08", "INSCRIPCION INICIAL NACIONAL", "PICK-UP CABINA DOBLE", "TOYOTA", "HILUX 4X4 DC SRX 2.8 TDI 6 AT", "Física", 5)
    # out of scope: classic car, auctioned vehicle, van, quadricycle
    a.add("2026-08", "INSCRIPCION INICIAL AUTO CLASICO", "COUPE", "FORD", "MUSTANG", "Física", 1)
    a.add("2026-08", "INSCRIPCION INICIAL FORM. 05 SUB. SIN CERTIFICADO", "SEDAN 4 PUERTAS", "FIAT", "CRONOS", "Física", 1)
    a.add("2026-08", "INSCRIPCION INICIAL IMPORTADO", "FURGONETA", "RENAULT", "KANGOO E-TECH ELECTRICA", "Jurídica", 4)
    a.add("2026-08", "INSCRIPCION INICIAL NACIONAL", "CUADRICICLO PESADO PASAJ-L7B", "CORADIR", "S2-100", "Física", 1)
    c = a.counts["2026-08"]
    assert c["Whole"]["TOTAL"] == 5 and c["Whole"]["BEV"] == 3 and c["Whole"]["HEV"] == 2, c["Whole"]
    assert c["Private"]["TOTAL"] == 3 and c["Private"]["BEV"] == 3, c["Private"]
    assert c["Industry"]["TOTAL"] == 2 and c["Industry"]["HEV"] == 2, c["Industry"]
    assert c["Pickups"]["TOTAL"] == 5 and c["Pickups"]["ICE"] == 5, c["Pickups"]
    for v in ("Whole", "Private", "Industry", "Pickups"):
        assert sum(c[v][k] for k in fa.FUELS) == c[v]["TOTAL"], v


def test_upsert_is_line_level():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "Argentina.csv"
        foreign = "2017-12,monthly,Whole,hand-entered,1.0,0.0,0.0,0.0,0.0,9.0,10.0,keep me"
        odd = "2018-01,monthly,Whole,DNRPA,0.0,0.0,0.0,5.0,0.0,95.0,100.0,"
        p.write_text(",".join(fa.CSV_COLUMNS) + "\n" + foreign + "\n" + odd + "\n", encoding="utf-8")
        counts = {k: 0 for k in fa.FUELS + ["TOTAL"]}
        counts.update(HEV=6, ICE=95, TOTAL=101)
        new_jan = fa.render_line("2018-01", "Whole", counts)
        new_feb = fa.render_line("2018-02", "Whole", counts)
        new_dec = fa.render_line("2017-12", "Whole", counts)
        stats = fa.upsert_lines(p, {("2018-02", "Whole"): new_feb,
                                    ("2018-01", "Whole"): new_jan,
                                    ("2017-12", "Whole"): new_dec}, force=False)
        assert stats == {"added": 1, "updated": 1, "unchanged": 0, "skipped": 1}, stats
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[1] == foreign, "a foreign-source row must never be rewritten"
        assert lines[2] == new_jan and lines[3] == new_feb, lines
        # idempotent: re-running with the same numbers touches nothing
        before = p.read_bytes()
        stats = fa.upsert_lines(p, {("2018-01", "Whole"): new_jan}, force=False)
        assert stats["unchanged"] == 1 and p.read_bytes() == before


def test_incomplete_month_guard():
    have = {f"2026-{m:02d}": {"TOTAL": "30000.0"} for m in range(1, 13)}
    assert fa.looks_incomplete("2027-01", 5000, have)
    assert not fa.looks_incomplete("2027-01", 20000, have)
    assert not fa.looks_incomplete("2027-01", 5000, {"2026-12": {"TOTAL": "30000.0"}})


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
