# 24 · Source: China (CPCA)

CPCA (*全国乘用车市场信息联席会*, the China Passenger Car Association) publishes a
monthly **market analysis** ("【月度分析】YYYY年M月份全国乘用车市场分析") on
`cpcaauto.com`. Each month's article reports **two tracks** — retail (零售) and
wholesale (批发) — in narrative `XXX.X万辆` form, plus a slide deck. The headline
retail BEV/PHEV/EREV split is **only available as an image** in that deck, which
makes China the one source in this project that depends on **OCR**. CPCA
publishes the previous month roughly between the **8th and 11th**.

This playbook is the "what actually happens with China" reference. Low-level
parsing details live in the `scripts/fetch_china.py` module docstring; this
file covers the shape, the gotchas, and the incident history so the next dev
(or LLM) doesn't have to re-derive any of it.

## TL;DR

```
Source:    CPCA monthly analysis article + slide deck
           https://www.cpcaauto.com/newslist.php?types=csjd&id=<id>
Auth:      None, but the host 403s bare requests → desktop User-Agent + a
           Referer of https://www.cpcaauto.com/ are required.
API:       None. Scrape the listing for "YYYY年M月份全国乘用车市场分析", follow to
           the detail page (?id=NNNN, a rotating CPCA-internal id), parse the
           narrative for TOTAL/NEV/ICE, and OCR a slide for the retail split.
Tracks:    Retail (零售)    → data/China.csv,          variant="Whole"
           Wholesale (批发) → data/China_Wholesale.csv, variant="Wholesale"
Units:     Article is in 万辆 (1万 = 10,000). CSVs store ABSOLUTE units.
Retail
 split:    CPCA does NOT print the retail BEV/PHEV/EREV breakdown in text —
           only the NEV aggregate. The split comes from OCR of the
           "新能源市场 … 零售、出口分析表" slide (tesseract -l chi_sim+eng).
Fallback:  If OCR can't read the slide, the split is approximated by applying
           the WHOLESALE BEV/PHEV/EREV mix to the retail NEV total
           ("ws-proportional"). This is a proxy and is systematically wrong
           (see §6). It is tagged in the row's `source` and is preserved-over,
           never overwritten, once a real value is in the CSV.
EREV:      Own column. From 2025-01 the narrow PHEV column EXCLUDES EREV
           (see the source-label suffix). OTHERS is always 0.
Schedule:  Daily cron 11:00 UTC, 1st→EOM; self-throttles via latest period
           already in each CSV (no-op until CPCA publishes).
Scripts:   scripts/fetch_china.py
Workflow:  .github/workflows/fetch-china.yml  (installs tesseract-ocr +
           tesseract-ocr-chi-sim)  → render-country.yml (Whole only)
```

## 1. Two metric tracks, two CSVs

CPCA reports both tracks in the same article:

- **Retail (零售)** — vehicles reaching end consumers in mainland China during
  the month (≈ registrations). This is the headline series →
  `data/China.csv`, `variant="Whole"`.
- **Wholesale (批发)** — manufacturer shipments to dealers, **including exports
  and inventory build-up**, so it runs 20–40 % higher than retail →
  `data/China_Wholesale.csv`, `variant="Wholesale"`.

Both CSVs share the canonical column set
(`period,time_interval,variant,source,BEV,PHEV,EREV,OTHERS,ICE,TOTAL,notes`) and
are upserted in the **same** `fetch_china.py` run. Only **Whole (retail)** is
auto-rendered (`render-country.yml`); wholesale is captured for a separate
downstream model and is **not** rendered yet.

> Naming trap: the retail file's variant is `"Whole"` (as in "whole market"),
> *not* "wholesale". Wholesale lives in the `_Wholesale.csv` file. Confusing
> these is the single easiest mistake to make here.

## 2. What is parsed from text vs. from the image

| Field | Retail | Wholesale |
|---|---|---|
| TOTAL | narrative (`全国乘用车市场零售 X万辆`) | narrative (`乘用车厂商批发 X万辆`) |
| NEV aggregate | narrative (`新能源乘用车零售 Y万辆`) | narrative |
| ICE | narrative, or TOTAL − NEV | narrative, or TOTAL − NEV |
| **BEV / PHEV / EREV** | **OCR of the NEV slide** (or fallback) | **narrative** (`纯电动批发`, `狭义插混`, `增程式批发`) |

So **wholesale BEV/PHEV/EREV is read straight from the article text** and is
reliable. The retail split is the only OCR-dependent value, because CPCA never
restates it in prose.

