# 56 · Runner and action upgrades

Every fetch, render and build in this repo runs on GitHub-hosted runners. Two
kinds of platform change land on us from outside, on GitHub's schedule:

- **Action runtimes.** An action declares the Node.js version it runs on
  (`using: node20` in its `action.yml`). When GitHub retires a Node version,
  actions still on it first run with a warning, then are forced onto the new
  Node, then stop working.
- **Runner images.** `ubuntu-latest` moves to a new Ubuntu LTS about every two
  years, and each image updates weekly. A new LTS brings a different system
  Python, new versions of the apt tools our fetchers shell out to (tesseract,
  poppler, ImageMagick), and new system libraries under R and Chromium.

This page is the **risk register** for both: what could break, what it would
look like, how we'd notice, and what we do about it. Update it whenever a
risk materialises, gets mitigated, or a new one turns up.

## 1. Current state

| What | State | Since |
|---|---|---|
| Runner image | Every job pins **`runs-on: ubuntu-24.04`**, never `ubuntu-latest` | 2026-10 |
| Actions | All on Node 24 majors: `actions/checkout@v5`, `actions/setup-python@v6`, `actions/upload-artifact@v6`, `actions/download-artifact@v7`, `EndBug/add-and-commit@v10`, `r-lib/actions/*@v2` | 2026-10 |
| Next image | Ubuntu 26.04 (`ubuntu-latest` from November 2026). Compared monthly by the canary (§3); not adopted yet. First comparison in §5 | — |

Why we pin instead of following `ubuntu-latest`: several fetchers read their
numbers through OCR or `pdftotext`. A tool upgrade can change parsed values
without any step failing, which is worse than a red run. Pinning makes the OS
move a deliberate PR that we check first (§4). See also
[06-tech-stack.md § CI runner stack](06-tech-stack.md#ci-runner-stack).

## 2. Risk register

Status: **open** (could hit us, not yet handled), **mitigated** (handled; the
note says how), **watch** (accepted; the canary or a test would show it).

| # | Risk | Affects | What it would look like | How we'd notice | Status / mitigation |
|---|---|---|---|---|---|
| R1 | **OCR reads digits differently** after a tesseract upgrade (new model or engine defaults) | `fetch-turkey.yml` (Turkish), `fetch-china.yml` (simplified Chinese), `scripts/tuik_discover.py` | A plausible but wrong number in `data/Türkiye.csv` / `China*.csv`. No red run | Canary legs `turkey`, `china` (a CSV differs between images). Turkey also cross-checks year-to-date totals | **watch**: pinned to 24.04; canary monthly |
| R2 | **ImageMagick 7 drops or deprecates `convert`** (replaced by `magick`) | `fetch_turkey.py` upscales each page with `convert` before OCR | Turkey fails with `convert: not found`, or prints a deprecation warning that pollutes logs | Canary tool table: the `convert` row reads `(not found)`; the `turkey` leg goes red | **watch**: Ubuntu 26.04 ships ImageMagick 7.1.2 and still provides `convert` (an alternative pointing at `convert-im7.q16`), so the call works. If a later release drops it, call `magick` when it exists and fall back to `convert` |
| R3 | **`pdftotext -layout` changes column spacing** after a poppler upgrade | `fetch_italy.py`, `fetch_colombia.py`, `backfill_italy_rental.py`, `fetch_turkey.py` | A parser picks the wrong column or misses a row. Either a red run or a wrong number | Canary legs `italy`, `colombia` (Colombia also keeps the extracted text, so a layout shift shows even when the numbers agree). `test_fetch_italy.py` and `test_fetch_colombia.py` use stored text, so they would *not* catch it | **watch**: pinned; canary monthly |
| R4 | **Playwright cannot install Chromium's system libraries** on a new Ubuntu (`--with-deps` doesn't know the release, or apt package names changed) | `fetch-albania.yml` | Red run at "Install dependencies" | Canary leg `albania` (`pre` step fails on the next image only) | **watch**: Playwright is unpinned, so the newest release (which knows the newest Ubuntu) is what installs |
| R5 | **System Python changes** (3.12 → 3.14 on 26.04), and **PEP 668 blocks `pip install`** into it | `preview-render.yml` (`plan` uses `python3` without setup-python; `collect` runs `pip install pillow` into it) | Render preview on a PR goes red at `pip install` with `externally-managed-environment` | Canary leg `system-python` | **watch**: on the 26.04 runner image `pip install` into Python 3.14 works (2026-10-14). If it ever goes red, add `actions/setup-python@v6` to `collect` (and `plan`) |
| R6 | **R stack on a new image**: Posit Package Manager has no binaries for the new codename yet (source builds, much slower), different freetype/harfbuzz (PNG anti-aliasing), different libm/BLAS (last digits of the fit) | `render-country.yml`, `build-manifest.yml`, `snapshot-builder.yml`, `backfill-bands.yml`, `preview-render.yml` | Slow or failing `setup-r-dependencies`; PNGs that differ by a few pixels; `params.csv` numbers that differ in the 10th digit, or (bad) a different crossing year in a post | Canary leg `render`: `params.csv`, `bands/`, `posts/` compared with a tolerance (§3.2); PNGs listed as "compare by eye" | **watch**: `r-lib/actions@v2` already fixed one 26.04 issue (pak and `sudo`, v2.13.0) |
| R7 | **An apt package is renamed or removed** in the new release (as with the `t64` renames in 24.04) | Every workflow with `apt-get install`: turkey, china, italy, colombia, `backfill-italy-rental.yml` | Red run at the install step | Canary: the `apt` step fails on the next image only | **watch** |
| R8 | **The next Node.js deprecation** (Node 24 → 26 …) | All actions | Annotation `Node.js 24 is deprecated … forced to run on Node.js …` at the end of every job log | Read the warning; check each action's `action.yml` for `using:` | **mitigated for Node 20** (2026-10): repeat the same bump when the next warning appears |
| R9 | **The pinned image itself is retired.** GitHub supports the two newest LTS images; Ubuntu 22.04 entered deprecation in September 2026, about 4.5 years after release. Expect the same for 24.04 around 2028/29 | Every job | Brownout failures, then jobs that never start ("no runner matching labels") | GitHub's announcement in the runner-images README (linked at the top of every job's "Set up job" log) | **open**: migrate to 26.04 (§4) well before then |
| R10 | **Unpinned Python packages** change behaviour (`pdfplumber`, `pypdf`, `openpyxl`, `playwright`, `requests` are installed at their newest version on every run) | Every fetcher | A parser breaks or reads a table differently after a library release, independent of the OS | Partly: the `test_fetch_*.py` self-tests that run before some fetchers. The canary does **not** catch this (both images install the same version) | **watch**: pin a version only for the package that breaks, in that fetcher's workflow |
| R11 | **Floating action tags** (`@v2`, `@v5`, `@v10`) pick up the maintainers' new minor releases automatically | All workflows | A behaviour change without any commit here | The job's "Set up job" log names the resolved commit | **watch**: accepted. These are the maintainers' supported channels, and they carry fixes such as R6's |
| R12 | **The canary itself raises a false alarm**: the source publishes a new month, or a live count changes, between the two legs' fetches | Canary `fetch` legs | A red leg whose diff is a whole new row or a moving last month, on one image only | The diff in the report: a new period, not a different digit | **watch**: re-run the canary. A second identical red is real |
| R13 | **The canary itself passes without testing anything.** A fetcher that targets "last month" exits cleanly with "not published yet", changes nothing, and that looks exactly like "reproduces master" | Canary `fetch` legs | 🟢 "no changes" although no PDF was read and no OCR ran | Happened on the first run (2026-10-14): Turkey and Colombia were green but had parsed nothing | **mitigated**: every fetch leg now runs through `as-of` (§3.1), which removes the newest period first and fails the leg if it doesn't come back. "Fails on both images" is 🟡, never green |

