# R render image for LeRaffl-Gallery CI.
#
# What: Ubuntu 24.04 (the same OS as the ubuntu-24.04 runners) + R 4.6.1 from
# the very .deb that r-lib/actions/setup-r installs + the HARD dependencies of
# every R package list the workflows used to install with
# setup-r-dependencies, as P3M binaries from a frozen date snapshot.
# Why:  setup-r + setup-r-dependencies cost ~97 s per job (mostly apt),
#       for 16-22 s of actual rendering.
# Docs: docs/architecture/63-r-render-image.md (rebuild, add a package,
#       bump the snapshot, rollback).
#
# Any change here MUST bump docker/r-render/IMAGE_VERSION (the build workflow
# refuses to overwrite an existing version tag) and the `:vN` tag in every
# workflow that uses the image (scripts/check_r_image.py enforces both).

# Ubuntu 24.04 ("noble"), pinned by digest so a rebuild starts from the same base.
FROM docker.io/library/ubuntu:24.04@sha256:a2d43bffc46670d7108bb3c0468c67c5557c4c92e83e1e34cbff1322ad1b94dc

ARG R_VERSION=4.6.1
ARG R_DEB_SHA256=5af816371126c8e5895600de035153cd3a64b12f4beb43f291ee34bf24f8fd2d
# Posit Package Manager (P3M) snapshot date: every CRAN package version is
# frozen to what CRAN had on this day. Bump it deliberately (doc 63 §4).
ARG P3M_SNAPSHOT=2026-10-21

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Etc/UTC

# System tools the workflow steps run INSIDE the container:
#   git            actions/checkout (a real clone, not the REST fallback),
#                  EndBug/add-and-commit, preview-render's git checkout/clean
#   gh             render-country.yml "Trigger manifest build"
#   python3        runner-canary.yml's render leg (scripts/runner_canary.py, stdlib only)
#   curl, ca-certificates   R's download.file (QR code) and HTTPS in general
#   tzdata, locales         R / lubridate time zones
# Runtime libraries of the R packages below (P3M binaries link against them):
#   libfreetype6 libpng16 zlib (showtext, sysfonts, png), libjpeg8 (jpeg),
#   libcurl4 libssl3 (curl/openssl via markdown deps), libicu74 (stringi),
#   libxml2, libuv1 (fs).
RUN apt-get update -qq \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git gh python3 tzdata locales gdebi-core \
      libfreetype6 libpng16-16t64 zlib1g libjpeg8 libcurl4t64 libssl3t64 \
      libicu74 libxml2 libuv1t64 \
 && curl -fsSL -o /tmp/r.deb "https://cdn.posit.co/r/ubuntu-2404/pkgs/r-${R_VERSION}_1_amd64.deb" \
 && echo "${R_DEB_SHA256}  /tmp/r.deb" | sha256sum -c - \
 && apt-get install -y --no-install-recommends /tmp/r.deb \
 && ln -sf /opt/R/${R_VERSION}/bin/R /usr/local/bin/R \
 && ln -sf /opt/R/${R_VERSION}/bin/Rscript /usr/local/bin/Rscript \
 && rm -f /tmp/r.deb \
 && apt-get purge -y gdebi-core && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Every job's checkout is owned by the runner user while the container runs as
# root; without this git refuses the repo ("dubious ownership") in every step
# after actions/checkout.
RUN git config --system --add safe.directory '*'

# Package repo for this image: the P3M Linux-binary snapshot. Set in Rprofile.site
# so any later install.packages() in a workflow uses the same frozen snapshot.
# The HTTPUserAgent line is what makes P3M serve Linux binaries instead of sources.
RUN RHOME="$(Rscript -e 'cat(R.home())')" \
 && printf '%s\n' \
    "options(repos = c(CRAN = 'https://packagemanager.posit.co/cran/__linux__/noble/${P3M_SNAPSHOT}'))" \
    "options(HTTPUserAgent = sprintf('R/%s R (%s)', getRversion(), paste(getRversion(), R.version\$platform, R.version\$arch, R.version\$os)))" \
    "options(Ncpus = 4L)" \
    >> "${RHOME}/etc/Rprofile.site"

# The union of the package lists the workflows installed with
# setup-r-dependencies, HARD dependencies only (Depends/Imports/LinkingTo):
#   render-country / preview-render / runner-canary: ggplot2 scales png ggtext
#     viridis showtext sysfonts glue   (grid is base R)
#   build-manifest: jsonlite stringr dplyr lubridate purrr fs tibble yaml
#   ray-article-charts: ggplot2 scales
# snapshot-builder and backfill-bands need base R only.
COPY packages.txt /tmp/packages.txt
RUN Rscript -e ' \
      pkgs <- setdiff(trimws(readLines("/tmp/packages.txt")), ""); \
      pkgs <- pkgs[!startsWith(pkgs, "#")]; \
      install.packages(pkgs, dependencies = c("Depends", "Imports", "LinkingTo")); \
      missing <- pkgs[!vapply(pkgs, requireNamespace, logical(1), quietly = TRUE)]; \
      if (length(missing)) stop("not installed: ", paste(missing, collapse = ", ")); \
      ip <- installed.packages()[, c("Package", "Version", "Built")]; \
      write.csv(ip[is.na(installed.packages()[, "Priority"]), ], "/opt/r-render-packages.csv", row.names = FALSE)' \
 && rm -f /tmp/packages.txt

# Fail the build if a package that needs a system library cannot load it
# (a missing runtime lib would otherwise only surface in a render).
RUN Rscript -e 'for (p in read.csv("/opt/r-render-packages.csv")$Package) suppressPackageStartupMessages(library(p, character.only = TRUE)); cat("all packages load\n")'

LABEL org.opencontainers.image.source="https://github.com/LeRaffl/LeRaffl-Gallery" \
      org.opencontainers.image.description="R ${R_VERSION} + gallery render packages (P3M snapshot ${P3M_SNAPSHOT}) for LeRaffl-Gallery CI"
