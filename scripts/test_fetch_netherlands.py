#!/usr/bin/env python3
"""Offline tests for the Netherlands Swing fetcher (relay POST, SPA open flow).
No network.

    python scripts/test_fetch_netherlands.py
"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_netherlands as fn  # noqa: E402


class FakeResp:
    def __init__(self, status=200, text="", payload=None, headers=None):
        self.status_code = status
        self.text = text if payload is None else json.dumps(payload)
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload if self._payload is not None else json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RelaySession:
    """Stands in for requests.Session behind the relay: records what is sent."""
    relay_base = "https://relay.example/fetch?url="
    relay_token = "tok"

    def __init__(self):
        self.relay_cookies = {}
        self.sent = []

    def post(self, url, headers=None, data=None, **kw):
        self.sent.append(("POST", url, headers, data))
        blob = base64.b64encode(b"swing_token=abc; path=/\nx=1; path=/").decode()
        return FakeResp(200, payload={"ok": True}, headers={"X-Upstream-Set-Cookie-B64": blob})

    def get(self, url, headers=None, **kw):
        self.sent.append(("GET", url, headers, None))
        return FakeResp(200, "html")


def test_post_json_through_the_relay():
    s = RelaySession()
    s.relay_cookies = {"c": "1"}
    r = fn._post_json(s, "https://duurzamemobiliteit.databank.nl/viewer/api/x",
                      {"entries": {"workspace_guid": "T"}},
                      {"X-Page-Type": "Index", "__RequestVerificationToken": "TOK",
                       "Origin": "https://o", "Referer": "https://ref"})
    method, url, hdrs, body = s.sent[0]
    assert method == "POST" and url.startswith("https://relay.example/fetch?url=https%3A%2F%2Fduurzame")
    assert json.loads(body) == {"entries": {"workspace_guid": "T"}}
    # the relay contract: extra headers travel as X-Fwd-*, cookies as X-Fwd-Cookie
    assert hdrs["X-Fwd-Content-Type"] == "application/json"
    assert hdrs["X-Fwd-Accept"].startswith("application/json")
    assert hdrs["X-Fwd-Page-Type"] == "Index" and hdrs["X-Fwd-Antiforgery"] == "TOK"
    assert hdrs["X-Fwd-Origin"] == "https://o" and hdrs["X-Fwd-Referer"] == "https://ref"
    assert hdrs["X-Fwd-Cookie"] == "c=1" and hdrs["X-Relay-Token"] == "tok"
    # upstream Set-Cookie of the POST answer lands in the jar for the next call
    assert s.relay_cookies["swing_token"] == "abc" and s.relay_cookies["x"] == "1"
    assert r.json() == {"ok": True}
    # an empty token is not forwarded
    s2 = RelaySession()
    fn._post_json(s2, "https://duurzamemobiliteit.databank.nl/a", {}, {"__RequestVerificationToken": ""})
    assert "X-Fwd-Antiforgery" not in s2.sent[0][2]


def test_swing_token_and_open_flow():
    html = ('<html data-page-type="Index" lang="nl"><script>Globals.workspaceId = '
            '"11111111-2222-3333-4444-555555555555";</script>'
            '<input name="__RequestVerificationToken" type="hidden" value="CfDJ8_abc" /></html>')
    assert fn.swing_token(html) == "CfDJ8_abc" and fn.swing_token("<html></html>") == ""
    calls = []

    def fake_get(session, url, headers=None, **kw):
        calls.append(("GET", url))
        if "/presentation/" in url:
            return FakeResp(200, payload={"title": "T", "table": {"rows": [], "columnHeaderRows": []}})
        return FakeResp(200, html)

    def fake_post(session, url, payload, headers=None, **kw):
        calls.append(("POST", url, payload, headers))
        return FakeResp(200, payload={"presentationID": "PID", "isValid": True})
    real = fn._get, fn._post_json
    fn._get, fn._post_json = fake_get, fake_post
    try:
        p = fn.open_presentation(None, "Whole")
        assert p["title"] == "T"
        assert calls[0][1] == f"{fn.BASE}/viewer?workspace_guid={fn.TEMPLATES['Whole']}"
        kind, url, payload, hdrs = calls[1]
        assert url == f"{fn.BASE}/viewer/api/workspace/11111111-2222-3333-4444-555555555555/presentationfromurl"
        assert payload == {"entries": {"workspace_guid": fn.TEMPLATES["Whole"]}}
        assert hdrs["X-Page-Type"] == "Index" and hdrs["__RequestVerificationToken"] == "CfDJ8_abc"
        assert calls[2][1].endswith("/presentation/PID")
        # a workspace the server does not know comes back invalid: a clear error, not a parse crash
        fn._post_json = lambda *a, **k: FakeResp(200, payload={"isValid": False, "presentationID": ""})
        try:
            fn.open_presentation(None, "Whole")
            raise AssertionError("an invalid presentation must raise")
        except RuntimeError as e:
            assert "re-save" in str(e)
        # the page no longer defining the session workspace is reported as a layout change
        fn._get = lambda *a, **k: FakeResp(200, "<html>Startpagina</html>")
        try:
            fn.open_presentation(None, "Whole")
            raise AssertionError("a page without Globals.workspaceId must raise")
        except RuntimeError as e:
            assert "workspaceId" in str(e)
    finally:
        fn._get, fn._post_json = real


def _cell(text, **kw):
    return {"text": text, "type": 0, "valueType": 2, "headers": "", **kw}


def _whole_presentation():
    """The shape the SPA returned for the Whole workspace on 2026-09-28 (four
    months of it plus the last one, values as printed)."""
    head = {"cells": [{"text": "Maand", "type": 5, "valueType": 3}] + [
        {"colSpan": 1, "text": f, "type": 1, "valueType": 3, "headers": ""}
        for f in ("BEV", "FCEV", "PHEV", "Benzine", "Diesel", "Overig")]}

    def row(label, *vals):
        return {"cells": [{"rowSpan": 1, "text": label, "type": 2, "valueType": 3}]
                + [_cell(v) for v in vals]}
    rows = [row("30 september 2023", "10.075", "", "3.574", "15.301", "27", "218"),
            row("31 oktober 2023", "8.062", "", "3.374", "15.979", "76", "198"),
            row("31 augustus 2026", "12.764", "", "4.748", "8.102", "22", "154"),
            row("30 september 2026", "", "", "", "", "", "")]      # pre-filled future month
    return {"title": "Instroom Personenauto Nieuw - Nederland",
            "table": {"colCount": 6, "rowCount": 4, "headColCount": 1, "headRowCount": 1,
                      "rows": rows, "columnHeaderRows": [head]}}


def test_whole_presentation_parses_like_the_old_pivot():
    data = fn.swing_table_to_legacy(_whole_presentation())
    assert data["caption"].startswith("Instroom Personenauto") and data["totalRows"] == 4
    assert [c["d"] for c in data["headCols"][0]] == ["BEV", "FCEV", "PHEV", "Benzine", "Diesel", "Overig"]
    assert data["headRows"][2][0]["d"] == "31 augustus 2026"
    assert data["rowData"][0][0]["d"] == "10.075" and data["rowData"][0][1]["d"] == ""
    parsed = fn.parse_table(data, "Whole")
    assert sorted(parsed) == ["2023-09", "2023-10", "2026-08", "2026-09"]
    assert parsed["2023-09"] == {"BEV": 10075.0, "FCEV": 0.0, "PHEV": 3574.0,
                                 "Benzine": 15301.0, "Diesel": 27.0, "Overig": 218.0}
    rows = fn.to_csv_rows(parsed, "Whole")
    assert "2026-09" not in rows                      # all-zero future month is skipped
    r = rows["2026-08"]
    assert (r["BEV"], r["PHEV"], r["PETROL"], r["DIESEL"], r["OTHERS"]) == (12764.0, 4748.0, 8102.0, 22.0, 154.0)
    assert r["TOTAL"] == 12764 + 4748 + 8102 + 22 + 154 and r["HEV"] == "" and r["source"] == fn.SOURCE


def _used_presentation(with_continuation_cells=True):
    """Used as the SPA sends it (2026-09-28): fuels on the outer header level,
    each colSpan 2 and followed by an empty type-4 continuation cell."""
    def h(text, span=1, **kw):
        return {"colSpan": span, "text": text, "type": 1, "valueType": 3, **kw}
    corner = {"text": "", "type": 5, "valueType": 3}
    cont = {"text": "", "type": 4, "valueType": 3}
    outer = [corner]
    for f in ("BEV", "PHEV", "Benzine"):
        outer += [h(f, 2)] + ([cont] if with_continuation_cells else [])
    inner = [{"text": "Maand", "type": 5, "valueType": 3}] + [
        h(x) for x in ("Occasion import > 90 dgn", "Occasion import <= 90 dgn") * 3]
    row = {"cells": [{"rowSpan": 1, "text": "31 juli 2026", "type": 2, "valueType": 3}]
           + [_cell(v) for v in ("1.000", "10", "200", "5", "3.000", "30")]}
    return {"title": "Occasion import", "table": {
        "colCount": 6, "rowCount": 1, "headColCount": 1, "headRowCount": 2,
        "rows": [row], "columnHeaderRows": [{"cells": outer}, {"cells": inner}]}}


def test_two_level_header_sums_sub_columns():
    """Used: the outer level's continuation cells must not be added a second time
    (that slid every fuel two columns to the right on the first try)."""
    for explicit in (True, False):
        data = fn.swing_table_to_legacy(_used_presentation(explicit))
        assert [c["d"] for c in data["headCols"][0]] == ["BEV", "", "PHEV", "", "Benzine", ""]
        assert fn.parse_table(data, "Used")["2026-07"] == {"BEV": 1010.0, "PHEV": 205.0, "Benzine": 3030.0}


def test_payload_shape_changes_are_errors_not_shifted_data():
    pres = _used_presentation()
    pres["table"]["rows"][0]["cells"].pop()             # one value cell missing
    try:
        fn.swing_table_to_legacy(pres)
        raise AssertionError("a short row must raise")
    except RuntimeError as e:
        assert "declares 6" in str(e)
    pres = _used_presentation()
    pres["table"]["columnHeaderRows"][0]["cells"].pop()
    pres["table"]["columnHeaderRows"][0]["cells"].pop()
    pres["table"]["columnHeaderRows"][0]["cells"].pop()  # neither shape adds up to 6 columns
    try:
        fn.swing_table_to_legacy(pres)
        raise AssertionError("a header that does not add up must raise")
    except RuntimeError as e:
        assert "header level" in str(e)


def test_dry_run_report(capsys=None):
    import io
    import tempfile
    from contextlib import redirect_stdout
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "n.csv"
        path.write_text(
            "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,FLEXFUEL,OTHERS,TOTAL,notes\n"
            "2026-06,monthly,Whole,S,16907.0,7571.0,,13107.0,19.0,,158.0,37762.0,\n"
            "2026-07,monthly,Whole,S,1.0,1.0,,1.0,1.0,,1.0,5.0,\n", encoding="utf-8")
        rows = {
            "2026-06": {"BEV": 16907.0, "PHEV": 7571.0, "PETROL": 13107.0, "DIESEL": 19.0, "OTHERS": 158.0, "TOTAL": 37762.0},
            "2026-07": {"BEV": 9.0, "PHEV": 1.0, "PETROL": 1.0, "DIESEL": 1.0, "OTHERS": 1.0, "TOTAL": 13.0},
            "2026-08": {"BEV": 12764.0, "PHEV": 4748.0, "PETROL": 8102.0, "DIESEL": 22.0, "OTHERS": 154.0, "TOTAL": 25790.0}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            fn.dry_run_report(str(path), rows, "Whole")
    out = buf.getvalue()
    assert "CHANGED 2026-07: BEV 1->9, TOTAL 5->13" in out
    assert "NEW     2026-08" in out and "2026-06" not in out.replace("dry run", "")
    assert "1 months identical" in out and "1 new, 1 changed" in out


def test_main_end_to_end_writes_the_csvs():
    """main() with a stubbed portal: Whole and Used land in their CSVs with the
    right columns, an existing month is updated in place, all-zero future months
    are skipped, and --dry-run touches nothing."""
    import csv
    import tempfile
    pres = {"Whole": _whole_presentation(), "Used": _used_presentation()}
    real_fetch, real_paths, real_argv = fn.fetch_table, dict(fn.CSV_PATHS), sys.argv
    real_session = fn.make_swing_session
    with tempfile.TemporaryDirectory() as d:
        fn.CSV_PATHS.update({v: str(Path(d) / f"{v}.csv") for v in fn.CSV_PATHS})
        Path(fn.CSV_PATHS["Whole"]).write_text(
            "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,FLEXFUEL,OTHERS,TOTAL,notes\n"
            "2023-09,monthly,Whole,old,1.0,1.0,,1.0,1.0,,1.0,5.0,keep-me\n", encoding="utf-8")
        fn.fetch_table = lambda variant, session: fn.swing_table_to_legacy(pres[variant])
        fn.make_swing_session = lambda: None
        try:
            sys.argv = ["x", "--variant", "whole", "--force", "--no-top", "--dry-run"]
            fn.main()
            assert "old" in Path(fn.CSV_PATHS["Whole"]).read_text(encoding="utf-8")   # untouched
            sys.argv = ["x", "--variant", "all", "--force", "--no-top"]
            pres["HDV"] = _whole_presentation()
            fn.main()
        finally:
            fn.fetch_table, fn.make_swing_session, sys.argv = real_fetch, real_session, real_argv
            fn.CSV_PATHS.update(real_paths)
        rows = {r["period"]: r for r in csv.DictReader(open(Path(d) / "Whole.csv", encoding="utf-8"))}
        assert sorted(rows) == ["2023-09", "2023-10", "2026-08"]      # future zero month skipped
        r = rows["2023-09"]
        assert (r["BEV"], r["PHEV"], r["PETROL"], r["DIESEL"], r["OTHERS"], r["TOTAL"]) == (
            "10075.0", "3574.0", "15301.0", "27.0", "218.0", "29195.0")
        assert r["source"] == fn.SOURCE and r["HEV"] == ""
        used = {r["period"]: r for r in csv.DictReader(open(Path(d) / "Used.csv", encoding="utf-8"))}
        assert used["2026-07"]["PHEV"] == "205.0" and used["2026-07"]["PETROL"] == "3030.0"


def test_plate_bucket_splits_novc_hev_out_of_petrol():
    """RDW hybrid class is the counted split Swing does not publish.
    OVC-HEV is plug-in, NOVC-HEV is full/mild, campers stay diesel."""
    assert fn.plate_bucket([("Elektriciteit", "")]) == "BEV"
    assert fn.plate_bucket([("Benzine", "OVC-HEV"), ("Elektriciteit", "OVC-HEV")]) == "PHEV"
    assert fn.plate_bucket([("Benzine", "NOVC-HEV"), ("Elektriciteit", "NOVC-HEV")]) == "HEV"
    assert fn.plate_bucket([("Benzine", "")]) == "PETROL"
    assert fn.plate_bucket([("Diesel", "")]) == "DIESEL"
    assert fn.plate_bucket([("Benzine", ""), ("LPG", "")]) == "OTHERS"
    assert fn.plate_bucket([("Elektriciteit", "NOVC-FCHV"), ("Waterstof", "NOVC-FCHV")]) == "OTHERS"
    # RDW files some combustion cars under NOVC-FCHV. No hydrogen, no
    # electricity: not a hybrid, keep the fuel.
    assert fn.plate_bucket([("Diesel", "NOVC-FCHV")]) == "DIESEL"
    assert fn.plate_bucket([("Benzine", "NOVC-FCHV")]) == "PETROL"


def test_enrich_keeps_swing_total_and_refuses_a_negative_residual():
    """HEV and pure petrol come from the register. TOTAL, BEV, PHEV and
    DIESEL stay Swing's — register diesel is mostly campers and would
    make OTHERS negative."""
    swing = {"TOTAL": 24739, "BEV": 9457, "PHEV": 5774, "DIESEL": 16, "OTHERS": 111}
    register = {"HEV": 7263, "PETROL": 1917, "DIESEL": 457, "OTHERS": 111}
    row = fn.enrich_swing(swing, register)
    assert row is not None
    assert row["HEV"] == 7263 and row["PETROL"] == 1917 and row["DIESEL"] == 16
    assert row["TOTAL"] == 24739 and row["BEV"] == 9457 and row["PHEV"] == 5774
    assert row["OTHERS"] == 24739 - 9457 - 5774 - 7263 - 1917 - 16
    assert row["OTHERS"] > 0
    assert "RDW register" in row["notes"] and "still in the country" in row["notes"]
    exported = fn.enrich_swing(swing, register, cohort="with_exports")
    assert exported is not None and "since-exported" in exported["notes"]
    # Register diesel instead of Swing diesel does not add up.
    assert fn.enrich_swing(swing, register, diesel="register") is None


def test_choose_cohort_sticks_to_swing_and_refuses_the_rest():
    """The cohort whose total sticks to Swing, or nothing.

    Stay wins when it is as close as the since-exported cohort. Since-exported
    cars win when they are closer and still inside the band, including when
    stay has drifted past it. Neither match means leave the month blank.
    """
    assert fn.choose_cohort(35529, 35333, 36086) == "stay"          # 2026-09
    assert fn.choose_cohort(29250, 27529, 29145) == "with_exports"  # 2022-06
    assert fn.choose_cohort(40401, 39550, 40504) == "with_exports"  # 2023-06, stay -2.1%
    assert fn.choose_cohort(34668, 34389, 34933) == "with_exports"  # 2024-06, exports closer
    assert fn.choose_cohort(10000, 10100, 9900) == "stay"           # tie: stay
    assert fn.choose_cohort(10000, 9000, 8000) is None              # both past 2%
    assert fn.choose_cohort(0, 100, 100) is None


def test_window_cohort_is_one_choice_for_the_whole_fill():
    """A per-month pick flips the scope inside one series. The window takes
    the cohort that covers more of it, and a tie keeps stay."""
    mixed = [{"choice": "with_exports"}] * 3 + [{"choice": "stay"}]
    assert fn.window_cohort(mixed) == "with_exports"
    assert fn.window_cohort([{"choice": "stay"}, {"choice": "with_exports"}]) == "stay"
    assert fn.window_cohort([{"choice": None}, {"choice": None}]) is None
    assert fn.window_cohort([]) is None


def test_closer_to_acea_absolute_when_totals_agree_relative_when_not():
    """ACEA is the only counted HEV. Absolute when the totals are the same
    month, relative when they are not — September 2026 is the first case."""
    acea = {"TOTAL": 36259, "HEV": 8601}
    stay = {"TOTAL": 35333, "HEV": 8254}
    exports = {"TOTAL": 36086, "HEV": 8720}
    # Only the export cohort is the same month as ACEA, so both are judged
    # by share, and stay is closer (0.36pp against 0.44pp).
    assert fn.closer_to_acea(stay, exports, acea) == "stay"
    # Both totals within 1%: the count decides, and the export cohort's
    # 119 is closer than stay's 347.
    near = {"TOTAL": 36100, "HEV": 8254}
    assert fn.closer_to_acea(near, exports, acea) == "with_exports"


def test_cohort_flag_matches_the_plan():
    assert fn.cohort_exported("stay") is False
    assert fn.cohort_exported("with_exports") is None
    # A blank month has no cohort; it must not be fetched as "both".
    try:
        fn.cohort_exported(None)
    except ValueError:
        pass
    else:
        raise AssertionError("a blank month was given a cohort")


def test_fill_run_is_the_longest_stretch_without_a_hole():
    marks = [("2021-01", True), ("2021-02", False), ("2021-03", True),
             ("2021-04", True), ("2021-05", True), ("2021-06", False)]
    decisions = [{"period": p, "fill": f} for p, f in marks]
    assert fn.fill_run(decisions) == ("2021-03", "2021-05")
    assert fn.fill_run([{"period": "2021-01", "fill": False}]) is None


class _PlanStub:
    """count_new_cars / register_split / CSV path, no network."""

    def __init__(self, tmp, swing, counts, splits=None):
        self.csv = Path(tmp) / "Netherlands.csv"
        lines = ["period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,OTHERS,TOTAL,notes"]
        for period, (total, bev, phev, die) in swing.items():
            lines.append(f"{period},monthly,Whole,Swing,{bev},{phev},,,{die},,{total},")
        self.csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.counts, self.splits = counts, splits or {}

    def __enter__(self):
        self.saved = (fn.CSV_PATHS["Whole"], fn.rdw_session, fn.count_new_cars, fn.register_split)
        fn.CSV_PATHS["Whole"] = self.csv
        fn.rdw_session = lambda: None
        fn.count_new_cars = lambda _s, period, variant="Whole", exported=False: \
            self.counts[period]["stay" if exported is False else "with_exports"]
        fn.register_split = lambda _s, period, choice: self.splits[(period, choice)]
        return self

    def __exit__(self, *exc):
        fn.CSV_PATHS["Whole"], fn.rdw_session, fn.count_new_cars, fn.register_split = self.saved


def test_backfill_plan_fills_only_where_the_window_cohort_fits():
    """One cohort for the whole fill: a month where only the other cohort
    is inside the band stays blank instead of switching scope."""
    import contextlib
    import io
    import tempfile
    swing = {p: (1000, 0, 0, 0) for p in ("2022-01", "2022-02", "2022-03", "2025-01")}
    counts = {
        "2022-01": {"stay": 950, "with_exports": 1000},   # only exports fit
        "2022-02": {"stay": 950, "with_exports": 1010},   # only exports fit
        "2022-03": {"stay": 940, "with_exports": 995},    # only exports fit
        "2025-01": {"stay": 1000, "with_exports": 1030},  # only stay fits
    }
    with tempfile.TemporaryDirectory() as tmp, _PlanStub(tmp, swing, counts) as stub:
        before = stub.csv.read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            plan = fn.backfill_plan("2022-01", "2025-01")
        assert stub.csv.read_bytes() == before
    assert [d["choice"] for d in plan] == ["with_exports"] * 3 + ["stay"]
    assert [d["fill"] for d in plan] == [True, True, True, False]
    text = out.getvalue()
    assert "window cohort: with_exports" in text and "ACEA" not in text
    assert "2025-01: only stay fits" in text
    assert "2022-01..2022-03" in text


def test_shadow_takes_the_window_cohort_and_acea_only_cross_checks():
    import contextlib
    import io
    import tempfile
    swing = {"2026-09": (35529, 9457, 5774, 16)}
    counts = {"2026-09": {"stay": 35333, "with_exports": 36086}}
    # Splits sum to the plate counts; HEV is the September 2026 count, so
    # the ACEA shares are the 0.36pp / 0.44pp in the PR (stay closer).
    split = {"BEV": 10000, "PHEV": 6000, "HEV": 8254, "PETROL": 1837, "DIESEL": 457, "OTHERS": 8785}
    exp_split = dict(split, HEV=8720, OTHERS=9072)
    assert sum(split.values()) == 35333 and sum(exp_split.values()) == 36086
    splits = {("2026-09", "stay"): split, ("2026-09", "with_exports"): exp_split}
    with tempfile.TemporaryDirectory() as tmp, _PlanStub(tmp, swing, counts, splits):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            own = fn.shadow_hev("2026-09")
            forced = fn.shadow_hev("2026-09", cohort="with_exports",
                                   acea={"TOTAL": 36259, "HEV": 8601})
    assert own["HEV"] == 8254 and "still in the country" in own["notes"]
    # The forced cohort is still inside 2% of Swing, so it previews; the
    # ACEA line is printed but the row is that cohort's, not ACEA's pick.
    assert forced["HEV"] == 8720 and "since-exported" in forced["notes"]
    assert forced["TOTAL"] == 35529
    assert "ACEA cross-check" in out.getvalue() and "closer: stay" in out.getvalue()
    # A forced cohort outside the band is blank, not a different scope.
    counts["2026-09"]["with_exports"] = 37000
    with tempfile.TemporaryDirectory() as tmp, _PlanStub(tmp, swing, counts, splits):
        with contextlib.redirect_stdout(io.StringIO()):
            assert fn.shadow_hev("2026-09", cohort="with_exports") is None


def _write_csv(path, rows):
    head = "period,time_interval,variant,source,BEV,PHEV,HEV,PETROL,DIESEL,FLEXFUEL,OTHERS,TOTAL,notes\n"
    Path(path).write_text(head + "".join(r + "\n" for r in rows), encoding="utf-8")


def test_fill_register_hev_is_line_level_and_refuses_outside_the_band():
    """Only the filled Whole lines change; a month outside the band, or one
    that already has the split, is not touched; the cap takes the newest."""
    import contextlib
    import io
    import tempfile
    lines = [
        "2021-12,monthly,Whole,S,5000.0,2000.0,,9000.0,10.0,,100.0,16110.0,workspace_guid=x",
        "2022-01,monthly,Whole,S,5000.0,2000.0,,9000.0,10.0,,100.0,16110.0,workspace_guid=x",
        "2022-02,monthly,Whole,S,5000.0,2000.0,,9000.0,10.0,,100.0,16110.0,workspace_guid=x",
        "2022-03,monthly,Whole,S,5000.0,2000.0,,9000.0,10.0,,100.0,16110.0,workspace_guid=x",
        "2022-04,monthly,Whole,S,5000.0,2000.0,4000.0,4900.0,10.0,,200.0,16110.0,"
        + '"' + fn.register_note("with_exports") + '"',
    ]
    counts = {p: {"stay": 16000, "with_exports": 16100} for p in ("2022-01", "2022-02", "2022-03")}
    counts["2022-02"]["with_exports"] = 17000          # +5.5 %: outside the band
    split = {"BEV": 5000, "PHEV": 2000, "HEV": 4000, "PETROL": 4800, "DIESEL": 200, "OTHERS": 100}
    splits = {(p, "with_exports"): split for p in counts}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "NL_under_test.csv"
        _write_csv(path, lines)
        with _PlanStub(tmp, {}, counts, splits):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                filled = fn.fill_register_hev(str(path), cohort="with_exports", limit=None)
        text = path.read_text(encoding="utf-8").splitlines()
    assert filled == ["2022-01", "2022-03"]
    assert "2022-02: with_exports 17000" in out.getvalue()
    assert text[1] == lines[0] and text[3] == lines[2] and text[5] == lines[4]   # untouched
    import csv
    row = next(csv.DictReader([text[0], text[2]]))
    assert (row["HEV"], row["PETROL"], row["OTHERS"], row["TOTAL"]) == ("4000.0", "4800.0", "300.0", "16110.0")
    assert row["BEV"] == "5000.0" and row["DIESEL"] == "10.0"          # Swing's, not the register's
    assert row["notes"].strip('"') == fn.register_note("with_exports")


def test_fill_register_hev_cap_takes_the_newest_months():
    import contextlib
    import io
    import tempfile
    periods = ["2022-01", "2022-02", "2022-03", "2022-04"]
    lines = [f"{p},monthly,Whole,S,10.0,10.0,,70.0,0.0,,10.0,100.0,x" for p in periods]
    counts = {p: {"stay": 100, "with_exports": 100} for p in periods}
    split = {"BEV": 10, "PHEV": 10, "HEV": 30, "PETROL": 40, "DIESEL": 0, "OTHERS": 10}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "NL_under_test.csv"
        _write_csv(path, lines)
        with _PlanStub(tmp, {}, counts, {(p, "with_exports"): split for p in periods}):
            with contextlib.redirect_stdout(io.StringIO()):
                assert fn.fill_register_hev(str(path), cohort="with_exports", limit=2) == ["2022-03", "2022-04"]
                assert fn.fill_register_hev(str(path), cohort="with_exports", limit=2) == ["2022-01", "2022-02"]
                assert fn.fill_register_hev(str(path), cohort="with_exports", limit=2) == []


def test_carry_register_split_survives_a_swing_restatement():
    note = fn.register_note("with_exports")
    old = {"period": "2026-09", "variant": "Whole", "HEV": "8720.0", "PETROL": "1837.0",
           "OTHERS": "9725.0", "notes": note}
    new = {"period": "2026-09", "variant": "Whole", "TOTAL": 35600.0, "BEV": 9500.0,
           "PHEV": 5800.0, "DIESEL": 16.0, "PETROL": 20200.0, "HEV": "", "OTHERS": 84.0,
           "notes": "workspace_guid=x"}
    kept = fn.carry_register_split(old, new)
    assert kept["HEV"] == 8720.0 and kept["PETROL"] == 1837.0 and kept["TOTAL"] == 35600.0
    assert kept["OTHERS"] == 35600 - 9500 - 5800 - 8720 - 1837 - 16 and kept["notes"] == note
    # Swing restated past the split: Swing's row as published, counted again.
    tiny = dict(new, TOTAL=12000.0)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        assert fn.carry_register_split(old, tiny) is tiny
    # A row without the register split, or another variant, is Swing's.
    assert fn.carry_register_split(dict(old, notes="workspace_guid=x"), new) is new
    assert fn.carry_register_split(old, dict(new, variant="Used"))["HEV"] == ""


def test_main_keeps_the_register_split_when_swing_rewrites_the_window():
    """End to end: Swing re-delivers a month that already has register HEV;
    the row keeps HEV / pure petrol and OTHERS is the slack again."""
    import csv
    import tempfile
    pres = {"Whole": _whole_presentation(), "Used": _used_presentation()}
    real = (fn.fetch_table, dict(fn.CSV_PATHS), sys.argv, fn.make_swing_session, fn.fill_register_hev)
    with tempfile.TemporaryDirectory() as d:
        fn.CSV_PATHS.update({v: str(Path(d) / f"{v}.csv") for v in fn.CSV_PATHS})
        # 2023-09 in the stub: TOTAL 29195, BEV 10075, PHEV 3574, Benzine 15301, Diesel 27.
        _write_csv(fn.CSV_PATHS["Whole"], [
            "2023-09,monthly,Whole," + fn.SOURCE + ",10075.0,3574.0,6000.0,9000.0,27.0,,519.0,29195.0,"
            + '"' + fn.register_note("with_exports") + '"'])
        fn.fetch_table = lambda variant, session: fn.swing_table_to_legacy(pres[variant])
        fn.make_swing_session = lambda: None
        fn.fill_register_hev = lambda *a, **k: []
        try:
            sys.argv = ["x", "--variant", "whole", "--force", "--no-top"]
            fn.main()
        finally:
            fn.fetch_table, paths, sys.argv, fn.make_swing_session, fn.fill_register_hev = real
            fn.CSV_PATHS.update(paths)
        rows = {r["period"]: r for r in csv.DictReader(open(Path(d) / "Whole.csv", encoding="utf-8"))}
    r = rows["2023-09"]
    assert float(r["HEV"]) == 6000 and float(r["PETROL"]) == 9000 and float(r["TOTAL"]) == 29195
    assert float(r["OTHERS"]) == 29195 - 10075 - 3574 - 6000 - 9000 - 27
    assert "RDW register" in r["notes"]
    assert rows["2023-10"]["HEV"] == ""          # a month without the split stays Swing's


def test_rdw_session_falls_back_to_the_socrata_edge_without_dns():
    """opendata.rdw.nl lost its DNS record on 2026-11-20 while the datasets
    kept updating; the tenant answers on Socrata's EU edge by Host header."""
    real = fn.socket.getaddrinfo
    try:
        def no_dns(*a, **k):
            raise OSError("no address")
        fn.socket.getaddrinfo = no_dns
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            s = fn.rdw_session()
        assert s.rdw_base == fn.RDW_EDGE_BASE and s.headers["Host"] == fn.RDW_HOST
        fn.socket.getaddrinfo = lambda *a, **k: [("ok",)]
        plain = fn.rdw_session()
        assert not hasattr(plain, "rdw_base") and "Host" not in plain.headers
    finally:
        fn.socket.getaddrinfo = real
    seen = []

    class FakeSession:
        rdw_base = fn.RDW_EDGE_BASE

        def get(self, url, params=None, timeout=None):
            seen.append(url)
            return FakeResp(200, payload=[{"n": "1"}])
    assert fn.rdw_get(FakeSession(), fn.RDW_VEHICLES, {}) == [{"n": "1"}]
    assert seen == [f"{fn.RDW_EDGE_BASE}{fn.RDW_VEHICLES}.json"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn_ in tests:
        fn_()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