## 3. The retail-split OCR pipeline

The detail page embeds ~10 JPG slides (`admin/ewebeditor/uploadfile/*.jpg`).
One — usually deck page 6, titled `新能源市场-YYYY年M月零售、出口分析表` — is a
table with explicit retail and export breakdowns by fuel:

```
零售            BEV    PHEV   EREV   NEV          出口   BEV   PHEV  EREV  NEV
5月份           63.7   22.8   8.5    95.0         5月份  25.2  15.4  12.3  42.4
4月份           57.8   19.1   7.6    84.5         …
```

`fetch_china.py` downloads each slide and OCRs it until one row reconciles
against the article's retail NEV total. The important, hard-won details:

- **Language matters more than resolution.** Pure `tesseract -l eng`
  mis-segments this teal-banded table and **garbles the digit cells** — May
  2026's `63.7 / 22.8 / 8.5 / 95.0` came out as `3 45 55.6 7`. Loading the
  Simplified-Chinese model (`-l chi_sim+eng`) anchors the table structure and
  the numbers read cleanly. **This is why the workflow installs
  `tesseract-ocr-chi-sim`.**
- **Self-validating config ladder.** `OCR_CONFIGS` lists
  `(scale, lang)` pairs tried in order — `6x chi_sim+eng` first, then 5x/4x,
  then a legacy `4x eng`. For each slide we try each config until
  `_extract_retail_from_ocr` returns a row whose `BEV+PHEV+EREV ≈ NEV` **and**
  `NEV ≈ the article's retail NEV total` (`_recover_decimal`). A wrong config
  simply fails that cross-check, so trying several is safe — we can never
  silently accept a misread table (e.g. the wholesale one).
- **Decimal recovery.** OCR sometimes drops the decimal point (`57.9` → `579`)
  or splits it into two tokens (`37` `8`). `_recover_decimal` /
  `_merge_split_decimals` reconstruct it by enforcing the NEV sum.
- **Diagnostic logging.** When a month-label line matches but the tokens don't
  reconcile, the run prints `DEBUG OCR: …` lines, and a clean hit logs
  `OCR matched <file> [<config>] … BEV=.. PHEV=.. EREV=.. NEV=..`. If you ever
  need to know why a month went to the fallback, read the
  "Fetch & update China CSVs" step log.

## 4. The ws-proportional fallback (and how to override by hand)

If **no** slide/config reconciles, `build_rows` derives the retail split by
applying the wholesale mix to the retail NEV total:

```
retail_bev = retail_nev * ws_bev  / (ws_bev + ws_phev + ws_erev)
retail_phev = …  ; retail_erev = …
```

Such a row is tagged `source = "CPCA (…) [BEV/PHEV/EREV: ws-proportional]"`.
This is a **proxy**, not the truth (§6 shows how far off it can be). Two
safety rails exist:

- **`preserve_split`** (in `upsert_csv`): a ws-proportional run will **not**
  overwrite an existing row that already has BEV/PHEV/EREV filled in. So a
  good value (OCR or hand-entered) is never clobbered by a later proxy run.
- **Manual override.** To correct a month by hand: read the four retail
  numbers off the CPCA NEV slide (万), multiply by 10,000, and edit
  `data/China.csv`, dropping the `[ws-proportional]` suffix from `source`.
  `preserve_split` then protects your values on subsequent runs.

To re-pull a specific month once OCR is fixed/CPCA republished:
`fetch_china.py --force --id <NNNN>` (or via the workflow's `workflow_dispatch`
inputs `detail_id` + `force`).

## 5. Rendering & the post % bands (EREV ⊆ PHEV)

`render-country.yml` → `R/render_country.R China Whole` fits the Weibull model,
updates the `China` rows in `params.csv` + `weights.csv`, writes four PNGs under
`images/<period>/`, and generates `posts/china.txt` (+ periodised
`posts/china_<period>.txt`).

EREV is a **special case of PHEV** (a range-extender is a plug-in hybrid),
exactly as HEV is a special case of ICE. The CSV stores EREV in its **own
additive column** — `BEV + PHEV(narrow) + EREV + ICE = TOTAL`, and the China
source label notes "PHEV excludes EREV from 2025-01" — so anything that reports
a PHEV figure must **add EREV back in** to get the broad PHEV. The canonical
rollup lives in `R/data.R` (drives the BEV/PHEV/ICE plot):

