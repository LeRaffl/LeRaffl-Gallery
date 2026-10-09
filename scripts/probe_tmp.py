#!/usr/bin/env python3
"""TEMPORARY probe for Greek registration sources (removed before the PR).

Crawls a few seeds on SEAA / ELSTAT / data.gov.gr, keeps pages whose URL or
text look statistics-related, downloads small data files, and writes an index
to probe_out/greece/index.txt.
"""
import os, re, sys, time, hashlib, urllib.request, urllib.parse, ssl, json
from html.parser import HTMLParser

OUT = "probe_out/greece"
os.makedirs(OUT, exist_ok=True)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SEEDS = [s for s in os.environ.get("PROBE_SEEDS", "").split() if s] or [
    "https://www.seaa.gr/",
    "https://www.seaa.gr/el/",
    "https://www.seaa.gr/en/",
    "https://www.statistics.gr/el/statistics/-/publication/SME18/-",
    "https://www.statistics.gr/en/statistics/-/publication/SME18/-",
    "https://www.statistics.gr/en/statistics/tra",
    "https://data.gov.gr/search/?q=%CE%BF%CF%87%CE%AE%CE%BC%CE%B1%CF%84%CE%B1",
    "https://data.gov.gr/datasets/",
]
KEY = re.compile(r"stat|ταξινομ|taxinom|registr|licen|άδει|adeies|κυκλοφ|vehicl|car|αυτοκιν|press|δελτ|deltia|SME18|transport|μεταφ|xls|pdf|csv|json|api", re.I)
FILE = re.compile(r"\.(pdf|xlsx?|csv|zip|json)(\?|$)", re.I)
MAXPAGES = int(os.environ.get("PROBE_MAXPAGES", "220"))
MAXFILES = int(os.environ.get("PROBE_MAXFILES", "60"))
DEPTH = int(os.environ.get("PROBE_DEPTH", "3"))
ALLOWED = ("seaa.gr", "statistics.gr", "data.gov.gr")

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links = []; self.cur = None; self.txt = []
    def handle_starttag(self, t, a):
        a = dict(a)
        if t == "a" and a.get("href"):
            self.cur = [a["href"], ""]; self.links.append(self.cur)
        for k in ("src", "data-href", "data-url"):
            if a.get(k) and FILE.search(a[k]):
                self.links.append([a[k], k])
    def handle_endtag(self, t):
        if t == "a": self.cur = None
    def handle_data(self, d):
        if self.cur is not None: self.cur[1] += d.strip()

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "el,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read(), r.geturl()

def safe(url):
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.unquote(url.split("//", 1)[-1]))[-80:]
    return f"{h}_{tail}"

seen, queue, idx, nfiles = set(), [(s, 0) for s in SEEDS], [], 0
while queue and len(seen) < MAXPAGES:
    url, d = queue.pop(0)
    if url in seen: continue
    seen.add(url)
    try:
        st, ct, body, final = get(url)
    except Exception as e:
        idx.append(f"ERR  {url}  {e!r}"); continue
    isfile = FILE.search(url) or "html" not in ct
    if isfile:
        if nfiles < MAXFILES and len(body) < 15_000_000:
            fn = safe(url); open(os.path.join(OUT, fn), "wb").write(body); nfiles += 1
            idx.append(f"FILE {st} {ct} {len(body)} {url} -> {fn}")
        else:
            idx.append(f"SKIPFILE {st} {ct} {len(body)} {url}")
        continue
    fn = safe(url) + ".html"
    open(os.path.join(OUT, fn), "wb").write(body)
    idx.append(f"PAGE {st} {ct} {len(body)} {url} (final {final}) -> {fn}")
    try:
        p = Links(); p.feed(body.decode("utf-8", "replace"))
    except Exception:
        continue
    for href, text in p.links:
        u = urllib.parse.urljoin(final, href.strip()).split("#")[0]
        host = urllib.parse.urlparse(u).netloc
        if not any(host.endswith(a) for a in ALLOWED): continue
        idx.append(f"  LINK {u}  [{text[:80]}]")
        if u in seen: continue
        if FILE.search(u):
            queue.insert(0, (u, d + 1))
        elif d + 1 <= DEPTH and KEY.search(u + " " + text):
            queue.append((u, d + 1))
    time.sleep(0.3)

open(os.path.join(OUT, "index.txt"), "w").write("\n".join(idx) + "\n")
print(f"pages={len(seen)} files={nfiles}")
