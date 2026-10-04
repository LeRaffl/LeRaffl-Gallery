"""Temporary probe (small-country sources) — removed before any PR."""
import re, json, os, requests
from pathlib import Path
H = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
OUT = Path("probe_out"); OUT.mkdir(exist_ok=True)
KW = re.compile(r'(statist|vehic|motor|regist|bil|car|transport|fuel|elec|pdf|xls|csv|înmatric|mijloace|vozil)', re.I)

def get(u, **kw):
    return requests.get(u, headers=H, timeout=40, **kw)

def save(name, text):
    (OUT / name).write_text(text, encoding="utf-8")

def page(name, u):
    try:
        r = get(u); t = r.text
        print(f"\n=== {name} {u} -> {r.status_code} {len(t)}B final={r.url}")
        save(name + ".html", t[:3_000_000])
        links = sorted(set(l for l in re.findall(r'href=["\']([^"\']+)["\']', t) if KW.search(l)))
        for l in links[:80]: print("  link:", l)
    except Exception as e:
        print(f"\n=== {name} {u} -> ERROR {type(e).__name__}: {str(e)[:160]}")

def pxweb(name, base, depth=3):
    """Walk a PxWeb v1 API tree, printing folders/tables whose text matches KW."""
    lines = []
    def walk(path, d):
        try:
            r = get(base + path)
            items = r.json()
        except Exception as e:
            lines.append(f"{path} ERR {type(e).__name__} {str(e)[:100]}"); return
        for it in items:
            p = path + it["id"] + ("/" if it.get("type") == "l" else "")
            lines.append(f"{'  '*(3-d)}{it.get('type')} {p} | {it.get('text')}")
            if it.get("type") == "l" and d > 0 and (d == depth or KW.search(it.get("text", "") + it["id"])):
                walk(p, d - 1)
    walk("", depth)
    print(f"\n=== PXWEB {name} {base}"); print("\n".join(lines[:400]))
    save(name + "_tree.txt", "\n".join(lines))

pxweb("faroe_fo", "https://statbank.hagstova.fo/api/v1/fo/H2/")
pxweb("faroe_en", "https://statbank.hagstova.fo/api/v1/en/H2/")
pxweb("greenland", "https://bank.stat.gl/api/v1/en/Greenland/")
page("dmt_lk", "https://dmt.gov.lk/")
page("dmt_lk_stats", "https://dmt.gov.lk/index.php?option=com_content&view=article&id=152&Itemid=181&lang=en")
page("lk_stats", "https://www.statistics.gov.lk/")
page("asp_md", "https://www.asp.gov.md/ro/date-deschise")
page("asp_md_en", "https://www.asp.gov.md/en/open-data")
page("datagov_md", "https://date.gov.md/")
page("bhas", "https://bhas.gov.ba/")
page("mauritius", "https://statsmauritius.govmu.org/")
page("serbia_mup", "https://data.gov.rs/sr/datasets/?q=vozila")