```r
phev_share <- (phev + erev) / total              # EREV folded into PHEV
ice_share  <- (total - bev - phev - erev) / total  # EREV kept OUT of ICE
```

The post bands (`R/post_text.R` `.pt_triplet_lines`) follow the same rule:

```
bev        = BEV / TOTAL
phev_broad = (PHEV + EREV) / TOTAL
ice        = 1 - bev - phev_broad
line2      = "<phev_broad>% PHEV (of which <EREV/TOTAL>%p were EREV)"
```

So the corrected May 2026 row (BEV 637k, PHEV 228k, EREV 85k, ICE 560k,
TOTAL 1,510k) renders as:

```
42.2% BEV
20.7% PHEV (of which 5.6%p were EREV)
37.1% ICE
```

— bands sum to 100 %, and the post `ICE %` equals the CSV `ICE/TOTAL` (37.1 %).

> **History / regression note.** Before the May-2026 fix, `post_text.R` used the
> *narrow* PHEV column and `ice = 1 - bev - phev`, which silently left the EREV
> share inside the displayed **ICE** band (e.g. the stale on-disk
> `posts/china_2026-05.txt` shows `17.3% PHEV` + `41.5% ICE` instead of
> `21.7% PHEV` + `37.1% ICE`). EREV is non-zero **only for China**, so this bug
> was China-only; every other country has `EREV = 0`, where `phev_broad == phev`
> and nothing changes. Fixed alongside the OCR work. The stale post refreshes on
> the next render — see §7.

## 6. Postmortem — the May 2026 "42.2 % BEV" incident

**Symptom.** A user reported China May-2026 at **42.2 % BEV**; the gallery
showed **41.2 %**.

**Cause.** The scheduled fetch ran on a runner where the retail-slide OCR
failed (`tesseract -l eng` garbled the digits to `3 45 55.6 7`, which the NEV
cross-check correctly rejected), so the row silently fell back to
**ws-proportional**. The wholesale mix is not the retail mix, so *all three*
NEV columns were off:

| | ws-proportional (wrong) | CPCA slide (correct) | Δ |
|---|---|---|---|
| BEV | 622,099 | **637,000** | +14,901 (41.2 % → **42.2 %**) |
| PHEV | 261,197 | **228,000** | −33,197 |
| EREV | 66,704 | **85,000** | +18,296 |

(Wholesale for May was correct — read from text: BEV 886k / PHEV 372k / EREV
95k.)

**Fix.** (1) Corrected the May retail row by hand from the official slide
(63.7 / 22.8 / 8.5 / 95.0 万). (2) Root-caused the OCR and switched it to
`chi_sim+eng` with a self-validating config ladder, so the split is **read**,
not proxied, going forward. Verified end-to-end on a live runner:
`OCR matched … [6x chi_sim+eng] … BEV=63.7 PHEV=22.8 EREV=8.5 NEV=95.0`.

**Lesson.** The ws-proportional fallback was failing **silently** — the only
trace was a single `WARNING … falling back` line nobody reads. It is now far
more visible via the `DEBUG OCR` lines, and OCR is reliable, but the fallback
still exists as a last resort, so a sudden China BEV that looks "smooth"
relative to wholesale is the tell to check the fetch log.

## 7. Gotchas

- **`variant="Whole"` is retail**, not wholesale. (§1)
- **OCR needs `chi_sim`.** Without the `tesseract-ocr-chi-sim` apt package the
  retail split silently degrades to the ws-proportional proxy. (§3)
- **Rotating detail ids.** `?id=NNNN` is CPCA-internal and sequential; never
  hard-code it — discover it from the listing, or pass `--id` for a backfill.
- **403 on bare requests.** A desktop `User-Agent` + `Referer` are mandatory.
- **Silent fallback.** "Nothing to commit" on a forced re-run does **not** by
  itself prove OCR worked — `preserve_split` keeps a good row stable even when
  the run fell back. Confirm via the `OCR matched …` log line. (§4, §6)
- **EREV ⊆ PHEV in the post.** The PHEV band is the broad figure (narrow PHEV +
  EREV); EREV must never leak into the ICE band. This was a China-only bug until
  the May-2026 fix — guard it if you touch `R/post_text.R`. (§5)
- **Schedule/manifest noise.** Dispatching `fetch-china.yml` on a feature
  branch can trigger downstream workflows that auto-commit `schedule.ics` /
  `schedule*.html` (`build-manifest.yml`). Those don't belong in a China PR —
  drop them before merging.
