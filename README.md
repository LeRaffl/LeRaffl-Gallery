
# BEV Trajectories · @LeRaffl

This repository powers the public **BEV Trajectory Gallery**, an interactive dashboard that visualizes electric-vehicle transition dynamics for countries around the world.

▶ **Open the live gallery:**  
https://leraffl.github.io/LeRaffl-Gallery/#gallery

The gallery is updated continuously and provides, for each country:

- 📈 **BEV transition trajectories** (fitted logistic / Weibull-style curves)
- 🔄 **ICE↔BEV market-share transition charts**
- 🟫 **TTM (trailing-twelve-month) market-split graphs**
- ⏱️ **Transition-time curves** (speed of change between thresholds)

In addition, the dashboard includes two analytical views:

- **Thresholds** — When does a market reach 20%, 50%, 80% BEV share?  
- **Durations** — How long does it take to move from one share level to another (e.g., 20→80%)?

All computations run purely **client-side** in the browser.

---

## 🚀 Project Purpose

Many countries follow an S-curve when transitioning from internal-combustion engines to battery-electric vehicles.  
This project aims to make these transitions **comparable, transparent, and publicly accessible**, using a consistent modelling approach across all markets.

Inputs include:

- Monthly new-registration data (sources include ACEA, KBA, CPCA, Statistik Austria, and others)
- A generalized logistic (Weibull-like) model
- Harmonized modelling assumptions for cross-country comparability

Outputs:

- PNG charts for each country and month
- A parameter table (`params.csv`) containing all fitted model parameters
- A machine-generated gallery manifest (`manifest.json`)

---

## 📂 Repository Structure

Key files in the repository root:

| File | Purpose |
|------|---------|
| **index.html** | The full interactive UI (Gallery, Thresholds, Durations). Runs 100% in the browser. |
| **manifest.json** | Auto-generated list of all available charts, used by the Gallery to display images. |
| **build_manifest.R** | Scans `images/` and generates `manifest.json`. |
| **params.csv** | Contains the model parameters (v1, v2, t0, baseline year, last data month) for each market. Used for Thresholds & Durations. |
| **log_params.R** | Produces and updates the parameter table (`params.csv`). |
| **images/** | Contains all exported PNG files structured as `images/YYYY-MM/...`. GitHub Pages serves them directly. |
| **.github/workflows/build-manifest.yml** | CI workflow ensuring that `manifest.json` always stays up to date. |

---

## 🖼️ How the Gallery Works

When opening `index.html`, the browser loads:

1. **manifest.json** — the full list of charts  
2. **params.csv** — all relevant model parameters  
3. Renders everything dynamically

### Gallery
- Filter by country, date, chart type, filename  
- Lightbox preview and direct download  
- “Latest only” mode automatically selects the newest chart per type/country (there may be several even for a single month, e.g. when I'm cleaning up or trying something)  

### Thresholds
- Computes 20%, 50%, 80% share dates + any custom threshold  
- Based on the fitted model parameters  
- Exportable as CSV  

### Durations
- Estimates transition durations (20→80%, 10→90%, custom X→Y%)  
- Includes the numerical speed at the inflection point  
- Exportable as CSV  

---

## 🔧 Data Generation (Overview)

Charts are generated locally using R scripts.  
The workflow:

1. Monthly registration data is ingested and modelled  
2. PNG charts are exported to the images folders by my locally run R scripts
3. `build_manifest.R` scans the directory → produces `manifest.json`
4. `params.csv` is carrying relevant output parameters from each model
5. GitHub Galerie shows updated gallery using the manifest as a guide of what to show with what filter
6. Github Thresholds and Durations are calculated on your device using the parameters from the R output cached in params.csv

The tables calculate thresholds and durations live.

---

## 🌍 License & Usage

Charts and model outputs may be shared freely with attribution to **@LeRaffl**.
Original data sources are subject to their respective licenses.
Feel free to use these outputs for your own purposes, but please link me to whatever you do.

---

