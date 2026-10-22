# 63 · The prebuilt R image (`ghcr.io/leraffl/r-render`)

Every workflow step that runs R does so inside one prebuilt Docker image,
`ghcr.io/leraffl/r-render:v<N>`, instead of installing R and the packages on
the runner in each job. This page says what is in the image, how it is built,
how to add a package, how to roll back, and the one-time GHCR setting.

Built from [`docker/r-render/`](../../docker/r-render/). Published by
[`build-r-image.yml`](../../.github/workflows/build-r-image.yml). Guarded by
[`scripts/check_r_image.py`](../../scripts/check_r_image.py) via
[`check-r-image.yml`](../../.github/workflows/check-r-image.yml).

## 1. Why

Until 2026-10 every R job ran `r-lib/actions/setup-r@v2` +
`setup-r-dependencies@v2`. Measured on the runs of 2026-10-15…22 that was about
**97 s per job** before any R code ran (setup-r ≈ 39 s, of which ≈ 27 s was
apt-installing devscripts/qpdf/ghostscript that nothing here uses; setup-r-dependencies
≈ 58 s, of which ≈ 32 s was apt system requirements — `dependencies: "all"`
resolved 149 packages and 24 system packages although the code needs 53).
`preview-render.yml` alone ran 479 jobs that week, so roughly 800 of its
1,327 job-minutes were setup. The image does that work once.

## 2. What is in the image

| Layer | Content | Pinned by |
|---|---|---|
| Base | `ubuntu:24.04` (noble) | digest in the `FROM` line |
| R | Posit's R build `r-4.6.1_1_amd64.deb` (same binaries setup-r installs) at `/opt/R/4.6.1`, `R`/`Rscript` on `PATH` | `R_VERSION` + `R_DEB_SHA256` |
| R packages | the 17 in [`packages.txt`](../../docker/r-render/packages.txt) with their **hard** dependencies only (`Depends`, `Imports`, `LinkingTo`) — 53 packages, all Posit Package Manager (P3M) binaries; `grid` ships with R | `P3M_SNAPSHOT` date (§4) |
| System libs | only what those binaries link against: freetype, libpng, zlib, libjpeg, libtiff, libwebp, harfbuzz, fribidi, fontconfig, libcurl, OpenSSL, ICU, libxml2, libuv | Ubuntu noble archive at build time (not snapshot-frozen, see §7) |
| Tools for the workflow steps | `git` (system `safe.directory '*'`, because container jobs run as root on a checkout owned by the runner user), `gh`, `python3`, `curl`, `ca-certificates`, `tzdata` | Ubuntu noble archive |

Environment: `LANG=LC_ALL=C.UTF-8`, `TZ=Etc/UTC`. `Rprofile.site` points
`repos` at the frozen P3M snapshot, so a stray `install.packages()` gets the
same versions. The image writes `/opt/r-render-packages.csv` (package,
version, repository) at build time; `build-r-image.yml` prints it in the job
summary.

**`ragg` is load-bearing although no script calls it.** `ggsave()` writes
PNGs through `ragg::agg_png` whenever ragg is installed, and through
`grDevices::png` otherwise. The old setup installed ragg as a Suggests of
ggplot2, so every chart saved with `ggsave()` (all `_ttm_shares` charts, and
all charts of series without a flag overlay) was rasterised by ragg; the charts
with a flag overlay go through `png()` directly. Without ragg those `ggsave()`
charts came out 0.3–2.7 % of pixels different (anti-aliasing). Keep it in
`packages.txt`.

**Fonts:** charts use `showtext`/`sysfonts`' bundled Liberation fonts, so no
system font packages are needed and none are installed.

Size (v1): 378 MB compressed (sum of the 7 layers in the GHCR manifest), about
0.96 GB uncompressed (local podman build: 962 MB); the job's "Initialize containers" step (pull + start)
took 17–19 s in the PR's preview runs.

## 3. How the workflows use it

| Workflow | How |
|---|---|
| `render-country.yml`, `preview-render.yml` (render job), `build-manifest.yml`, `ray-article-charts.yml`, `backfill-bands.yml` | job-level `container: image: ghcr.io/leraffl/r-render:v<N>` with `credentials` (`github.actor` / `GITHUB_TOKEN`) and `permissions: packages: read`. Every step — checkout, R, git, `EndBug/add-and-commit`, `gh`, `python3`, artifacts — runs in the container. |
| `snapshot-builder.yml` | the job stays on the runner (Python, pip Pillow); only the backtest step runs `docker run --rm -u "$(id -u):$(id -g)" -v "$GITHUB_WORKSPACE:/work" … Rscript …`, after a `docker/login-action` step |
| `runner-canary.yml` (render leg) | `scripts/runner_canary.py` wraps the render command in the same `docker run`; the `R (image)` version line comes from the image. This leg therefore now tests "can the new runner pull and run the image" instead of "does R install on the new runner OS" — R itself no longer changes with the runner image. |

