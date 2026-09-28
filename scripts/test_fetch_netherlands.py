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


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn_ in tests:
        fn_()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
