---
country: Türkiye
slug: turkiye
status: live
method: api
summary: >-
  New passenger-car registrations for Türkiye from TÜİK's monthly
  "Motorlu Kara Taşıtları" bulletin.
source_name: "TÜİK — Motorlu Kara Taşıtları (monthly bulletin)"
source_url: "https://veriportali.tuik.gov.tr/tr"
underlying: "TÜİK — Türkiye İstatistik Kurumu (Turkish Statistical Institute)"
auth: none
cadence: "daily 08:30 UTC, 15th–31st, commit-gated"
variants: [Whole]
scope_note: "Passenger cars (otomobil) only — the one vehicle category TÜİK breaks down by fuel type."
hev_note: "Hybrids are a single combined bucket, placed in the HEV column; PHEV is left empty."
backfill: none
column_map:
  Benzin: PETROL
  Hibrit: HEV
  Elektrik: BEV
  Dizel: DIESEL
  LPG: OTHERS
  Toplam: TOTAL
notes:
  - "Türkiye's figures come from TÜİK, the Turkish Statistical Institute. Every month TÜİK publishes a bulletin called \"Motorlu Kara Taşıtları\" (Motor Land Vehicles) reporting how many vehicles were newly registered, usually around the middle of the following month. As the country's official statistics body, TÜİK counts every registration — this is a complete record, not a survey or an industry estimate."
  - "The bulletin covers all vehicle types, from motorcycles to buses, but only passenger cars are broken down by fuel. That breakdown is what the gallery uses, which is why Türkiye's chart counts cars only."
  - "We read each new bulletin from TÜİK's data portal as soon as it appears and match it by the month it reports on, so a bulletin is never mistaken for a different month. The headline totals are taken from the bulletin's own text. The fuel breakdown, however, is published as a picture of a table rather than as text, so those five numbers have to be read off the image — and are then checked three separate ways before anything is saved."
  - "Those three checks are: the fuel figures must add up to the total TÜİK states in the text; each fuel's share must match the percentage TÜİK prints next to it; and the previous-year comparison column in the same table must match what we already hold for that month. If any check fails, the update stops and nothing is published — a missing month is better than a wrong one."
caveats:
  - "Hybrids are reported as one combined bucket (the Türkiye/Georgia convention), placed in the HEV column. Plug-in hybrids cannot be separated out."
  - "The fuel split is transcribed from an image of a table, not read from structured data. The three cross-checks above are what make that trustworthy; a transcription that fails any of them stops the update rather than publishing an uncertain figure."
  - "Only the most recent month is written, so if TÜİK later revises an earlier month, that revision is not picked up."
  - "Passenger cars only. Motorcycles, vans, trucks and buses are excluded, even though TÜİK reports them."
fetcher: "scripts/fetch_turkey.py"
workflow: ".github/workflows/fetch-turkey.yml"
fragility_doc: "docs/architecture/33-source-turkiye.md"
data_file: "data/Türkiye.csv"
---

# 33 · Source: Türkiye (TÜİK Veri Portalı bulletin API)

TÜİK publishes **Motorlu Kara Taşıtları** monthly. The fuel split for
`otomobil` (passenger cars) is the slice we want. Everything below the
front-matter is developer-facing; the front-matter is what renders to
`sources/turkiye.html` for gallery readers.

## TL;DR

```
Source:    TÜİK Veri Portalı — Motorlu Kara Taşıtları monthly bulletin
Portal:    https://veriportali.tuik.gov.tr/tr/press/<id>     (React SPA shell)
API:       GET https://veriportali.tuik.gov.tr/api/tr/press/<id>
           Accept: application/json
Auth:      None. Cookies only (GA + NetScaler), issued by fetching the press
           page first — warm_session() in scripts/tuik_discover.py
Response:  {"data": {"id", "number", "date", "title", "period", "content"},
            "isError", "message"}                              (~340 KB)
Discovery: id is NOT supplied by hand. Walk ids outward from the newest one in
           the CSV's `source` column, match title=="Motorlu Kara Taşıtları"
           AND period=="<Month> <Year>"       (scripts/tuik_discover.py)
Parse:     `content` is the bulletin HTML. Totals come from its prose; the fuel
           table is a raster image embedded as an inline data: URI, decoded and
           OCR'd at 4/6/8× (imagemagick + tesseract-tur)
Variant:   Whole (passenger cars only)
Cadence:   Daily days 15-31, 08:30 UTC; commit-gated; self-throttled on the
           CSV's latest period
Scripts:   scripts/fetch_turkey.py, scripts/tuik_discover.py
Workflow:  .github/workflows/fetch-turkey.yml
```

## 1. Why discovery is not "last id + 1"

The bulletin ids are **not chronological**. Observed:

| id | period |
|---|---|
| 58041 | Mart 2026 |
| 58042 | Nisan 2026 |
| 58043 | **Haziran** 2026 |
| 58044 | **Mayıs** 2026 |
| 58051 | Ocak 2026 |

All five are the same series. Incrementing from the last known id would have
fetched Haziran while asking for Mayıs. The narrative month-check would have
caught it and refused to write, but only after a full OCR round-trip.

There is no index to query. Every listing shape probed returns a plaintext
404 (`Sayfa bulunamadı`): `/api/tr/press`, `/api/tr/press/list`,
`/api/tr/presses`, `/api/tr/search`, `/api/tr/categories`, `/api/tr/themes`,
`/api/tr/press/<id>/metadata`.

So `_via_id_scan()` walks outward from an anchor — `+1, -1, +2, -2, …` up to
`SCAN_AHEAD`/`SCAN_BEHIND` — and matches on **both** `title` and `period`.
Period alone repeats across series; title alone repeats across months. The
anchor is parsed from the newest `…/press/<id>` URL in the CSV's `source`
column, so it re-derives itself every month and no id is hard-coded. Because
the series occupies a contiguous block, the normal case costs one request.

