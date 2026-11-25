#!/usr/bin/env python3
"""Shared retry/backoff for the fetchers' HTTP sessions.

A 2026-11 audit of the fetch workflows (docs/architecture/08-deploy-ops.md,
"Fetch robustness") found that most red runs were one-off network blips that
a second request a few seconds later would have survived:

  * Argentina  RemoteDisconnected on datos.jus.gob.ar
  * Ukraine    503 Service Unavailable on data.gov.ua
  * ACEA CV    520 from acea.auto's CDN
  * Switzerland "Connection reset by peer"

Each fetcher grew its own ad-hoc loop (or none). This module gives them one
behaviour:

    import http_retry
    session = http_retry.mount(requests.Session())

`mount()` installs an HTTPAdapter whose urllib3 Retry policy

  * retries connect errors, read errors and dropped connections,
  * retries 429 and the transient 5xx family (500, 502, 503, 504 and the
    Cloudflare 520-524 range), honouring a server's Retry-After header,
  * only for idempotent methods (GET/HEAD/OPTIONS) — a POST/PATCH that a
    server may already have applied is never replayed,
  * backs off exponentially: BACKOFF * 2**(n-1) seconds, capped at BACKOFF_MAX,
  * returns the last response (raise_for_status() still decides) instead of
    raising MaxRetryError on an exhausted status retry, so callers keep their
    existing error handling and messages.

A 403/404 is *not* retried: those are answers (bot wall, not published yet),
and hammering them only makes a block worse.

`mount()` also gives the session a default timeout, so a request that forgot
`timeout=` can no longer hang a runner for the job's whole time budget.
Explicit per-call timeouts still win.
"""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

TOTAL = 4                  # attempts after the first
BACKOFF = 2.0              # seconds; 2, 4, 8, 16 (urllib3 skips the first sleep)
BACKOFF_MAX = 60.0
DEFAULT_TIMEOUT = 120      # seconds, only when the caller passes none
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504, 520, 521, 522, 523, 524})
IDEMPOTENT = frozenset({"GET", "HEAD", "OPTIONS"})


def retry_policy(total: int = TOTAL, backoff: float = BACKOFF) -> Retry:
    """The urllib3 Retry every fetcher session shares."""
    kw = dict(
        total=total,
        connect=total,
        read=total,
        status=total,
        backoff_factor=backoff,
        status_forcelist=sorted(RETRY_STATUSES),
        allowed_methods=sorted(IDEMPOTENT),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    try:
        return Retry(backoff_max=BACKOFF_MAX, **kw)   # urllib3 >= 2
    except TypeError:                                  # urllib3 1.x
        return Retry(**kw)


class _TimeoutAdapter(HTTPAdapter):
    def __init__(self, *args, timeout: float | None = DEFAULT_TIMEOUT, **kw):
        self._timeout = timeout
        super().__init__(*args, **kw)

    def send(self, request, **kw):
        if kw.get("timeout") is None:
            kw["timeout"] = self._timeout
        return super().send(request, **kw)


def mount(session: requests.Session | None = None, *, total: int = TOTAL,
          backoff: float = BACKOFF,
          timeout: float | None = DEFAULT_TIMEOUT) -> requests.Session:
    """Install the shared retry policy (and a default timeout) on `session`.

    Returns the session so it can wrap a constructor call in place:
    ``s = http_retry.mount(requests.Session())``.
    """
    session = session if session is not None else requests.Session()
    adapter = _TimeoutAdapter(max_retries=retry_policy(total, backoff),
                              timeout=timeout)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def session(headers: dict | None = None, **kw) -> requests.Session:
    """A new requests.Session with the shared policy and optional headers."""
    s = mount(requests.Session(), **kw)
    if headers:
        s.headers.update(headers)
    return s
