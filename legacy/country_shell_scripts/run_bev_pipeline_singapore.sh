#!/usr/bin/env bash
set -e

# echo "Hello LeRaffl, Script läuft 🎉"

# 1. Ins Singapore-Projekt wechseln
cd "/Users/leraffl/Projects/bev_share_singapore"

# 2. R-Skript ausführen
/usr/local/bin/Rscript bev_share_Singapore_20251231.R

# 3. In den PNG-Ordner in iCloud wechseln
cd "/Users/leraffl/Library/Mobile Documents/com~apple~CloudDocs/R/bev_share_singapore"

# 4. Neuestes PNG finden
latest_png=$(ls -t singapore_202*.png | head -n 1)

# 6. Für Shortcuts ausgeben
echo "LATEST_PNG:$latest_png"
