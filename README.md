
# BEV Gallery Starter

Das hier ist eine **statische** Galerie (reines HTML + JS), die deine Charts aus `images/` und `manifest.json` rendert.

## Struktur
```
/
  index.html
  manifest.json
  images/
```

## 1) Lokal testen
Öffne `index.html` per Doppelklick. Falls der Browser Lokaldateien blockt, starte einen simplen Server:

```
python3 -m http.server 8080
# dann: http://localhost:8080
```

## 2a) GitHub Pages (am einfachsten, ohne Build)
1. Neues Git-Repo erstellen, alles commiten und pushen.
2. In den Repo-Settings unter **Pages**: Source = `Branch: main`, Folder = `/root`.
3. Warten bis die Seite gebaut ist. URL steht in den Pages-Settings.

## 2b) Vercel (sehr bequem)
1. https://vercel.com → neues Projekt → "Import Git Repository".
2. Build Command: **None** (kein Build). Output Directory: **/** (Root).
3. Deploy. Custom Domain in Vercel hinzufügen und DNS (CNAME) setzen.

## 2c) Cloudflare Pages
1. https://dash.cloudflare.com → Pages → "Create a project" → "Connect to Git".
2. Build command leer lassen, Output directory `/`.
3. Deploy. Domain per Cloudflare-DNS als CNAME verknüpfen.

## 3) Eigene Domain
- Domain bei einem Registrar kaufen.
- CNAME `charts.deinedomain.tld` → deine Hosting-URL (Vercel/Cloudflare) setzen.
- HTTPS kommt automatisch.

## 4) Bilder und Manifest aktualisieren
- Lege neue PNG/WEBP in `images/` ab.
- Ergänze sie in `manifest.json` im Format:
```json
{
  "country": "Germany",
  "type": "ICE_BEV",
  "date": "2025-07-04",
  "filename": "germany_ICE_BEV_20250704.webp",
  "url": "images/germany_ICE_BEV_20250704.webp",
  "alt": "Deutschland: ICE vs BEV"
}
```
- Commit & Push → Seite aktualisiert sich.

## 5) R-Automation (kurz)
Exportiere beim Rendern deiner Plots gleich WEBP/PNG in `images/` und generiere `manifest.json` automatisch (siehe dein R-Snippet aus dem Chat).

## Optional
- `.nojekyll` legen wir bei, damit GitHub Pages nichts "cleveres" versucht.
- `robots.txt` und `sitemap.xml` kannst du später ergänzen.
