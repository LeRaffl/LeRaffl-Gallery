"""TEMP diagnostic for the ANFAVEA site relaunch — removed before merge."""
import re

import requests
from bs4 import BeautifulSoup

H = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
BASE = "https://anfavea.com.br/site/"

r = requests.get(BASE + "central-de-dados/", headers=H, timeout=30)
soup = BeautifulSoup(r.text, "html.parser")
print("=== inline scripts")
for s in soup.find_all("script"):
    if s.get("src"):
        print("SRC", s["src"])
    elif s.string and len(s.string.strip()) > 0:
        t = s.string.strip()
        if re.search(r"ajax|url|api|json|dados|nonce", t, re.I):
            print("INLINE:", t[:1500])
print("=== main content text (first 4000 chars)")
main = soup.find("main") or soup.body
print(main.get_text("\n", strip=True)[:4000])
print("=== elements with data-* attrs in main")
for tag in main.find_all(True):
    d = {k: v for k, v in tag.attrs.items() if k.startswith("data-")}
    if d:
        print(tag.name, tag.get("id"), tag.get("class"), d)
print("=== selects/options")
for sel in main.find_all("select"):
    print("SELECT", sel.attrs, [o.get("value") for o in sel.find_all("option")][:40])
print("=== buttons/links in main")
for a in main.find_all(["a", "button"]):
    print(a.name, a.attrs, a.get_text(" ", strip=True)[:60])

for s in soup.find_all("script", src=True):
    if "central-de-dados" in s["src"] or "anfavea-theme" in s["src"]:
        js = requests.get(s["src"], headers=H, timeout=30).text
        print(f"\n=== JS {s['src']} len={len(js)}")
        print(js[:20000])
