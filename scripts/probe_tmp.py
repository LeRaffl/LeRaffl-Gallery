"""TEMPORARY probe for the Vietnam history (removed before merge): crawl
vama.org.vn's sales-report listings (http only works from the runner) and
download the monthly PDFs 2018-01 .. 2024-08 into an artifact. Nothing is
committed."""
import os, pathlib, re, time, urllib.request, urllib.parse, html, json

UA = "Mozilla/5.0 (X11; Linux x86_64) LeRaffl-Gallery probe (github.com/LeRaffl/LeRaffl-Gallery)"
BASE = "http://vama.org.vn"
OUT = pathlib.Path("probe_out"); (OUT / "pdf").mkdir(parents=True, exist_ok=True); (OUT / "html").mkdir(exist_ok=True)
log = []

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa
            err = f"{type(e).__name__}: {str(e)[:80]}"
            time.sleep(3 * (i + 1))
    log.append(f"FAIL {url} {err}")
    return None

seen_pages, pdfs, queue = set(), {}, []
for lang, path in (("en", "/en/sales-report.html"), ("vn", "/vn/bao-cao-ban-hang.html")):
    for p in range(1, 41):
        queue.append(f"{BASE}{path}?Page={p}")
t0 = time.time()
while queue and time.time() - t0 < 1500:
    u = queue.pop(0)
    if u in seen_pages:
        continue
    seen_pages.add(u)
    b = get(u)
    if not b:
        continue
    h = b.decode("utf-8", "replace")
    (OUT / "html" / (re.sub(r"[^A-Za-z0-9]+", "_", u[len(BASE):])[:120] + ".html")).write_text(h)
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', h, re.S | re.I):
        href = urllib.parse.urljoin(u, html.unescape(m.group(1)))
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(m.group(2)))).strip()
        if href.lower().endswith(".pdf"):
            pdfs.setdefault(href, {"text": text, "page": u})
        elif href.startswith(BASE) and re.search(r"sales-report-|bao-cao-ban-hang-", href) and href not in seen_pages:
            queue.append(href)
(OUT / "pdf_links.json").write_text(json.dumps(pdfs, indent=1, ensure_ascii=False))
want = [u for u in pdfs if re.search(r"/files/20(1[89]|2[0-4])/", u)]
for u in sorted(want):
    name = urllib.parse.unquote(u.split("/files/", 1)[1]).replace("/", "__").replace(" ", "_")
    if (OUT / "pdf" / name).exists():
        continue
    b = get(u)
    if b:
        (OUT / "pdf" / name).write_bytes(b)
summary = f"pages {len(seen_pages)}, pdf links {len(pdfs)}, wanted {len(want)}, saved {len(list((OUT/'pdf').iterdir()))}, fails {len(log)}"
print(summary); print("\n".join(log[:50]))
(OUT / "log.txt").write_text(summary + "\n" + "\n".join(log))
with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a") as fh:
    fh.write(summary + "\n")
