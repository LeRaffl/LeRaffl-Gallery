#!/usr/bin/env python3
"""Regression tests for the UNRAE LCV (Vans) parser in fetch_italy.py.

Run with plain Python, no test framework and no network:

    python scripts/test_fetch_italy.py

The fixture is pdftotext -layout output of the June 2026 LCV Comunicato
Stampa (released 2026-07), trimmed to the total and motorizzazioni paragraphs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fetch_italy as fi  # noqa: E402

JUNE_2026 = """\
d’arresto, evidenziando una flessione a doppia cifra. Le immatricolazioni si posizionano
infatti a 17.108 unità, registrando un calo del 12,1% rispetto alle 19.453 dello stesso mese
del 2025 (quando il mercato aveva già ceduto il 5,9%). L’andamento negativo del mese
impatta sul bilancio del primo semestre del 2026, che archivia una flessione del 4,3% e un
totale di 94.759 unità immatricolate, contro le 99.026 del gennaio-giugno dello scorso anno.
   Sul fronte delle motorizzazioni, a giugno il diesel, con una contrazione in volume inferiore
al mercato complessivo, recupera 3,7 punti e sale al 80,6% di quota (78,4% nel cumulato, -2,3
p.p.). Il motore a benzina nel mese cede 0,7 punti, fermandosi al 3,1% (3,5 nei 6 mesi, -0,4 p.p.).
Il Gpl scende all’1,6% (2,2% in gennaio-giugno), i veicoli plug-in raddoppiano in quota
passando dall’1,0% di un anno fa al 2,1% di giugno (2,3% nei 6 mesi). I veicoli BEV, come
anticipato, a giugno scendono al 3,9% (-3,5 p.p.) e nel cumulato passano dal 4,3% di un anno fa
al 3,2% attuale, mentre i veicoli ibridi guadagnano 0,6 punti e coprono l’8,8% del totale nel
mese (10,4% in gennaio-giugno).
"""


def test_june_2026_shares() -> None:
    cols = fi.parse_vans(JUNE_2026)
    total = 17108
    assert cols["TOTAL"] == total, cols
    expect = {"DIESEL": 80.6, "PETROL": 3.1, "OTHERS": 1.6,
              "PHEV": 2.1, "BEV": 3.9, "HEV": 8.8}
    for k, pct in expect.items():
        assert cols[k] == round(pct / 100 * total), (k, cols[k], pct)
    fi.sanity_check(cols, "2026-06", strict=False)


def test_all_apostrophe_needs_word_boundary() -> None:
    # "dall’1,0% di un anno fa" is the year-ago share, not the month's.
    text = "i veicoli plug-in passano dall’1,0% di un anno fa al 2,1% di giugno."
    hit = fi._LCV_PCT["PHEV"].search(text)
    assert hit and hit.group(1) == "2,1", hit and hit.group(1)
    text = "Il Gpl scende all’1,6% (2,2% in gennaio-giugno)."
    assert fi._LCV_PCT["GPL"].search(text).group(1) == "1,6"


def test_slug_months() -> None:
    base = "https://unrae.it/sala-stampa/veicoli-commerciali"
    assert fi.slug_months(
        f"{base}/7718/veicoli-commerciali-leggeri-a-giugno-121-sul-2025-e-173-sul-2024"
    ) == [6]
    # The July+August 2026 release: fuel shares only cumulative -> skipped.
    assert fi.slug_months(
        f"{base}/7776/veicoli-commerciali-leggeri-luglio-flette-del-10-"
        "agosto-in-recupero-grazie-agli-incentivi-46"
    ) == [7, 8]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"ok  {t.__name__}")
    print(f"{len(tests)} passed")
