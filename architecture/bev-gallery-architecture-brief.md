# BEV Trajectories Gallery — Architektur-Brief für EAM-Modellierung in ADOIT

> **Auftrag an die nächste Claude-Session:** Modelliere das unten beschriebene System in ADOIT als ArchiMate-konformes Architekturbild. Erzeuge Application Components, Application Interfaces, Data Objects, Business Processes, Technology Services und Actors mit den entsprechenden Beziehungen. Ziel: ein vollumfängliches Übersichtsdiagramm das technische **und** fachliche Sicht abbildet. Bei Unklarheiten frag nach — der ursprüngliche Architekt ist verfügbar.

---

## 1. Zweck und Geschäftskontext

**Was das System tut:** Veröffentlicht für ~30 Länder visuelle Extrapolationen zur Marktdurchdringung von Elektrofahrzeugen (BEV/PHEV/ICE) bei Neuzulassungen, basierend auf monatlichen Registrierungsdaten. Pro Land werden vier Charts erzeugt (BEV-Trajektorie, ICE/BEV/PHEV-Kombination, Transition-Time-Erwartung, 12-Monats-Trailing Marktanteile pro Antriebsart). Die Charts laufen auf einer öffentlichen GitHub-Pages-Seite, sind monatlich aktualisiert, und werden über soziale Medien (X, Bluesky) referenziert.

**Wer es nutzt:**
- **Öffentlichkeit / Datenjournalismus / Forschung:** Konsumiert Charts auf der Page, kann Threshold-Tabellen vergleichen, FAQs lesen, Feedback geben, Datenkorrekturen einreichen.
- **Maintainer (eine Person, GitHub-User `LeRaffl`):** Pflegt Rohdaten, reviewt eingereichte PRs, mergt, triggert Re-Renders, betreut den FontAwesome/Flag-Asset-Bestand.
- **Automatisierte Bots:** GitHub Actions (Manifest-Build, Render-Action), Cloudflare Worker (Feedback-Proxy, Submit-Proxy).

**Geschäftsfähigkeiten:**
1. *Datenerfassung* (Maintainer + Public-Submit)
2. *Modellbildung* (gewichtete Regression pro Land, byte-stabil reproduzierbar)
3. *Visualisierung* (vier kanonische Plots pro Land/Variante)
4. *Publikation* (statische Seite via GitHub Pages)
5. *Community-Interaktion* (Feedback, Q&A, Datenkorrektur-Vorschläge)

---

## 2. Actors / Akteure

| Actor | Typ | Rolle |
|---|---|---|
| Public Visitor | Human, anonym | Konsumiert Charts; kann Feedback und Submits absenden |
| Maintainer (`LeRaffl`) | Human, autorisiert | Merge-Rechte, Action-Trigger, PAT-Inhaber |
| GitHub Actions Runner | Automation | Führt Manifest-Build und Country-Render aus |
| Cloudflare Worker | Automation, hosted | Vermittelt Page ↔ GitHub API |
| ACEA (zukünftig) | Externe Datenquelle | Liefert Rohdaten für viele EU-Länder |
| Sonstige nationale Quellen | Externe Datenquelle | Pro-Land-spezifisch (KBA für DE, ofv.no für NO, JADA für JP, etc.) |

---

## 3. Application Components (das System-Inventar)

