# BEV Trajectories — Files you need

Put these into your repo root:

- `index.html` — the gallery UI (EN)
- `build_manifest.R` — generates `manifest.json` by scanning `images/YYYY-MM/`
- `images/` — create monthly subfolders like `images/2025-07/` and put charts there
- `.nojekyll` — optional file to disable Jekyll on GitHub Pages

## Usage
1) Export your charts into `images/<YYYY-MM>/...png` (or `.webp`).
2) In R:
   ```r
   source("build_manifest.R")
   build_manifest(root = "images", base_url = "images/")
   ```
   This writes `manifest.json` next to `images/`.
3) Commit & push. GitHub Pages will serve `index.html` and the gallery reads `manifest.json`.

The UI filters by **country**, **type**, **period** and has a **Latest only** toggle (shows only the newest per country+type when no month is selected).