## 3. The runner canary (`runner-canary.yml`)

[`.github/workflows/runner-canary.yml`](../../.github/workflows/runner-canary.yml)
with the logic in [`scripts/runner_canary.py`](../../scripts/runner_canary.py).
It runs on the 20th of each month (05:29 UTC), on manual dispatch (with
`base_image` / `next_image` inputs) and whenever the canary's own files change.
It has read-only permissions and never commits.

### 3.1 What it runs

One leg per target and image (2 × 7 jobs):

| Leg | What it runs (same commands as production) | Covers |
|---|---|---|
| `turkey` | `fetch_turkey.py --force` | R1, R2, R3, R7 |
| `china` | `fetch_china.py --force` | R1, R7 |
| `italy` | `fetch_italy.py --force` | R3, R7 |
| `colombia` | `fetch_colombia.py --force --debug-dir …` | R3, R7 |
| `albania` | `playwright install --with-deps chromium`, `fetch_albania.py` | R4 |
| `render` | `Rscript R/render_country.R Sweden Whole` after setup-r + the render package list | R6 |
| `system-python` | runner's `python3`, `pip install pillow`, compile `build_render_preview.py` | R5 |

Every fetch leg runs through `runner_canary.py as-of <csv> <fetcher> …`:

1. It finds the newest period master has in that CSV and **removes those rows**
   (a line-level edit; every other byte stays).
2. It runs the fetcher's `main()` with the fetcher's own `date` replaced, so
   that `date.today()` is the 15th of the month after that period. The fetcher
   targets "previous month", which is exactly the removed period, and has to
   download and parse it again. Only that one name in the fetcher's module is
   patched: the system clock, TLS and every library keep the real date.
