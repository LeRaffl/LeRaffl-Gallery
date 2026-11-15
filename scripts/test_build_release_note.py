#!/usr/bin/env python3
"""The monthly note keeps marked sentences and a short data half. No network."""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_release_note as brn

checks = []


def check(name, ok):
    checks.append((name, ok))
    print(("PASS " if ok else "FAIL ") + name)


check("uses the calendar month", brn.stand_month(__import__("datetime").date(2026, 11, 30)) == "2026-11")
check("explicit month wins", brn.stand_month(__import__("datetime").date(2026, 11, 15), "2026-09") == "2026-09")

bodies = ["Release: France Whole is now the registry series.\n\nAlso a delimiter fix.", "no marker here", "Release: "]
lines = brn.release_lines(bodies)
check("keeps a marked sentence", lines == ["France Whole is now the registry series."])

with tempfile.TemporaryDirectory() as tmp:
    data = pathlib.Path(tmp)
    (data / "Germany.csv").write_text("period,BEV\n2026-10,1\n2026-09,1\n", encoding="utf-8")
    (data / "Germany_Buses.csv").write_text("period,BEV\n2020-01,1\n", encoding="utf-8")
    (data / "Albania.csv").write_text("period,BEV\n2026-06,1\n", encoding="utf-8")
    latest = brn.latest_periods(data)
    check("variant file is not a series", set(latest) == {"Germany", "Albania"})
    check("latest period wins", latest["Germany"] == "2026-10")
    half = brn.data_half(latest)
    check("data half names the lead and the laggard", "1 series through 2026-10" in half and "Albania 2026-06" in half)

note = brn.render_note("2026-11", lines, "1 series through 2026-10.", ["#1 A chevron"])
check("note leads with the tag", note.startswith("## v2026-11"))
check("appendix is collapsed", "<details>" in note and "A chevron" in note)
check("empty month says so", "No reading changes were marked" in brn.render_note("2026-11", [], "x.", []))
cff = brn.citation("v2026.11", "2026-12-01")
check("citation names the tag", "version: v2026.11" in cff and "not the moving branch" in cff)

bad = [n for n, ok in checks if not ok]
print(f"{len(checks) - len(bad)}/{len(checks)} passed")
sys.exit(1 if bad else 0)
