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

faroe()
page("dmt_lk_stats", "https://dmt.gov.lk/index.php?option=com_content&view=article&id=16&Itemid=132&lang=en")
page("asp_md_stats", "https://www.asp.gov.md/ro/date-deschise/date-statistice")
for q in ("transport", "vehicule", "inmatriculate", "mijloace de transport"):
    try:
        r = get("https://dataset.gov.md/api/3/action/package_search", params={"q": q, "rows": 25})
        print(f"\n=== dataset.gov.md q={q} -> {r.status_code}")
        d = r.json()["result"]; print("count", d["count"])
        for pk in d["results"]:
            print("  -", pk.get("name"), "|", pk.get("title"), "|", (pk.get("organization") or {}).get("title"),
                  "|", pk.get("metadata_modified"), "|", [ (x.get("format"), x.get("url")) for x in pk.get("resources", [])][:4])
    except Exception as e:
        print(f"\n=== dataset.gov.md q={q} ERROR {type(e).__name__}: {str(e)[:200]}")
