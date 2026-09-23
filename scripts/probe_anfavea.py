"""TEMP diagnostic for the ANFAVEA site relaunch — removed before merge."""
import json
import re

import requests
from bs4 import BeautifulSoup

H = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}
BASE = "https://anfavea.com.br/site/"
S = requests.Session()
S.headers.update(H)
page = S.get(BASE + "central-de-dados/", timeout=30).text
nonce = re.search(r'"nonce":"([0-9a-f]+)"', page).group(1)
AJAX = BASE + "wp-admin/admin-ajax.php"
print("nonce", nonce, "cookies", S.cookies.get_dict())


def post(fields, show=3000):
    data = [("nonce", nonce)] + fields
    r = S.post(AJAX, data=data, timeout=60, headers={"Referer": BASE + "central-de-dados/"})
    print(f"\n### {fields}\n-> {r.status_code} len={len(r.text)}")
    try:
        j = r.json()
    except Exception:
        print(r.text[:500])
        return None
    d = j.get("data")
    if isinstance(d, dict) and "table_html" in d:
        html = d["table_html"]
        print("RAW HTML head:", html[:1500])
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr")[:60]:
            print("  ", " | ".join(c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"]))[:400])
        extra = {k: v for k, v in d.items() if k != "table_html"}
        print("other keys:", json.dumps(extra)[:500])
    else:
        print(json.dumps(j, ensure_ascii=False)[:show])
    return j


post([("action", "anfavea_get_periodos"), ("tipo_dado", "emplacamento"), ("dashboard", "dashboard1"),
      ("tem_filtro_empresa", "false"), ("procedencia", "total"), ("dimensao_emplacamento", "combustivel"),
      ("categorias[]", "automoveis")], show=1500)

post([("action", "carregar_filtros_empresa_marca"), ("categorias[]", "automoveis"),
      ("procedencia", "total"), ("empresa", "todas")], show=3000)

common = [("action", "anfavea_dashboard1"), ("dashboard", "dashboard1"), ("tipo_dado", "emplacamento"),
          ("tipo_dado_dashboard2", "emprego"), ("tipo_dado_maquina", "VENDA ATACADO"),
          ("agregacao", "mensal"), ("inicio", "2025-11"), ("fim", "2026-08")]

# Fuel dimension, all fuels, cars only / light commercials only / both
for cats in (["automoveis"], ["comerciais_leves"], ["automoveis", "comerciais_leves"], ["total_leves"]):
    post(common + [("categorias[]", c) for c in cats] +
         [("dimensao_emplacamento", "combustivel"), ("combustivel_filter[]", "todos"),
          ("procedencia", ""), ("por_empresa", "0"), ("por_marca", "0"), ("empresa", ""), ("marca", "")])

# Explicit fuel list
post(common + [("categorias[]", "automoveis"), ("dimensao_emplacamento", "combustivel")] +
     [("combustivel_filter[]", f) for f in ("diesel", "eletrico", "etanol", "flex", "gasolina", "plugin", "hibrido")] +
     [("procedencia", ""), ("por_empresa", "0"), ("por_marca", "0"), ("empresa", ""), ("marca", "")])

# Brand dimension (does it cross with fuel?)
post(common + [("categorias[]", "automoveis"), ("dimensao_emplacamento", "procedencia"),
               ("procedencia[]", "total"), ("por_empresa", "0"), ("por_marca", "1"),
               ("empresa", ""), ("marca", ""), ("combustivel_filter", "")])
# Long history check
post([(k, v) for k, v in common if k not in ("inicio", "fim")] + [("inicio", "2012-01"), ("fim", "2012-03"),
     ("categorias[]", "automoveis"), ("dimensao_emplacamento", "combustivel"), ("combustivel_filter[]", "todos"),
     ("procedencia", ""), ("por_empresa", "0"), ("por_marca", "0"), ("empresa", ""), ("marca", "")])
