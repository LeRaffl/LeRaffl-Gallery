"""TEMPORARY reachability probe for Vietnam sources (removed before merge)."""
import os, pathlib, time, urllib.request, urllib.parse

UA = "Mozilla/5.0 (X11; Linux x86_64) LeRaffl-Gallery probe (github.com/LeRaffl/LeRaffl-Gallery)"
OUT = pathlib.Path("probe_out"); OUT.mkdir(exist_ok=True)
SEC_UA = "LeRaffl-Gallery grokbot@users.noreply.github.com"
TESTS2 = [
    ("vg_news", "https://vingroup.net/tin-tuc-su-kien"),
    ("vg_news_p2", "https://vingroup.net/tin-tuc-su-kien?page=2"),
    ("vg_search", "https://vingroup.net/tim-kiem?keyword=VinFast%20b%C3%A0n%20giao"),
    ("vg_art", "https://www.vingroup.net/vi/tin-tuc-su-kien/bai-viet/9096/vinfast-ban-giao-23624-o-to-dien-tai-viet-nam-trong-thang-9"),
    ("vg_art2", "https://vingroup.net/tin-tuc-su-kien/bai-viet/9096/vinfast-ban-giao-23624-o-to-dien-tai-viet-nam-trong-thang-9"),
    ("vg_en_news", "https://vingroup.net/en/news"),
    ("vinfast_news", "https://vinfastauto.com/vn_vi/tin-tuc"),
]
TESTS = [
    ("vama_list", "http://vama.org.vn/en/sales-report.html"),
    ("vama_list_https", "https://vama.org.vn/en/sales-report.html"),
    ("vama_list_p2", "http://vama.org.vn/en/sales-report.html?Page=2"),
    ("vama_home_www", "http://www.vama.org.vn/"),
    ("edgar_index", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1913510&type=6-K&dateb=&owner=include&count=40&output=atom"),
    ("edgar_json", "https://data.sec.gov/submissions/CIK0001913510.json"),
    ("vingroup", "https://vingroup.net/"),
    ("tc_2026_09", "https://thanhcong.vn/tin-tuc/tc-group-thong-bao-doanh-so-ban-hang-xe-hyundai-thang-9-2026.html"),
    ("tc_news", "https://thanhcong.vn/tin-tuc"),
    ("csgt", "https://csgt.vn/"),
    ("csgt_bocongan", "https://csgt.bocongan.gov.vn/"),
    ("bocongan", "https://bocongan.gov.vn/"),
]
TIMEOUT = 40
lines = ["| name | status | bytes | seconds | url |", "|---|---|---|---|---|"]

def get(name, url, save=True, ua=None):
    t = time.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua or UA, "Accept": "*/*", "Accept-Encoding": "identity"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(); st = r.status
        if save:
            (OUT / name).write_bytes(body)
        res = (st, len(body))
    except Exception as e:  # noqa
        res = (f"ERR {type(e).__name__}: {str(e)[:80]}", 0)
    lines.append(f"| {name} | {res[0]} | {res[1]} | {time.time()-t:.1f} | {url} |")
    print(lines[-1], flush=True)

for n, u in TESTS2:
    get(n + ".html", u, ua=UA)
TESTS = TESTS[:1]
for n, u in TESTS:
    get(n + ".html", u)
ok_vama = any(l.startswith("| vama_list") and "| 200 |" in l for l in lines)
print("VAMA listing reachable:", ok_vama, flush=True)
urls = open("scripts/probe_tmp_urls.txt").read().split()
if not ok_vama:
    urls = urls[:2]  # two direct PDF attempts, then give up
TIMEOUT = 120
for i, u in enumerate(urls):
    name = "vama_" + urllib.parse.unquote(u.rsplit("/", 1)[1]).replace(" ", "_")
    get(name, u)
with open(os.environ.get("GITHUB_STEP_SUMMARY", "/dev/null"), "a") as fh:
    fh.write("\n".join(lines) + "\n")
