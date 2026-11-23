#!/usr/bin/env python3
"""Offline tests for scripts/http_retry.py. A throwaway local HTTP server
plays the flaky upstream; no internet.

    python scripts/test_http_retry.py
"""
import http.server
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import requests  # noqa: E402

import http_retry  # noqa: E402


class _Flaky(http.server.BaseHTTPRequestHandler):
    """Answers each path from a script of status codes, then 200."""
    plans: dict[str, list[int]] = {}
    hits: dict[str, int] = {}

    def _answer(self, body: bool = True):
        n = self.hits.get(self.path, 0)
        self.hits[self.path] = n + 1
        plan = self.plans.get(self.path, [])
        code = plan[n] if n < len(plan) else 200
        if code == -1:                       # drop the connection mid-request
            self.close_connection = True
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        if body:
            self.wfile.write(b"ok")

    def do_GET(self):
        self._answer()

    def do_POST(self):
        self._answer()

    def log_message(self, *a):
        pass


def _serve():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _fast_session():
    return http_retry.mount(requests.Session(), backoff=0.01)


def test_transient_5xx_and_cloudflare_52x_are_retried():
    srv, base = _serve()
    try:
        _Flaky.plans["/a"] = [503, 520, 502]
        r = _fast_session().get(base + "/a", timeout=5)
        assert r.status_code == 200 and _Flaky.hits["/a"] == 4
    finally:
        srv.shutdown()


def test_dropped_connection_is_retried():
    srv, base = _serve()
    try:
        _Flaky.plans["/drop"] = [-1, -1]
        r = _fast_session().get(base + "/drop", timeout=5)
        assert r.status_code == 200 and _Flaky.hits["/drop"] == 3
    finally:
        srv.shutdown()


def test_403_and_404_are_answers_not_retried():
    srv, base = _serve()
    try:
        _Flaky.plans["/f"] = [403]
        _Flaky.plans["/n"] = [404]
        s = _fast_session()
        assert s.get(base + "/f", timeout=5).status_code == 403
        assert s.get(base + "/n", timeout=5).status_code == 404
        assert _Flaky.hits["/f"] == 1 and _Flaky.hits["/n"] == 1
    finally:
        srv.shutdown()


def test_exhausted_retries_return_last_response_for_raise_for_status():
    srv, base = _serve()
    try:
        _Flaky.plans["/down"] = [503] * 10
        r = _fast_session().get(base + "/down", timeout=5)
        assert r.status_code == 503
        assert _Flaky.hits["/down"] == http_retry.TOTAL + 1
        try:
            r.raise_for_status()
        except requests.HTTPError:
            pass
        else:
            raise AssertionError("raise_for_status should still raise")
    finally:
        srv.shutdown()


def test_post_is_never_replayed():
    srv, base = _serve()
    try:
        _Flaky.plans["/p"] = [503]
        r = _fast_session().post(base + "/p", data=b"x", timeout=5)
        assert r.status_code == 503 and _Flaky.hits["/p"] == 1
    finally:
        srv.shutdown()


def test_default_timeout_only_fills_a_missing_one():
    seen = []

    class Capture(requests.adapters.HTTPAdapter):
        def send(self, request, **kw):
            seen.append(kw.get("timeout"))
            raise requests.ConnectionError("stop")

    class Spy(http_retry._TimeoutAdapter, Capture):
        pass

    s = requests.Session()
    s.mount("http://", Spy(timeout=7))
    for kw in ({}, {"timeout": 3}):
        try:
            s.get("http://127.0.0.1:9/", **kw)
        except requests.ConnectionError:
            pass
    assert seen == [7, 3]


def test_session_helper_sets_headers_and_adapters():
    s = http_retry.session({"User-Agent": "x"})
    assert s.headers["User-Agent"] == "x"
    a = s.get_adapter("https://example.org/")
    assert isinstance(a, http_retry._TimeoutAdapter)
    assert 520 in a.max_retries.status_forcelist
    assert "POST" not in a.max_retries.allowed_methods


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