3. If the rows don't come back, the leg fails ("tested nothing").

On a healthy image the rows come back byte for byte, which gives **no change
at all**. Both images fetch the same document within minutes, so if they
disagree, the cause is the OS, not the source. Without this, a leg run early in
the month, before the source has published last month, exits with "nothing
new" and looks exactly like a pass (R13).

Each leg records the exit code of every step instead of failing, the versions
of the tools in §2 (including whether `convert` / `magick` exist), and a copy
of every file the run changed. The `report` job compares the two images and
writes the verdict to the run summary (also kept as the `runner-canary-report`
artifact for 90 days; the legs' raw results for 30 days).

### 3.2 How to read the report

| Mark | Meaning | Fails the run? |
|---|---|---|
| 🟢 | Identical, no change on either image, or numbers equal within float noise (relative difference ≤ 1e-9) | no |
| ⚪ | Informational: a PNG differs (open both from the artifacts and compare by eye) | no |
| 🟡 | Small numeric drift (≤ 1e-4 relative); a step fails on the pinned image only; the main step fails on **both** images (the leg tested nothing: source down, or a fetcher problem); or a diagnostic file differs (e.g. Colombia's `pdftotext` dump changed layout while the parsed numbers agree) | no, but look before migrating |
| 🔴 | A step fails on the next image only, a leg produced nothing, or a published file (`data/`, `market/`, `params.csv`, `weights.csv`, `bands/`, `posts/`) differs in text or by more than 1e-4 relative | **yes** |

A 🔴 is a reason not to move the pin yet. It doesn't mean production is
broken: production stays on the pinned image. Fix the cause (or record why it
is acceptable in §2), then re-run the canary.

## 4. Moving to a new image (checklist)

1. Dispatch the canary with `next_image` set to the new label. It must be 🟢,
   or every 🟡/⚪ explained.
2. Fix every 🔴 on master first, in code that works on **both** images (for
   example R2: prefer `magick` when present). Re-run the canary.
3. One PR: replace `ubuntu-24.04` in every `runs-on:` (and the canary's
   `base_image`/`next_image` defaults and the `report` job), update §1 here and
   [06-tech-stack.md](06-tech-stack.md#ci-runner-stack). Validate with
   `actionlint`.
4. Expect a `chore: update manifest + schedule (CI)` commit on the PR branch:
   `build-manifest.yml` runs on any push that touches `.github/workflows/fetch-*.yml`,
   on every branch. It is regenerated on master anyway, so drop it before
   merging to keep the diff clean.
5. After merging, dispatch one OCR fetcher (Turkey) and one PDF fetcher
   (Italy) with `force`. Check that the commit, if any, contains no changed
   historical values.

## 5. Log

| Date | Change | Evidence |
|---|---|---|
| 2026-10-14 | Bumped the five actions still on Node 20 (`checkout` v4→v5, `setup-python` v5→v6, `upload-artifact` v4→v6, `download-artifact` v4→v7, `add-and-commit` v9→v10). Pinned all 94 jobs to `ubuntu-24.04`. Added the canary. Breaking changes checked against the actions' source: add-and-commit v10 only changes the runtime and drops a JSON-input parser that YAML parsing already covers; download-artifact v5 only changes downloads by artifact ID (we download by `pattern:`) | `build-manifest.yml` on the PR branch (checkout v5, setup-r, add-and-commit v10 with commit + push, on `ubuntu-24.04`): green, no Node 20 warning. Master's `fetch-sweden.yml` run the same day still ended with `Node.js 20 is deprecated … EndBug/add-and-commit@v9` |
| 2026-10-14 | First canary run, 24.04 vs 26.04 ([run 38565862816](https://github.com/LeRaffl/LeRaffl-Gallery/actions/runs/38565862816)). Tool versions on 26.04: tesseract 5.3.4 → 5.5.0, poppler 24.02 → 26.01, ImageMagick 6.9 → 7.1.2 (`convert` still present), system Python 3.12 → 3.14, R 4.6.1 on both, Playwright 1.64 on both. **Really tested and identical:** China (OCR re-read September; the same retail/wholesale values as master), Italy (`pdftotext` re-read September Whole/Rental/NonRental and the July/August vans PDFs, all unchanged), Albania (Playwright installed Chromium and re-read 2026, no change), the Sweden render (`params.csv`, `weights.csv` and all four PNGs byte-identical; Posit had binaries for 26.04), system Python (`pip install` works). **Not tested:** Turkey and Colombia targeted September, which isn't published yet, so they read no PDF. That is the canary bug R13, fixed the same day with `as-of` | Report job of that run |
