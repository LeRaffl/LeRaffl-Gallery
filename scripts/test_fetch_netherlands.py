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
            "table": {"colCount": 7, "rowCount": 4, "headColCount": 1, "headRowCount": 1,
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


def test_two_level_header_sums_sub_columns():
    """Used: fuels on the outer header level, each spanning '> 90 dgn' / '<= 90 dgn'."""
    def h(text, span=1):
        return {"colSpan": span, "text": text, "type": 1, "valueType": 3}
    corner = {"text": "Maand", "type": 5, "valueType": 3}
    head0 = {"cells": [corner, h("BEV", 2), h("PHEV", 2), h("Benzine", 2)]}
    head1 = {"cells": [corner] + [h(x) for x in ("> 90 dgn", "<= 90 dgn") * 3]}
    row = {"cells": [{"rowSpan": 1, "text": "31 juli 2026", "type": 2, "valueType": 3}]
           + [_cell(v) for v in ("1.000", "10", "200", "5", "3.000", "30")]}
    pres = {"title": "Occasion import", "table": {"colCount": 7, "rowCount": 1, "headColCount": 1,
            "headRowCount": 2, "rows": [row], "columnHeaderRows": [head0, head1]}}
    data = fn.swing_table_to_legacy(pres)
    assert [c["d"] for c in data["headCols"][0]] == ["BEV", "", "PHEV", "", "Benzine", ""]
    assert fn.parse_table(data, "Used")["2026-07"] == {"BEV": 1010.0, "PHEV": 205.0, "Benzine": 3030.0}


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


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn_ in tests:
        fn_()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
