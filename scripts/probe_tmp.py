"""Temporary probe (Vietnam sources) — removed before any PR."""
import re, json, sys, requests
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
     "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}
URLS = [
 "https://vama.org.vn/vn/bao-cao-ban-hang.html", "https://vama.org.vn/en/sales-report.html", "https://vama.org.vn/",
 "https://www.vr.org.vn/", "https://www.vr.org.vn/Pages/thong-ke.aspx", "http://www.vr.org.vn/",
 "https://www.csgt.vn/", "https://www.nso.gov.vn/", "https://www.nso.gov.vn/so-lieu-thong-ke/",
 "https://www.customs.gov.vn/index.jsp?pageId=3&cid=1293", "https://www.customs.gov.vn/",
 "https://data.gov.vn/", "https://data.gov.vn/api/3/action/package_search?q=%C3%B4%20t%C3%B4&rows=20",
 "https://data.gov.vn/api/3/action/package_search?q=xe&rows=20",
 "https://www.tcmotor.vn/", "https://hyundai.tcmotor.vn/", "https://vinfastauto.com/vn_vi",
 "https://ir.vinfastauto.com/", "https://vneconomy.vn/", "https://dangkiem.vr.org.vn/",
]
KW = re.compile(r'(thống kê|thong-ke|bao-cao|báo cáo|sales|\.pdf|\.xlsx?|so-lieu|số liệu|xe điện|dien)', re.I)
for u in URLS:
    try:
        r = requests.get(u, headers=H, timeout=40, allow_redirects=True)
        t = r.text
        print(f"\n=== {u} -> {r.status_code} {len(t)}B final={r.url}")
        if "api/3/action" in u:
            try:
                d = r.json()["result"]; print("count", d["count"])
                for p in d["results"]: print("  -", p.get("name"), "|", p.get("title"), "|", p.get("organization", {}).get("title") if p.get("organization") else "")
            except Exception as e: print("json err", e, t[:300])
            continue
        title = re.search(r"<title[^>]*>(.*?)</title>", t, re.S)
        print("title:", (title.group(1).strip()[:120] if title else None))
        links = set(re.findall(r'href=["\']([^"\']+)["\']', t))
        hits = sorted(l for l in links if KW.search(l))[:60]
        for l in hits: print("  link:", l)
    except Exception as e:
        print(f"\n=== {u} -> ERROR {type(e).__name__}: {str(e)[:200]}")
