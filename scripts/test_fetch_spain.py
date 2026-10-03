#!/usr/bin/env python3
"""Regression tests for the daily-file fallback in scripts/fetch_spain.py
(no network).

Run:  python scripts/test_fetch_spain.py

Before DGT publishes a month's consolidated file (around the 15th), the
fetcher sums that month's daily files into a provisional row. The failure
modes are quiet: a half-published month written as complete, a provisional
row overwriting the monthly one, or a monthly row never replacing the
provisional one. These cases pin the "is the month complete?" rule (weekdays
minus national holidays), the banner handling when files are concatenated,
the overwrite order between the two sources, and the top-list provenance.
"""
import io
import sys
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_spain as fs  # noqa: E402


def _record(day: str, tipo="40", nu="N", cat="BEV", prop="2"):
    rec = [" "] * fs.RECORD_LEN

    def put(name, val):
        a, b = fs._slice(name)
        rec[a:b] = list(val.ljust(b - a)[: b - a])
    put("FEC_MATRICULA", day)
    put("COD_TIPO", tipo)
    put("IND_NUEVO_USADO", nu)
    put("CATEGORIA_VEHICULO_ELECTRICO", cat)
    put("COD_PROPULSION_ITV", prop)
    put("CLAVE_TRAMITE", "1")
    return "".join(rec)


def _zip(txt: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("export_mat.txt", txt.encode("latin-1"))
    return buf.getvalue()


class _Resp:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


class _Session:
    """Serves daily zips for the given days, 404 for everything else."""
    def __init__(self, files: dict[str, str]):
        self.files, self.urls = files, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        ymd = url.rsplit("_", 1)[-1].removesuffix(".zip")
        if ymd in self.files:
            return _Resp(200, _zip(self.files[ymd]))
        return _Resp(404, b"<html>404</html>")


def test_easter_and_holidays():
    assert fs.easter(2026) == date(2026, 4, 5)
    assert fs.easter(2027) == date(2027, 3, 28)
    hol = fs.national_holidays(2026)
    assert date(2026, 4, 3) in hol                     # Viernes Santo
    assert date(2026, 10, 12) in hol and date(2026, 12, 8) in hol


def test_expected_daily_files():
    oct26 = fs.expected_daily_files("2026-10")
    assert date(2026, 10, 12) not in oct26              # Fiesta Nacional (Mon)
    assert date(2026, 10, 3) not in oct26               # Saturday
    assert date(2026, 10, 1) in oct26 and date(2026, 10, 30) in oct26
    assert len(oct26) == 21
    sep26 = fs.expected_daily_files("2026-09")
    assert len(sep26) == 22 and sep26[-1] == date(2026, 9, 30)


def test_strip_banner():
    banner = b"Vehiculos matriculados. Letras ...\r\n"
    assert fs.strip_banner(banner + b"0109x\r\n") == b"0109x\r\n"
    assert fs.strip_banner(b"0109x") == b"0109x\n"      # newline appended
    assert fs.strip_banner(b"Banner only") == b""
    assert fs.strip_banner(b"") == b""


def _september(drop: str | None = None) -> dict[str, str]:
    files = {}
    for d in fs.expected_daily_files("2026-09"):
        if d.strftime("%Y%m%d") == drop:
            continue
        files[d.strftime("%Y%m%d")] = (
            "Vehiculos matriculados. Banner\r\n"
            + _record(d.strftime("%d%m%Y")) + "\r\n"
            + _record(d.strftime("%d%m%Y"), cat="HEV", prop="0") + "\r\n")
    # a Saturday file with one trailer record: summed, never required
    files["20260919"] = _record("19092026", tipo="R1") + "\r\n"
    return files


def test_download_daily_month_complete():
    s = _Session(_september())
    txt, note = fs.download_daily_month(s, "2026-09")
    assert len(s.urls) == 30
    assert "/2026/9/vehiculos/matriculaciones/export_mat_20260901.zip" in s.urls[0]
    # ×50 clears aggregate()'s 2,000-car corruption guard
    counts = fs.aggregate(txt * 50, "2026-09", ["Whole"])
    assert counts["Whole"]["BEV"] == counts["Whole"]["HEV"] == 22 * 50
    assert counts["Whole"]["TOTAL"] == 44 * 50          # trailer not in Whole
    assert "sum of 23 DGT daily files" in note
    assert "export_mat_20260901..20260930" in note


def test_download_daily_month_incomplete():
    s = _Session(_september(drop="20260930"))
    try:
        fs.download_daily_month(s, "2026-09")
        raise AssertionError("a missing weekday file must raise NotPublished")
    except fs.NotPublished as e:
        assert "2026-09-30" in str(e)


def _counts(bev):
    c = {k: 0 for k in fs.FUEL_COLUMNS}
    c["BEV"] = bev
    c["TOTAL"] = bev
    return c


def test_upsert_order():
    rows = []
    assert fs.upsert(rows, "2026-09", "Whole", _counts(10), "n1", False,
                     fs.SOURCE_DAILY) == "added"
    assert rows[0]["source"] == "DGT (daily)"
    assert fs.upsert(rows, "2026-09", "Whole", _counts(10), "n1", False,
                     fs.SOURCE_DAILY) == "unchanged"
    # a late weekend file changes the note: rewritten, still provisional
    assert fs.upsert(rows, "2026-09", "Whole", _counts(10), "n2", False,
                     fs.SOURCE_DAILY) == "updated"
    # the monthly file replaces the provisional row even with equal counts
    assert fs.upsert(rows, "2026-09", "Whole", _counts(10), "url", False) == "updated"
    assert rows[0]["source"] == "DGT" and rows[0]["notes"] == "url"
    # …and a provisional row never replaces a monthly one
    assert fs.upsert(rows, "2026-09", "Whole", _counts(11), "n3", False,
                     fs.SOURCE_DAILY) == "skipped"
    assert rows[0]["BEV"] == "10.0"
    # blended/legacy rows stay protected from the daily path too
    legacy = [{"period": "2015-01", "variant": "Whole", "source": "Blend"}]
    assert fs.upsert(legacy, "2015-01", "Whole", _counts(1), "n", False,
                     fs.SOURCE_DAILY) == "skipped"


def test_latest_dgt_row():
    rows = [{"period": "2026-08", "variant": "Whole", "source": "DGT"},
            {"period": "2026-09", "variant": "Whole", "source": "DGT (daily)"},
            {"period": "2026-09", "variant": "Rental", "source": "DGT"},
            {"period": "2026-10", "variant": "Whole", "source": "ACEA"}]
    assert fs.latest_dgt_row(rows)["source"] == "DGT (daily)"
    assert fs.latest_dgt_period(rows) == "2026-09"
    assert fs.latest_dgt_row([]) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