### 3.1 Static Web Frontend
- **Name:** `LeRaffl-Gallery Page`
- **Tech:** Single-File HTML/CSS/JS (`index.html`, ~5900 Zeilen), kein Build-Step, keine Frameworks
- **Hosted on:** GitHub Pages (`https://leraffl.github.io/LeRaffl-Gallery/`)
- **Tabs/Module:**
  - Gallery (rendert die PNGs aus `manifest.json`)
  - Thresholds (Tabelle: wann erreicht jedes Land 20%/50%/80% BEV-Anteil)
  - Durations (Tabelle: wie viele Jahre für Übergänge erwartet)
  - Builder (interaktiver "What-if"-Modus)
  - Fleet (Bestand-Extrapolationen, eigener CSV-Datensatz unter `fleet/`)
  - World Map (Choroplethe nach BEV-Anteil)
  - FAQ
  - **Submit Data** *(neu in PR #12)*: Formular für neue Datenpunkte und Korrekturen
  - Feedback & Questions (Issue-basierter Diskussions-Thread)
- **Entry Point:** `index.html` lädt `manifest.json` für Galerie, `params.csv` für Modell-Parameter, `weights.csv` für gewichtete Aggregate.

### 3.2 Cloudflare Worker — Edge-Vermittler
- **Name:** `leraffl-gallery-feedback` (Endpoint: `https://leraffl-gallery-feedback.xgwvfz7nrb.workers.dev`)
- **Rolle:** Einziger Brücken-Bauteil zwischen statischer Page und schreibenden GitHub-Operationen. Hält das GitHub-PAT-Secret. Macht CORS, Rate-Limiting (3/Stunde/IP über Cloudflare KV), Honeypot-Spam-Filter.
- **Endpoints:**
  - `GET /issues` — Listet Feedback-Issues, Cache 60 s
  - `POST /issues` — Nimmt Feedback-Formular entgegen, erstellt Issue
  - `POST /submissions` *(neu)* — Nimmt Datenpunkt-Submissions entgegen, upsertet in `data/<Country>.csv` per Branch + PR gegen master
- **Tech:** JavaScript (Workers Runtime), KV-Binding `RATE_KV`
- **Secrets:** `GITHUB_TOKEN` (Fine-grained PAT)

### 3.3 R Render-Pipeline
- **Name:** `Country Render Pipeline`
- **Standort:** Verzeichnis `R/`
- **Module:**
  - `R/data.R` — CSV-Loader, Share-Derivation, Trailing-12-Monate-Aggregation. Definiert Aggregations-Regeln: EREV→PHEV nur für 3-Kurven-Plot; HEV/MHEV/Petrol/Diesel/Gas/CNG/LPG → ICE. TTM startet erst wenn jede Spalte 12 vollständige Monate hat.
  - `R/fit.R` — Gewichtete Regression mit Time-History-Loop (`reg`/`reg_ice`/`optim` Aufrufe). **Mathematik byte-identisch zu historischer R-Implementation; darf nicht geändert werden** weil ältere Threshold-Werte reproduzierbar sein müssen.
  - `R/plots.R` — Vier ggplot2-Konstruktoren (BEV-Trajektorie, ICE/BEV/PHEV, Transition-Timer, TTM-Stack). Country-agnostisch über `meta`-Argument.
  - `R/upsert.R` — Line-level Upsert für `params.csv`/`weights.csv` (nur jeweils eine Zeile pro Lauf, kein Format-Drift in fremden Zeilen).
  - `R/render_country.R` — Entry-Point: `Rscript R/render_country.R <Country> [<Variant>]`. Lädt Daten, fittet, rendert vier PNGs nach `images/<period>/`, upsertet `params.csv` + `weights.csv`.
- **Lokale Ausführung:** Maintainer kann das Skript jederzeit in RStudio laufen lassen, Output landet identisch im Repo.
- **CI-Ausführung:** Über Render Action (siehe 3.5).

### 3.4 R Manifest-Builder
- **Name:** `Manifest Builder`
- **Datei:** `build_manifest.R`
- **Funktion:** Scannt `images/`, extrahiert Country/Variant/Period/Type pro PNG-Dateinamen, schreibt `manifest.json` (Index für die Gallery-Anzeige).

### 3.5 GitHub Actions
- **`Build manifest` (`.github/workflows/build-manifest.yml`):** Triggert auf Push zu `images/**` oder `build_manifest.R`. Installiert R, ruft `build_manifest.R`, committet `manifest.json`. Cron-Fallback täglich 03:17 UTC.
- **`Render country charts` (`.github/workflows/render-country.yml`):** Manueller Trigger via Actions UI (`workflow_dispatch`) mit Inputs `country` und `variant`. Installiert R + Pakete (`renv`-Cache empfohlen), ruft `R/render_country.R`, committet `images/`+`params.csv`+`weights.csv`. Triggert dadurch implizit den Manifest-Build.

### 3.6 GitHub Pages
- **Rolle:** Static Hosting für die Gallery. Auto-Deploy auf jeden Push zu `master`.

---

## 4. Data Objects (was wo gespeichert ist)

| Data Object | Standort | Format | Owner | Beschreibung |
|---|---|---|---|---|
| **Country Raw Data** | `data/<Country>.csv` (z.B. `data/Germany.csv`) | CSV (wide, sparse) | Maintainer / Submitter | Eine Zeile pro `(period, variant)`. Spalten: `period, time_interval, variant, source, BEV, PHEV, EREV, HEV, MHEV, PETROL, DIESEL, GAS, CNG, LPG, FLEXFUEL, ETHANOL, OTHERS, TOTAL, notes`. Pro Land nur die tatsächlich gemeldeten Spalten. **Single source of truth** für alle abgeleiteten Artefakte. |
| **Model Parameters** | `params.csv` (Repo-Root) | CSV | Render-Pipeline | Eine Zeile pro `(country, variant)` mit gewichteten Regressionsparametern: `v1, v2, t0` (BEV-Kurve) und `ice_v1, ice_v2, ice_t0` (ICE-Kurve), plus `data_per`, `model_date`, `source`, `baseline_date`. Wird vom Frontend für die Builder-Tab "What-if"-Berechnungen geladen. |
| **Aggregate Weights** | `weights.csv` (Repo-Root) | CSV | Render-Pipeline | Eine Zeile pro `(country, variant)` mit `weight` = Trailing-12-Months-Total. Wird für Welt-Aggregat-Berechnungen verwendet. |
| **Chart Images** | `images/<YYYY-MM>/<slug>_*.png` | PNG, 12.8×7.2 in @ 300 dpi (3840×2160 px für Trajektorie) | Render-Pipeline | Vier Plots pro Lauf: `<slug>.png`, `<slug>_ICE_BEV.png`, `<slug>_time.png`, `<slug>_ttm_shares.png`. `<slug>` = lower-case Country (+ Variant). Periode = neuester Datenpunkt. |
| **Image Manifest** | `manifest.json` (Repo-Root) | JSON | Manifest Builder | Indexed array of all images: `{country, variant, period, date, filename, url, alt}`. Vom Frontend bei jedem Page-Load gefetcht. |
| **Fleet Dataset** | `fleet/fleet_initial.csv`, `fleet_observed.csv`, `fleet_meta.json`, `hazard_defaults.csv` | CSV/JSON | Maintainer | Bestandsdaten + Hazard-Modell für Fleet-Tab. Eigener Datenkreis, separater Lifecycle. |
| **Assets** | `assets/flags/<slug>.png`, `assets/fonts/fontawesome/otfs/*.otf`, `assets/variant/*.png` | Binary | Maintainer | Pro Land eine Flagge, FontAwesome OTF-Dateien für Caption-Icons (X, Bluesky, Buy-Me-a-Coffee). Werden zur Render-Zeit in die Plots eingebettet. |
| **Feedback Issues** | GitHub Issues mit Label `feedback` | GitHub Issues | öffentlich | Diskussions-Threads mit Labels für Kategorie (`question`/`bug`/`idea`/`data`/`comment`) und Status (`hidden`, `pinned`). |
| **Submission PRs** | GitHub Pull Requests mit Branch `submit/<country>-<variant>-<timestamp>` | GitHub PRs | öffentlich vorgeschlagen, Maintainer entscheidet | Diff in genau einer `data/<Country>.csv` plus menschen-lesbarer Body mit Vorher/Nachher pro korrigierter Zeile. |
| **Rate-Limit Counters** | Cloudflare KV Namespace `RATE_KV`, Keys `rl:<ip>` (Feedback) und `sub:<ip>` (Submit) | KV (TTL 1 h) | Worker | Counter pro IP zur Drosselung. |

---

## 5. Interfaces & Integrationen

| From | To | Interface | Protokoll | Auth |
|---|---|---|---|---|
| Browser | GitHub Pages | HTTP GET der statischen Page + Assets | HTTPS | keine |
| Browser | Cloudflare Worker `/issues` | GET (Issues lesen), POST (Feedback erstellen) | HTTPS + JSON | CORS, Origin-Check (`leraffl.github.io`), Honeypot, Math-Captcha |
| Browser | Cloudflare Worker `/submissions` | POST | HTTPS + JSON | CORS, Honeypot, Rate-Limit (3/h/IP), Inhaltsvalidierung (Periode-Format, Sum-Check, Spalten-Allowlist) |
| Browser | GitHub Raw Content | GET `data/<Country>.csv` | HTTPS | keine (öffentliche Repo-Datei; vom Submit-Tab gefetcht um Schema dynamisch zu lesen) |
| Cloudflare Worker | GitHub REST API | Issues API (R/W), Contents API (R/W für CSVs), Git Refs API (Branch erstellen), Pulls API (PR erstellen) | HTTPS + JSON | Bearer Token (`GITHUB_TOKEN` Secret) |
| GitHub Actions Runner | GitHub Repo | git checkout + git push, Releases-API | HTTPS + Git | `GITHUB_TOKEN` (Workflow-scoped, automatisch von GitHub Actions) |
| GitHub Actions Runner | Posit Public Package Manager | R-Package-Download | HTTPS | keine |
| Maintainer (lokal) | GitHub Repo | git push (R-Skript-Output direkt vom Mac) | HTTPS + git | OAuth über macOS Keychain |
| Maintainer (lokal) | Google Sheets API | (legacy, optional) Sheet auslesen | HTTPS | OAuth (lokal) |

---

## 6. Schlüssel-Datenflüsse (Sequenzen)

### Flow A: Public-Submit eines Datenpunkts (neu)
1. Visitor öffnet "Submit Data" Tab → JS fetched `data/Germany.csv` von raw.githubusercontent, parst Header für Spalten-Schema, baut Form-Felder dynamisch.
2. Visitor füllt Formular (Country, Source, ein oder mehrere Rows mit Period/Interval/Fuel-Werten/Notes), klickt "Submit".
3. Browser POSTet JSON an Worker `/submissions`.
4. Worker validiert (Rate-Limit, Honeypot, Period-Format, BEV+PHEV+EREV ≤ TOTAL, erlaubte Fuel-Spalten).
5. Worker GETet aktuelle CSV via Contents API.
6. Worker führt Upsert per `(period, variant)` durch — neue Zeilen einfügen, existierende ersetzen.
7. Worker erstellt Branch `submit/<slug>-<ts>`, PUTtet neue CSV per Contents API, öffnet PR mit Pulls API.
8. Worker antwortet mit `pr_url`. Browser zeigt Erfolgsmeldung mit Link.
9. *Maintainer reviewt → mergt → triggert manuell die Render Action für das Land.*

### Flow B: Render eines Landes (manuell oder nach Submit-Merge)
1. Maintainer klickt in GitHub Actions UI "Render country charts" → Inputs Country + Variant.
2. Runner: checkout, Setup R, Install Pakete.
3. Runner: `Rscript R/render_country.R <Country> <Variant>`
4. Skript: lädt `data/<Country>.csv`, fitted Modell (`fit_history`), baut TTM, erzeugt vier Plots, schreibt PNGs in `images/<period>/`, upsertet `params.csv` + `weights.csv` (line-level, ein Zeilen-Diff).
5. Runner: committet `images/` + `params.csv` + `weights.csv`.
6. Push auf master triggert Build-manifest Action.
7. Build-manifest scannt `images/`, schreibt `manifest.json`, committet.
8. Push triggert GitHub Pages Deploy → Page aktualisiert sich nach wenigen Sekunden.

### Flow C: Lokales Rendern durch Maintainer (Legacy, weiter parallel verfügbar)
1. Maintainer öffnet altes per-country R-Skript (z.B. `bev_share_Germany_*.R`) in RStudio.
2. Skript liest aus Google Sheets *oder* aus `data/Germany.csv` (je nach Variante).
3. Skript erzeugt vier PNGs, schreibt sie nach iCloud + ins lokale Repo-Clone, committet, pusht.
4. Push triggert Build-manifest, Pages deployt.
*Diese Path bleibt funktional als Fallback und ist die historisch dominante Render-Form.*

### Flow D: Feedback einreichen
1. Visitor öffnet "Feedback & Questions" Tab oder klickt FAB-Button (überall sichtbar).
2. Modal mit Kategorie-Picker, Title, Body, Captcha.
3. POST an Worker `/issues` → Worker erstellt GitHub Issue mit Labels `feedback` + `feedback:<category>`.
4. Issue erscheint sofort im Tab (Worker invalidiert seinen 60-s-Cache).
5. Maintainer kann auf GitHub kommentieren → erscheint als Antwort im Tab; Status wird automatisch "answered" oder "resolved" (bei Issue-Close).

### Flow E: Manifest auto-rebuild
- Cron 03:17 UTC oder Push zu `images/**` → Action läuft → `manifest.json` neu geschrieben falls geändert. Selbstheilend wenn jemand manuell PNGs hinzufügt.

---

## 7. Technologie-Stack

| Layer | Technologie | Wo verwendet |
|---|---|---|
| Runtime: Edge | Cloudflare Workers (V8 isolate) | Worker `/issues` und `/submissions` |
| Runtime: CI | GitHub Actions (Ubuntu Runner) | Manifest-Build, Country-Render |
| Runtime: Static Hosting | GitHub Pages | Gallery |
| Sprache: Backend | JavaScript (ES Modules, Workers API) | Worker |
| Sprache: Frontend | Vanilla JS (ES2020), HTML5, CSS3 (kein Build) | `index.html` |
| Sprache: Datenpipeline | R 4.5+ | `R/*.R`, `build_manifest.R` |
| R-Pakete | `ggplot2, scales, grid, png, ggtext, viridis, showtext, sysfonts, glue, gert, readxl, dplyr, tidyr, patchwork, lubridate, jsonlite, fs, tibble, googlesheets4` (legacy) | siehe oben |
| Storage | Cloudflare KV | Rate-Limit Counter |
| Storage | Git LFS *(nicht im Einsatz)* | — |
| Storage | Repo-Files (CSV, JSON, PNG, OTF, R, JS, HTML) | alles dauerhafte |
| Auth | GitHub Fine-grained PAT | Worker → GitHub API |
| Auth | Cloudflare OAuth | Wrangler-CLI Auth lokal |

---

## 8. Externe Systeme

| System | Rolle | Owner | Vertrauensgrad |
|---|---|---|---|
| GitHub (Repo, Issues, PRs, Actions, Pages) | Source-of-Truth, CI/CD, Hosting, Diskussionsplattform | GitHub Inc. | hoch — Single Point of Failure für nahezu alles |
| Cloudflare (Workers, KV, OAuth) | Edge-Compute, Anti-Abuse | Cloudflare Inc. | hoch — ohne Worker keine Submit/Feedback-Funktionalität |
| Cloudflare Dashboard | Out-of-band Worker-Konfiguration (compatibility_date, observability, logs) | Maintainer | medium — Einstellungen werden in `wrangler.toml` gespiegelt |
| Posit Public Package Manager | R-Package-Quelle in CI | Posit | medium — Cache-fähig |
| Google Sheets | Legacy: Rohdaten-Quelle für Maintainer-lokalen R-Run | Maintainer | sinkt — wird durch `data/<Country>.csv` ersetzt |
| ACEA (acea.auto) | Zukünftige primäre Multi-Land-Quelle (geplant) | ACEA | extern, wird gescraped |
| Nationale Statistikquellen | Pro-Land-Rohdaten (KBA, ofv.no, statbank.dk, …) | jeweils national | extern, manuell ausgelesen |
| X (twitter.com), Bluesky, Buy-Me-a-Coffee | Outbound-Promotion + Spenden | extern | nur als Caption-Links |

---

## 9. Secrets & Trust Boundaries

| Secret | Standort | Inhalt | Reichweite |
|---|---|---|---|
| `GITHUB_TOKEN` (PAT) | Cloudflare Worker als Secret | Fine-grained PAT auf `LeRaffl/LeRaffl-Gallery` mit Scopes: Issues R/W, Contents R/W, Pull requests R/W, Metadata R | Worker kann Issues lesen/schreiben, CSVs ändern, Branches erstellen, PRs öffnen — aber **nicht direkt nach master pushen** (PR-only Pfad ist Architektur-Schutz) |
| `GITHUB_TOKEN` (workflow-scoped) | GitHub Actions Runner-Env | Auto-injected pro Workflow-Run | kann nach master pushen — Render-Action committet direkt; akzeptabel weil Action nur durch Maintainer triggerbar |
| Cloudflare API Token | macOS Keychain via Wrangler OAuth | Account-weite Worker-Verwaltung | nur Maintainer-Mac |
| Git Credentials | macOS Keychain | OAuth für `git push` | nur Maintainer-Mac |
| Google Sheets OAuth | Lokale R-Session | nur lesend | nur Maintainer-Mac, legacy |

**Trust-Boundaries:**
- *Public ↔ Worker*: Origin-Check, Rate-Limit, Honeypot, Captcha (für Feedback). Submit-Endpoint hat keinen Captcha aber Schema-Validierung + Rate-Limit. Maximaler Schaden eines Angreifers: Spam-PRs öffnen — Maintainer kann das durch Close ablehnen.
- *Worker ↔ GitHub*: Submit-Pfad öffnet ausschließlich PRs, nie direkter Push. Reviewer (Maintainer) ist menschliches Gate vor jedem Datenänderungs-Merge.
- *Action ↔ Repo*: Render-Action darf direkt pushen, weil sie nur durch authentifizierten Maintainer-Trigger läuft.

---

## 10. Was bewusst nicht (yet) im System ist

- **Multi-Country-Submit:** Aktuell nur Germany hat eine `data/<Country>.csv`. Weitere Länder folgen sukzessive durch Export aus dem Maintainer-Sheet.
- **ACEA-Scraper:** Geplant, noch nicht gebaut. Soll später als separater Worker oder GitHub Action wöchentlich ACEA-Press-Releases parsen und Submit-PRs vorschlagen.
- **Auth/Login:** Nicht vorgesehen. Submitter sind anonym, Maintainer ist GitHub-User.
- **Datenbank:** Nicht im Einsatz, alles file-basiert in Git. Audit-Trail = `git log data/<Country>.csv`.
- **Per-Variant-CSV-Splits:** Aktuell ist `data/Germany.csv` nur für Variante "Whole". Worker-Code unterstützt schon `data/<Country>_<Variant>.csv` für Custom/HDV/Private/etc. — kommt sobald entsprechende CSVs entstehen.

---

## 11. Naming-Konventionen für ADOIT

Damit das EAM-Modell konsistent wird:
- **Application Components** → benannt wie in §3 (`LeRaffl-Gallery Page`, `Cloudflare Worker`, `Country Render Pipeline`, `Manifest Builder`, `Build Manifest Action`, `Render Country Action`).
- **Data Objects** → benannt wie in §4 (`Country Raw Data`, `Model Parameters`, `Aggregate Weights`, `Chart Images`, `Image Manifest`, `Feedback Issues`, `Submission PRs`, `Rate-Limit Counters`).
- **Application Interfaces** → eindeutig per Endpoint (`Worker /issues GET`, `Worker /issues POST`, `Worker /submissions POST`, `GitHub REST Issues API`, etc.).
- **Business Processes** → die fünf Flows aus §6 (`Public-Submit`, `Country-Render`, `Local-Render-Legacy`, `Feedback-Submit`, `Manifest-Auto-Rebuild`).
- **Actors** wie in §2.
- **Technology Services** → `GitHub Pages Hosting`, `Cloudflare Workers Runtime`, `GitHub Actions Runtime`, `Cloudflare KV Storage`, `GitHub REST API`.

---

**Bei Rückfragen:** Architekt verfügbar im Originalprojekt-Chat. Repo: https://github.com/LeRaffl/LeRaffl-Gallery. Live: https://leraffl.github.io/LeRaffl-Gallery/. Worker: https://leraffl-gallery-feedback.xgwvfz7nrb.workers.dev.
