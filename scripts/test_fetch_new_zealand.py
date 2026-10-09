#!/usr/bin/env python3
"""Regression tests for scripts/fetch_new_zealand.py (no network).

Run:  python scripts/test_fetch_new_zealand.py

The register's failure modes are quiet: a new MOTIVE_POWER label, a refresh
that has not landed yet, a month counted twice, a scope filter that drifts.
These cases pin every label of MOTIVE_MAP (and look-alikes that must not
map), the scope clause, the unknown-label guard, the snapshot-date guard,
the plausibility guard, the line-level upsert (foreign rows are kept), the
self-throttle and the brand / model summary.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_new_zealand as nz  # noqa: E402

LABEL_CASES = {
    "ELECTRIC": "BEV",
    "PLUGIN PETROL HYBRID": "PHEV", "PLUGIN DIESEL HYBRID": "PHEV",
    "ELECTRIC [PETROL EXTENDED]": "PHEV", "ELECTRIC [DIESEL EXTENDED]": "PHEV",
    "PETROL HYBRID": "HEV", "PETROL ELECTRIC HYBRID": "HEV",
    "DIESEL HYBRID": "HEV", "DIESEL ELECTRIC HYBRID": "HEV",
    "PETROL": "PETROL", "DIESEL": "DIESEL",
    "LPG": "OTHERS", "CNG": "OTHERS", "OTHER": "OTHERS",
    "ELECTRIC FUEL CELL HYDROGEN": "OTHERS",
    "PLUG IN FUEL CELL HYDROGEN HYBRID": "OTHERS",
    None: "OTHERS", "": "OTHERS",
    " plugin  petrol hybrid ": "PHEV",        # register strings are free text
}
NOT_MAPPED = ["ELECTRIC HYBRID", "HYDROGEN", "PETROL/LPG", "ELECTRIC [HYDROGEN EXTENDED]"]

HEADER = ",".join(nz.CSV_COLUMNS)
LEGACY = [
    "2025-09,monthly,Whole,transport.govt.nz & Prof. Ray Willis,814.0,606.0,8152.0,7738.0,3444.0,0.0,20754.0,",
    "2026-08,monthly,Whole,transport.govt.nz & Prof. Ray Willis,1485,1389,8200,7309,3127,,21510,",
]

failures = 0


def check(name, got, want):
    global failures
    if got != want:
        failures += 1
        print(f"FAIL {name}: got {got!r}, want {want!r}")


def raises(name, fn, *a, **kw):
    global failures
    try:
        fn(*a, **kw)
    except RuntimeError:
        return
    failures += 1
    print(f"FAIL {name}: no RuntimeError")


def row(p, status, power, n):
    y, m = p.split("-")
    return {nz.F_YEAR: int(y), nz.F_MONTH: int(m), "IMPORT_STATUS": status,
            "MOTIVE_POWER": power, "n": n}


def mrow(p, power, make, model, n):
    y, m = p.split("-")
    return {nz.F_YEAR: int(y), nz.F_MONTH: int(m), "MOTIVE_POWER": power,
            "MAKE": make, "MODEL": model, "n": n}


# September 2026 as the register returned it on 2026-10-09 (new + used, MA/MB/MC/NA)
SEP = [row("2026-09", "NEW", "ELECTRIC", 2661), row("2026-09", "USED", "ELECTRIC", 305),
       row("2026-09", "NEW", "PLUGIN PETROL HYBRID", 1450), row("2026-09", "NEW", "ELECTRIC [PETROL EXTENDED]", 51),
       row("2026-09", "USED", "PLUGIN PETROL HYBRID", 101),
       row("2026-09", "NEW", "PETROL HYBRID", 4500), row("2026-09", "NEW", "DIESEL HYBRID", 930),
       row("2026-09", "USED", "PETROL HYBRID", 4235),
       row("2026-09", "NEW", "PETROL", 4023), row("2026-09", "USED", "PETROL", 3396),
       row("2026-09", "NEW", "DIESEL", 2735), row("2026-09", "USED", "DIESEL", 334)]
SEP_COUNTS = {"BEV": 2966, "PHEV": 1602, "HEV": 9665, "PETROL": 7419, "DIESEL": 3069,
              "OTHERS": 0, "TOTAL": 24721}


def data(fuel=SEP, models=(), loaded="2026-10-06"):
    return {"service": "test", "loaded": loaded, "fuel": list(fuel), "models": list(models)}


def run(tmp, d, *extra, csv_lines=LEGACY, today="2026-10-09"):
    csv = Path(tmp) / "nz.csv"
    if not csv.exists():
        csv.write_text("\n".join([HEADER] + list(csv_lines)) + "\n", encoding="utf-8")
    src = Path(tmp) / "in.json"
    src.write_text(json.dumps(d), encoding="utf-8")
    out = Path(tmp) / "out.txt"
    out.write_text("")
    nz.main(["--csv", str(csv), "--from-json", str(src), "--no-top", "--today", today,
             "--github-output", str(out), "--summary", str(Path(tmp) / "sum.md"), *extra])
    return csv.read_text(encoding="utf-8"), out.read_text()


# ── mapping ──
for label, col in LABEL_CASES.items():
    check(f"label {label!r}", nz.column_of(label), col)
for label in NOT_MAPPED:
    check(f"look-alike {label!r}", nz.column_of(label), None)

# ── scope clause ──
w = nz.scope_where("2025-10", "2026-09")
check("scope months", "BETWEEN 202510 AND 202609" in w, True)
check("scope status", "IMPORT_STATUS IN ('NEW','USED')" in w, True)
check("scope class", "CLASS IN ('MA','MB','MC','NA')" in w, True)

# ── counting ──
counts, unknown, status = nz.count_months(SEP)
check("Sep counts", counts["2026-09"], SEP_COUNTS)
check("Sep status", status["2026-09"], {"NEW": 16350, "USED": 8371})
check("no unknown", unknown, {})
c2, u2, _ = nz.count_months(SEP + [row("2026-09", "NEW", "HYDROGEN", 10)])
check("unknown -> OTHERS", c2["2026-09"]["OTHERS"], 10)
check("unknown listed", u2, {"2026-09": {"HYDROGEN": 10}})
check("small unknown warns", bool(nz.check_unknown("2026-09", u2, 24731)), True)
_, u3, _ = nz.count_months(SEP + [row("2026-09", "NEW", "HYDROGEN", 400)])
raises("large unknown aborts", nz.check_unknown, "2026-09", u3, 25121)

# ── month helpers ──
check("shift back", nz.shift_month("2026-01", -1), "2025-12")
check("shift fwd", nz.shift_month("2025-12", 13), "2027-01")
check("month end", str(nz.month_end("2026-12")), "2027-01-01")
check("default period", nz.default_period(nz.date(2026, 1, 5)), "2025-12")

# ── fetch → CSV ──
with tempfile.TemporaryDirectory() as tmp:
    text, out = run(tmp, data())
    check("Sep row appended", text.splitlines()[-1],
          "2026-09,monthly,Whole,NZTA Motor Vehicle Register,2966,1602,9665,7419,3069,0,24721,")
    check("legacy rows byte-identical", text.splitlines()[1:3], LEGACY)
    check("changed output", "changed=true" in out and '["Whole"]' in out, True)
    # second run: same month -> unchanged
    text2, out2 = run(tmp, data())
    check("idempotent", text2, text)
    check("unchanged output", "changed=false" in out2, True)

with tempfile.TemporaryDirectory() as tmp:
    # a foreign (legacy) row for the month is kept without --force …
    aug = [dict(r, **{nz.F_MONTH: 8}) for r in SEP]
    text, _ = run(tmp, data(aug + SEP), "--period", "2026-08")
    check("foreign row kept", LEGACY[1] in text, True)
    # … and replaced with it
    text, _ = run(tmp, data(aug + SEP), "--period", "2026-08", "--force")
    check("foreign row replaced", LEGACY[1] in text, False)

with tempfile.TemporaryDirectory() as tmp:
    # snapshot not yet covering the month: no-op before the 20th, error after
    text, out = run(tmp, data(loaded="2026-09-30"))
    check("not yet refreshed", "2026-09,monthly" in text, False)
    check("not yet -> unchanged", "changed=false" in out, True)
with tempfile.TemporaryDirectory() as tmp:
    raises("stale register", run, tmp, data(loaded="2026-09-30"), today="2026-10-21")

with tempfile.TemporaryDirectory() as tmp:
    # plausibility: ×10 the same month a year earlier stops the run
    big = [dict(r, n=r["n"] * 10) for r in SEP]
    legacy_sep = ["2025-09,monthly,Whole,x,1,1,1,1,1,0,24000,"]
    raises("plausibility", run, tmp, data(big), csv_lines=legacy_sep)
with tempfile.TemporaryDirectory() as tmp:
    text, _ = run(tmp, data([dict(r, n=r["n"] * 10) for r in SEP]), "--force",
                  csv_lines=["2025-09,monthly,Whole,x,1,1,1,1,1,0,24000,"])
    check("plausibility skipped with force", "2026-09,monthly" in text, True)

with tempfile.TemporaryDirectory() as tmp:
    # self-throttle: month present and --no-top -> no input needed at all
    csv = Path(tmp) / "nz.csv"
    csv.write_text("\n".join([HEADER, "2026-09,monthly,Whole,x,1,1,1,1,1,0,5,"]) + "\n")
    nz.main(["--csv", str(csv), "--no-top", "--today", "2026-10-09"])   # no network: must not query
    check("throttle", True, True)

with tempfile.TemporaryDirectory() as tmp:
    # a backfill flags older months as snapshot undercounts
    jul = [dict(r, **{nz.F_MONTH: 7}) for r in SEP]
    text, _ = run(tmp, data(jul + SEP), "--since", "2026-07", csv_lines=[])
    jul_line = [l for l in text.splitlines() if l.startswith("2026-07")][0]
    check("backfill note", "undercount" in jul_line, False)       # target-2 is still fresh

with tempfile.TemporaryDirectory() as tmp:
    may = [dict(r, **{nz.F_MONTH: 5}) for r in SEP]
    text, _ = run(tmp, data(may + SEP), "--since", "2026-05", csv_lines=[])
    may_line = [l for l in text.splitlines() if l.startswith("2026-05")][0]
    check("old month flagged", "undercount" in may_line, True)

# ── brand / model summary ──
MODELS = [mrow("2026-09", "ELECTRIC", "TESLA", "MODEL Y", 500),
          mrow("2026-09", "ELECTRIC", "BYD", "BYD ATTO 3", 200),
          mrow("2026-09", "ELECTRIC", "byd", "Atto 3", 50),
          mrow("2026-09", "ELECTRIC [PETROL EXTENDED]", "LEAPMOTOR", "C10", 40),
          mrow("2026-09", "PETROL HYBRID", "TOYOTA", "AQUA", 900),
          mrow("2026-09", "PETROL", "TOYOTA", "HILUX", 999)]          # ICE never ranked
units = nz.month_units(MODELS)["2026-09"]
check("brand prefix stripped + case folded", units[("BEV", "BYD", "ATTO 3")], 250)
check("EREV ranked as PHEV", units[("PHEV", "LEAPMOTOR", "C10")], 40)
check("ICE not ranked", any(k[0] == "PETROL" for k in units), False)
top = nz.build_top(data(SEP, MODELS), "2026-09")
check("top total", top["total_registrations"], 24721)
check("top BEV leader", top["classes"]["BEV"]["brands"][0]["brand"], "TESLA")
check("top window", top["window"], {"from": "2026-09", "to": "2026-09", "months": 1})

print(f"{failures} failure(s)" if failures else "all New Zealand fetcher tests passed")
sys.exit(1 if failures else 0)
