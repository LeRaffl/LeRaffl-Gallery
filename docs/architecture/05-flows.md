# 05 · Flows

End-to-end sequence diagrams for every meaningful user journey or background process. If you're adding a new flow, copy one of these as a template.

## Flow inventory

| # | Flow | Trigger | Outcome |
|---|---|---|---|
| A | [Public-submit a data point](#flow-a--public-submit) | Visitor fills Submit Data form | PR opened, awaiting maintainer review |
| B | [Render a country](#flow-b--render-a-country) | Maintainer triggers Render Action | New PNGs + posts + params row |
| C | [Local-render legacy](#flow-c--local-render-legacy) | Maintainer runs R in RStudio | Same outputs as Flow B, pushed directly to master |
| D | [Submit feedback / question](#flow-d--feedback-submit) | Visitor fills feedback modal | New GitHub Issue with labels |
| E | [Auto-rebuild manifest](#flow-e--manifest-rebuild) | Push to images/** or daily cron | Updated manifest.json |
| F | [Visitor reads gallery](#flow-f--gallery-read) | Page load on leraffl.github.io | Manifest + images displayed |
| G | [Copy post text](#flow-g--copy-post) | Click "📋 Copy post" or run Apple Shortcut | Text in clipboard |
| H | [Auto-ingest Brazil from ANFAVEA](#flow-h--anfavea-ingest) | Monthly cron (10th, 08:00 UTC) or manual dispatch | Updated `data/Brazil.csv` → triggers Flow B for Brazil |
| I | [Auto-ingest Chile from ANAC](#flow-i--anac-ingest) | Daily cron (14th–end of month, 08:00 UTC) or manual dispatch | Updated `data/Chile.csv` → triggers Flow B for Chile |

---

## Flow A — Public-submit

```mermaid
sequenceDiagram
    actor Visitor
    participant Page as Static Page
    participant Worker as Cloudflare Worker
    participant KV as RATE_KV
    participant GH as GitHub API
    actor Maintainer

    Visitor->>Page: Open Submit Data tab, pick Country
    Page->>GH: GET raw/data/<Country>.csv
    GH-->>Page: CSV content (or 404 → fallback schema)
    Page->>Page: Render dynamic form fields per CSV header
    Visitor->>Page: Fill rows, source, click Submit

    Page->>Worker: POST /submissions {country, variant, source, rows[]}
    Worker->>KV: GET sub:<ip>
    KV-->>Worker: counter (or null)
    alt Rate-limited
        Worker-->>Page: 429
    else OK
        Worker->>KV: PUT sub:<ip> = counter+1, ttl=3600
        Worker->>Worker: Validate honeypot, schema, sums
        Worker->>GH: GET /contents/data/<Country>.csv?ref=master
        GH-->>Worker: file content + sha
        Worker->>Worker: Apply per-row upsert by (period, variant)
        Worker->>GH: GET /git/ref/heads/master
        GH-->>Worker: master sha
        Worker->>GH: POST /git/refs (new branch from master sha)
        Worker->>GH: PUT /contents/data/<Country>.csv (on new branch)
        Worker->>GH: POST /pulls (open PR against master)
        GH-->>Worker: PR url + number
        Worker-->>Page: 201 {pr_url, summary}
    end
    Page->>Visitor: "Thanks! PR #N opened, X added, Y corrected"

    Maintainer->>GH: Review PR diff
    Maintainer->>GH: Merge PR
```

**After this flow:** the country's `data/<Country>.csv` on master has the new/corrected rows, but no new images yet. The maintainer triggers Flow B next to refresh PNGs and post text.

**Key constraints:**
- Worker has Contents+PRs scope but the only write the page can trigger is "open PR" — it cannot push directly to master (no permission was granted; even the API endpoints called are PR-only).
- Branch naming `submit/<slug>-<timestamp>` makes it easy to pick out submission PRs from regular dev branches.

---

## Flow B — Render a country

```mermaid
sequenceDiagram
    actor Maintainer
    participant GHUI as GitHub Actions UI
    participant Runner as Action Runner (Ubuntu)
    participant Repo as GitHub Repo
    participant Pages as GitHub Pages

    Maintainer->>GHUI: Run "Render country charts" with country=Germany
    GHUI->>Runner: dispatch
    Runner->>Repo: actions/checkout
    Runner->>Runner: setup-r + install ggplot2/scales/grid/png/ggtext/viridis/showtext/sysfonts/glue
    Runner->>Runner: Rscript R/render_country.R Germany Whole

    Note over Runner: Inside the R script:<br/>1. load_country_csv(data/Germany.csv)<br/>2. fit_history(df) → params, history-loop<br/>3. build_post_text(df, "Germany")<br/>4. plot_bev_trajectory / plot_ice_bev_phev / plot_timer / plot_ttm_shares<br/>5. ggsave 4 PNGs to images/<period>/<br/>6. upsert_params, upsert_weights<br/>7. writeLines posts/<slug>.txt, posts/<slug>_<period>.txt

    Runner->>Repo: git add images/ params.csv weights.csv posts/
    Runner->>Repo: git commit -m "chore: render Germany (Whole)"
    Runner->>Repo: git push origin master
    Runner->>Repo: gh workflow run build-manifest.yml

    Repo->>Pages: deploy hook
    Pages->>Pages: serve updated assets
```

After this, Flow E (manifest rebuild) is explicitly dispatched by the Render-country workflow. Direct maintainer pushes to `images/**` still trigger Flow E through the path filter. The manifest commit then pushes to `master`, which GitHub Pages auto-deploys (Pages-from-branch; no separate Pages workflow exists or is needed).

**Performance notes:**
- Cold runner: ~2 min including R-package install
- Warm runner (cached binaries): ~30 s
- The R history-loop iterates `optim` once per data row × 2 (BEV + ICE). For Germany (~135 rows): ~3 s. For Norway (~250 rows): ~6 s.

---

## Flow C — Local-render legacy

```mermaid
sequenceDiagram
    actor Maintainer
    participant RStudio
    participant GS as Google Sheets
    participant LocalRepo as Local clone
    participant Repo as GitHub Repo

    Maintainer->>RStudio: source(bev_share_<Country>.R)
    RStudio->>GS: read_sheet(<sheet_url>)
    GS-->>RStudio: data frame
    RStudio->>RStudio: fit + plot + post-text (same logic, copied to per-country script)
    RStudio->>LocalRepo: writeLines images/<period>/<slug>_*.png
    RStudio->>LocalRepo: upsert params.csv, weights.csv
    RStudio->>LocalRepo: writeLines posts/<slug>.txt, posts/<slug>_<period>.txt
    RStudio->>Repo: git add + commit + push (via gert)
    Repo->>Repo: build-manifest workflow triggers on images/** push
```

**Why this exists at all (context for engineers):**
- Outputs are byte-compatible with Flow B — same filenames, same params row format, same posts format. So commits to master can come from either path without confusing downstream consumers.
- This path is being phased out as more data flows directly through Submit → PR → Render Action. Eventually Flow B becomes the only render path. Any new feature in `R/*.R` should be designed assuming Flow B is the canonical path.

---

## Flow D — Feedback submit

```mermaid
sequenceDiagram
    actor Visitor
    participant Page as Static Page
    participant Worker as Cloudflare Worker
    participant KV as RATE_KV
    participant GH as GitHub Issues
    actor Maintainer

    Visitor->>Page: Click FAB or "New topic"
    Page->>Visitor: Open feedback modal, generate captcha question
    Visitor->>Page: Fill title/body/category/captcha, submit

    Page->>Worker: POST /issues {title, body, category, captcha, context, version}
    Worker->>KV: GET rl:<ip>
    KV-->>Worker: counter
    alt Rate-limited
        Worker-->>Page: 429
    else
        Worker->>Worker: Validate honeypot, lengths, captcha
        Worker->>GH: POST /issues with labels feedback + feedback:<category>
        GH-->>Worker: issue object
        Worker->>Worker: Invalidate /issues cache
        Worker-->>Page: 201 mappedIssue
    end
    Page->>Visitor: Show new issue inline in Feedback tab

    Maintainer->>GH: (later) Comment / close
    Note over GH: Page's GET /issues picks up<br/>the comment + status change<br/>on next refresh (60 s cache)
```

---

## Flow E — Manifest rebuild

```mermaid
sequenceDiagram
    participant Repo as GitHub Repo
    participant Action as Build-manifest Action
    participant Runner as Action Runner

    Note over Repo,Action: Trigger sources (any one of):<br/>• Render-country explicit dispatch<br/>• push to images/**<br/>• push to build_manifest.R<br/>• daily cron 03:17 UTC<br/>• manual workflow_dispatch
    Repo->>Action: workflow trigger
    Action->>Runner: dispatch
    Runner->>Repo: checkout
    Runner->>Runner: setup-r + install jsonlite/stringr/dplyr/lubridate/purrr/fs/tibble
    Runner->>Runner: Rscript build_manifest.R
    Runner->>Runner: scan images/, derive country/variant/period/type per filename
    Runner->>Runner: write manifest.json
    Runner->>Repo: git add manifest.json
    Runner->>Repo: git commit (only if changed)
    Runner->>Repo: git push
```

---

## Flow F — Gallery read

```mermaid
sequenceDiagram
    actor Visitor
    participant Browser
    participant Pages as GitHub Pages
    participant Repo as GitHub Repo

    Visitor->>Browser: navigate to leraffl.github.io/LeRaffl-Gallery
    Browser->>Pages: GET /
    Pages-->>Browser: index.html
    Browser->>Pages: GET manifest.json (no-store)
    Pages-->>Browser: JSON
    Browser->>Browser: build Gallery cards from manifest.images
    par (in parallel for each visible card)
        Browser->>Pages: GET images/<period>/<slug>_*.png
        Pages-->>Browser: PNG
    end
    par (on tab switch)
        Browser->>Pages: GET params.csv (Builder/Thresholds/Durations/Map)
        Pages-->>Browser: CSV
    end
```

This flow is intentionally trivial. **Any change that adds a backend dependency to the read path is a regression.** The page is read-side static; only the write side (Submit, Feedback) goes through the Worker.

---

## Flow G — Copy post

Two variants: in-page button, and Apple Shortcut. Both fetch the same URL.

### G.1 In-page

```mermaid
sequenceDiagram
    actor Visitor
    participant Page as Static Page
    participant Pages as GitHub Pages
    participant Clipboard

    Visitor->>Page: Click "📋 Copy post" on a Germany card
    Page->>Clipboard: clipboard.write([ClipboardItem(text/plain → blobPromise)])
    Page->>Pages: GET posts/germany.txt (no-store)
    Pages-->>Page: text/plain (resolves blobPromise)
    Page->>Visitor: Button briefly shows "✓ Copied"
```

`clipboard.write()` is invoked synchronously inside the click handler — passing a `Promise<Blob>` to `ClipboardItem` lets the fetch resolve afterwards without losing Safari's user-gesture context. An older `await fetch(...) → clipboard.writeText(text)` chain throws `NotAllowedError` on Safari and iOS for exactly that reason.

### G.2 Apple Shortcut

```mermaid
sequenceDiagram
    actor Maintainer
    participant Shortcuts as Apple Shortcuts
    participant Raw as raw.githubusercontent.com
    participant Clipboard

    Maintainer->>Shortcuts: Tap "BEV Post Picker"
    Shortcuts->>Maintainer: Choose from Menu (country list)
    Maintainer->>Shortcuts: Pick "Germany"
    Shortcuts->>Raw: GET /LeRaffl/LeRaffl-Gallery/master/posts/germany.txt
    Raw-->>Shortcuts: text/plain
    Shortcuts->>Clipboard: Copy
    Shortcuts->>Maintainer: Notification "Germany post copied"
```

**Why two paths to the same artefact:** the in-page button is for visitors and casual mobile/desktop use; the Shortcut is for the maintainer's posting workflow on iOS where launching Safari is more friction than tapping a Shortcut on the home screen.

## Flow H — ANFAVEA ingest

Brazil is the first country with an automated, source-side ingestion. ANFAVEA publishes one Excel workbook per year (`siteautoveiculos<YEAR>.xlsx`) covering production, registrations, exports, and employment. We only consume sheet "III. Emplacamento Combustível" — the cars + light-commercial fuel-split table.

```mermaid
sequenceDiagram
    participant Cron as GitHub Actions (cron / dispatch)
    participant Job as fetch-brazil.yml job
    participant Site as anfavea.com.br
    participant CSV as data/Brazil.csv
    participant Render as render-country.yml

    Cron->>Job: workflow_dispatch OR cron (10th 08:00 UTC)
    Job->>Site: GET /site/edicoes-em-excel/ (browser UA)
    Site-->>Job: HTML index
    Job->>Job: regex match siteautoveiculos<year>(-N)?.xlsx
    Job->>Site: GET /docs/siteautoveiculos<year>.xlsx
    Site-->>Job: xlsx bytes
    Job->>Job: Open sheet "III. Emplacamento Combustível"<br/>locate "Unidades" header → month row → fuel rows
    Job->>Job: Map Portuguese fuel labels → CSV columns<br/>(Elétrico→BEV, Híbrido Plug-in→PHEV, Híbrido→HEV,<br/>Gasolina→PETROL, Diesel→DIESEL, Flex Fuel→FLEXFUEL)
    Job->>Job: Skip months where all fuel values are 0
    Job->>CSV: Upsert by period; warn on >50% delta vs existing
    alt CSV changed
        Job->>Render: gh workflow run render-country.yml -f country=Brazil
    else No change
        Job-->>Cron: Exit cleanly, nothing committed
    end
```

**Where parsing lives:** [scripts/fetch_brazil.py](../../scripts/fetch_brazil.py). The module docstring is the authoritative reference for the parsing rules, column map, and how the script handles partial-year data.

**Why a browser User-Agent:** ANFAVEA's Apache returns HTTP 406 for `python-requests/*`. We send a Chrome desktop UA + standard `Accept` / `Accept-Language` headers on both calls.

**Why not the trucks/buses table:** sheet III has a second "Caminhões e Ônibus" block below the cars block. It uses a different fuel taxonomy (Elétrico/Gás/Diesel only) and isn't represented in `data/Brazil.csv`'s schema. The parser only walks the FIRST "Unidades" header and stops at the closing "Fonte:" marker, so the trucks table is naturally skipped.

**Adding more countries:** the pattern (`fetch-<country>.yml` → `scripts/fetch_<country>.py` → commit + dispatch render) is intentionally country-local rather than generic, because each statistics agency has its own URL scheme, file layout, and quirks. Duplicate and adapt rather than parameterise prematurely.

## Flow I — ANAC ingest

Chile follows the same `fetch-<country>` pattern as Brazil, with one twist: ANAC publishes **two** PDFs per month and they don't appear at the same time. The cron runs daily from the 14th onward and the script self-throttles via the CSV's latest period — most invocations are a no-op.

```mermaid
sequenceDiagram
    participant Cron as GitHub Actions (cron / dispatch)
    participant Job as fetch-chile.yml job
    participant Site as anac.cl
    participant CSV as data/Chile.csv
    participant Render as render-country.yml

    Cron->>Job: workflow_dispatch OR cron (daily 14–31, 08:00 UTC)
    Job->>CSV: read latest period
    alt Latest period ≥ target month
        Job-->>Cron: Exit cleanly (no-op)
    else Target month missing
        Job->>Site: GET /category/estudio-de-mercado/ (browser UA)
        Site-->>Job: HTML listing PDFs
        alt Either PDF missing
            Job-->>Cron: Exit cleanly (no-op, retry tomorrow)
        else Both PDFs present
            Job->>Site: GET Mercado Automotor + Cero y Bajas Emisiones PDFs
            Site-->>Job: PDF bytes
            Job->>Job: Parse TOTAL + BEV/PHEV/HEV via pypdf
            Job->>CSV: Append target-month row (ICE = TOTAL − BEV − PHEV − HEV)
            Job->>Render: gh workflow run render-country.yml -f country=Chile
        end
    end
```

**Where parsing lives:** [scripts/fetch_chile.py](../../scripts/fetch_chile.py). The module docstring documents the regex patterns, the MHEV-into-ICE convention, and the no-partial-writes rule.

**Why two PDFs:** ANAC splits the headline market total (Mercado Automotor) from the alternative-drivetrain breakdown (Cero y Bajas Emisiones). Both are needed to fill one CSV row; partial writes would produce wrong charts because BEV/PHEV/HEV would default to 0 and inflate ICE.

**Why MHEV → ICE:** ANAC reports mild-hybrids (Microhíbridos) as a separate line that didn't exist historically and isn't in `data/Chile.csv`'s schema. Per maintainer's call we bucket them into ICE via the implicit subtraction (`ICE = TOTAL − BEV − PHEV − HEV − OTHERS`) rather than introducing a new column.

## See also

- [04-interfaces.md](04-interfaces.md) — request/response shapes for each Worker call shown above
- [02-components.md](02-components.md) — the boxes in the diagrams
- [08-deploy-ops.md](08-deploy-ops.md) — how to invoke Flow B, how to debug Flow A failures