`plan`/`collect` jobs of `preview-render.yml` and all Python-only workflows
are unchanged and still run on the runner.

## 4. Snapshot date and versions

`P3M_SNAPSHOT` (in the Dockerfile) is a date; P3M serves the CRAN state of that
day, so rebuilding the same `IMAGE_VERSION` gives the same package versions.
v1 uses **2026-10-21** with R **4.6.1**; at that date every package the image
shares with the old CI lockfile (2026-10-22) had the identical version
(ggplot2 4.0.3, scales 1.4.0, showtext 0.9-8, sysfonts 0.8.9, rlang 1.3.0,
ragg 1.5.2, systemfonts 1.3.2, textshaping 1.0.5, …).

To move to newer packages: change `P3M_SNAPSHOT` (and/or `R_VERSION` +
`R_DEB_SHA256`), bump `IMAGE_VERSION`, and compare renders (§6).

## 5. Rebuild, add a package

1. Edit `docker/r-render/packages.txt` (one package per line) and/or the
   Dockerfile.
2. **Bump `docker/r-render/IMAGE_VERSION`** (`1` → `2`) and change every
   `ghcr.io/leraffl/r-render:v1` in `.github/workflows/` (and the `R_IMAGE`
   values) to `:v2`. `check_r_image.py` fails the PR if either is missing.
3. Push the branch. `build-r-image.yml` runs on any push touching
   `docker/r-render/**` and publishes `:v2`, `:sha-<commit>`, `:<yyyymmdd>`
   (and `:latest` on master) **before** the PR is merged, so the PR's own
   preview render already runs on the new image.
4. An existing `vN` is never overwritten by a push (the job notices and skips);
   to rebuild one on purpose run the workflow by hand with `overwrite: true`.

Local build: `docker build -t r-render:dev docker/r-render` (podman works too),
then e.g. `docker run --rm -v "$PWD:/work" -w /work r-render:dev Rscript R/render_country.R Austria Whole`.

### Chicken-and-egg on the first build

The workflows reference the image by tag, so the tag must exist before they
run. Because `build-r-image.yml` runs on the PR branch push, v1 was published
from the PR branch, before the migration was merged. If a workflow ever fails
with `manifest unknown`, run **Build R image** manually on the branch.

## 6. Verifying an image change

Render the same series on the old and the new image and compare pixels, e.g.
dispatch `preview-render.yml` on master and on the branch with the same
`series` on the **same UTC day** (captions carry the render date), download
both artifacts and diff the PNGs. Also run `Rscript build_manifest.R` in the
image and check `git diff manifest.json` is empty.

## 7. Risks and limits

- **apt packages are not frozen**: Ubuntu security updates land on rebuild.
  They only affect libraries (freetype/libpng could in principle shift
  anti-aliasing); compare renders when rebuilding.
- **Package visibility**: after the first publish (2026-10-22) the package
  could already be pulled anonymously (it is linked to this public repo). The
  workflows log in with `GITHUB_TOKEN` + `packages: read` anyway, so they keep
  working if it is ever made private (§8); fork PRs could not pull it then.
- **Image pull** replaces R setup: 378 MB compressed per job (17–19 s).

## 8. One-time GHCR settings (owner)

After the first publish, on GitHub → profile → **Packages → r-render →
Package settings**:

1. **Manage Actions access**: make sure `LeRaffl/LeRaffl-Gallery` is listed
   (the build sets the `org.opencontainers.image.source` label, which links it
   automatically on the first push; check it anyway) with role **Read**
   (Write if it should also be able to publish — the build already has it as
   the creating repo).
2. **Visibility**: check it shows **Public** (an anonymous pull of `:v1`
   worked on 2026-10-22). Public is not needed for the workflows, but lets
   fork PRs and anyone without a token `docker pull` it; the repo is public
   anyway, and the image contains nothing secret.

## 9. Rollback

Revert the PR that introduced this page (or just the workflow files). The
previous setup, for reference — R jobs carried, before their first R step:

```yaml
      - uses: r-lib/actions/setup-r@v2
        with:
          use-public-rspm: true

      - uses: r-lib/actions/setup-r-dependencies@v2
        with:
          packages: |
            ggplot2
            scales
            grid
            png
            ggtext
            viridis
            showtext
            sysfonts
            glue
```

- `render-country.yml`, `preview-render.yml`, `runner-canary.yml` (render leg,
  with `id: r` / `id: rdeps`, `continue-on-error: true`, outcomes passed as
  `SETUP_R` / `SETUP_RDEPS`): the full list above.
- `build-manifest.yml`: `packages: jsonlite, stringr, dplyr, lubridate, purrr, fs, tibble, yaml`.
- `ray-article-charts.yml`: `ggplot2` and `scales`.
- `backfill-bands.yml`, `snapshot-builder.yml`: `setup-r` only (base R), and
  snapshot-builder ran `Rscript …` directly on the runner.

A rollback also has to drop `scripts/check_r_image.py`'s r-lib rule (or the
`check-r-image.yml` workflow), which otherwise fails the revert PR.
