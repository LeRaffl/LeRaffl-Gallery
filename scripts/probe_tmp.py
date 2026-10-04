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

def faroe():
    base = "https://statbank.hagstova.fo/api/v1/en/H2/SS/SS03/"
    try:
        items = get(base).json()
    except Exception as e:
        print("faroe ERR", e); return
    print("\n=== FAROE SS03"); 
    for it in items:
        print(" ", it)
        if it.get("type") == "t":
            try:
                meta = get(base + it["id"]).json()
                save("faroe_" + it["id"] + ".json", json.dumps(meta, ensure_ascii=False, indent=1))
                for v in meta.get("variables", []):
                    vals = v.get("valueTexts", [])
                    print("     var", v.get("code"), v.get("text"), len(vals), vals[:12], "...", vals[-3:])
            except Exception as e:
                print("   meta ERR", e)
        elif it.get("type") == "l":
            try:
                for sub in get(base + it["id"] + "/").json(): print("    sub", sub)
            except Exception as e: print("   sub ERR", e)

import shutil
shutil.rmtree(OUT); OUT.mkdir()
for name, u in [("and_aug26.pdf", "https://www.altaveu.com/uploads/s1/26/23/88/5/matriculacions-agost-2026.pdf"),
                ("and_feb26.pdf", "https://www.altaveu.com/uploads/s1/23/85/27/0/matriculacions-febrer-2026.pdf"),
                ("and_may25.pdf", "https://www.altaveu.com/uploads/s1/20/71/48/5/nota-matriculacions-maig-2025.pdf")]:
    try:
        r = get(u); print(name, r.status_code, len(r.content)); (OUT / name).write_bytes(r.content)
    except Exception as e:
        print(name, "ERR", e)
page("estad_ad", "https://www.estadistica.ad/")
page("estad_ad_portal", "https://www.estadistica.ad/portal/apps/sites/#/estadistica-ca")
for u in ["https://www.estadistica.ad/serveiestudis/web/banc_dades4.asp?lang=1&codi_div=12",
          "https://www.estadistica.ad/serveiestudis/web/index.asp?lang=1"]:
    page("estad_ad_" + str(abs(hash(u)) % 1000), u)