## 2. Why there is no PDF in the loop

`GET /tr/press/<id>` returns the SPA shell (~3.7 KB, empty `<title>`), not the
bulletin. There is **no known id → PDF mapping**. A latent bug in the original
fetcher handed that URL to `load_pdf_bytes()`, so `--press-id` could never have
worked on its own — pypdf received `<!doc` as its header. It had gone unnoticed
because the workflow was only ever dispatched *without* an id. That branch now
exits with an explanation instead.

`--pdf-url` / `--pdf-path` remain for feeding a PDF in by hand; the discovery
path never uses them.

## 3. Parsing the bulletin

`data.content` is the full bulletin HTML. Two things come out of it:

**Prose → totals.** `html_to_text()` strips tags, then the existing narrative
regexes pull the authoritative monthly and YTD totals:

```
"<Month> ayında X bin Y adet otomobilin trafiğe kaydı yapıldı"
"Ocak-<Month> döneminde trafiğe kaydı yapılan Z bin W adet otomobilin"
```

**Images → fuel table.** `Benzin` appears nowhere in the markup — TÜİK ships
the table as a raster image in the HTML exactly as it does in the PDF. But the
images are inline `data:` URIs, so `extract_images_from_html()` decodes them
straight out of the JSON. The declared mime type is unreliable (JPEG payloads
labelled `image/png`), so the extension comes from magic bytes.

`parse_content_tables()` still tries real markup first. It costs nothing when
it fails and would be the better path if TÜİK ever emits a genuine table.

### Multiple fuel tables per bulletin

A bulletin contains **two** fuel breakdowns under identical row labels: the
month's registrations, and the registered stock at month end. Picking the first
one writes ~17.8 million stock vehicles instead of ~73,665 registrations — and
it looks entirely plausible. `iter_fuel_table_images()` therefore yields *every*
image carrying all six labels, and the caller keeps the table whose `Toplam`
matches the narrative total.

### OCR upscale roulette

Each image is offered at **4×, 6× and 8×**. One factor is a single roll of the
dice on a low-resolution source. Haziran 2026 at 4× produced a row sum that
missed `Toplam`; the repair heuristic tried to pin the difference on LPG
(1155, implying 1.6 % against an OCR'd Pay% of 0.9 %) and the cross-check
rejected it. At a larger upscale the percentage column read correctly and
everything reconciled — **the count had been right all along; the *percentage*
was the misread.**

## 4. Validation

The HTML path emits the same `{label: (counts, pcts)}` shape as the OCR path,
so every existing guard applies unchanged:

1. `Toplam[col 1]` == narrative monthly total — hard fail.
2. `Sum(Benzin..LPG, col 1)` == `Toplam[col 1]` — single-error auto-repair via
   the Pay% cross-check; multi-fuel mismatches hard-fail.
3. Each fuel's `count/Toplam` == OCR'd Pay% ± 0.05 %.
4. `cross_check_prev_year()` — col 0 (previous-year same month) must match the
   row already in the CSV. Catches column-shift bugs the others would pass.

A failure is a red run, deliberately. A missing month is recoverable; a wrong
month quietly enters the charts.

## 5. Verification of the 2026-05 / 2026-06 backfill

Checked against TÜİK's own published cumulatives rather than only internally.
Ocak–Haziran 456,050 minus Ocak–Mayıs 382,385 = **73,665**, exactly the Haziran
total written. Back-computing each fuel from the published cumulative
percentages:

| fuel | derived | written | Δ |
|---|---|---|---|
| Benzin | ~34,998 | 35,114 | 116 |
| Hibrit | ~20,984 | 21,140 | 156 |
| Elektrik | ~10,818 | 10,617 | −201 |
| Dizel | ~5,746 | 5,639 | −107 |
| LPG | ~1,119 | 1,155 | 36 |

Every gap is inside what one-decimal percentages permit (±0.05 % of 456,050 is
±228 on its own).

## 6. Investigated and rejected

* **`data.tuik.gov.tr`** (the legacy server-rendered portal, cited as `source`
  for every CSV row up to 2026-03) — folded into the SPA. Both a search URL and
  a known-good 2025 bulletin now return the same 1,947-byte shell.
* **`sitemap.xml`** — 1,810 bytes, top-level routes only, no press ids.
* **`nsiws.tuik.gov.tr` SDMX** — `HTTP 401 Unauthorized`. Behind Keycloak
  (`giris.tuik.gov.tr/realms/web/protocol/openid-connect/token`); needs an API
  key from a verified portal account. Tracked in issue #171. This would replace
  OCR outright and make revisions visible, so it remains the preferred target.
* **`veriportali.tuik.gov.tr/api/en/data/downloads?t=i&p=<payload>`** — used
  without auth by the R package [`emraher/tuikr`](https://github.com/emraher/tuikr).
  The `p` parameter is encoded but constructible. Unexplored fallback if the
  SDMX account never materialises.

`robots.txt` is fully permissive — a single `Allow: /` covering the wildcard
and every named crawler, AI agents included.

## 7. Operational notes

* `TUIK_RECON=1` (or the workflow's `recon` input) dumps a reconnaissance pass:
  SPA chunk-graph crawl, API-literal extraction, endpoint probing. Use it when
  discovery starts missing — the portal has already changed shape once.
* The daily cron self-throttles on the CSV's latest period, so it is a silent
  no-op until the new bulletin lands.
* Following the project rule, only the most recent month is written. TÜİK does
  occasionally revise earlier months; those revisions are not picked up, and
  SDMX (§6) is the route to fixing that properly.
