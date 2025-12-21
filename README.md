
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

## 🧠 The model – explained without math pain (revised & precise)
1. What is being modelled

For each country, I model the BEV share of new car registrations over time.
Empirically, this share does not behave like random noise.
It behaves like a structured transition process: slow start, acceleration, eventual stabilization.
The model is therefore not trying to “predict the future”, but to describe the structure of the transition as observed so far.


2. Why an S-curve at all?

Most large-scale technology transitions follow a similar qualitative pattern:
- early friction (costs, infrastructure, trust)
- positive feedback loops once adoption takes off
- diminishing returns as edge cases remain

This produces curves that are monotonic, bounded, and nonlinear.
An S-shape is not assumed because it is pretty, it is assumed because it is the simplest structure that repeatedly matches real transitions. We've seen transitions between technologies in the past and this shape just fits.


3. Why not a normal distribution (clarified)

A normal distribution can, in fact, be fitted to cumulative adoption data like this.
The problem is not fit quality per se. The problem is structure.

A normal distribution is:
- symmetric by construction
- unable to express asymmetric acceleration/deceleration
- unable to “break” as visibly when the data stops behaving like a transition

In other words:
A normal distribution is just less suited.


4. Why a Weibull / generalized logistic formulation
The Weibull-style formulation is chosen for three reasons:

(1) Asymmetry
Real-world adoption curves are almost never symmetric. The Weibull allows early-heavy, late-heavy, or roughly symmetric transitions — all with the same functional form.

(2) Failure visibility
A Weibull does not HAVE to produce an S-curve. It could yield other shapes as well. It just doesn't because the data fits S-shapes best.
If the data does not support a meaningful transition, the model can:
- fail to converge
- produce nonsensical parameters (NaN, ±∞)
- collapse into degenerate shapes
This is a feature, not a bug.

Example:
Markets like Japan, which show no clear BEV transition, cause the model to break — exactly where it should. These examples are rare though. At time of writing I know of exactly 2 cases: Japan and Croatia

(3) Parameter parsimony
The model uses two shape parameters.
fewer → insufficient flexibility
more → unstable estimation and overfitting
Two parameters are a sweet spot, flexible enough to reflect reality, constrained enough to remain interpretable.


5. What the parameters mean (conceptually)
v1 — transition intensity
Controls how aggressively the market moves once adoption starts.
Intuitively: How sharp is the flip from “niche” to “mainstream”?

v2 — transition shape
Controls where acceleration happens.
Intuitively: Does the market ramp up early, or only after a long hesitation phase?

t0 — time shift
It's a horizontal shift so the curve aligns nicely with calendar time. Ignore this one.


6. Most important model assumption
Two hard assumptions are imposed:
- The transition starts at 0%
- The transition asymptotically ends at 100%

Technically these are assumptions. However, would we not assume these we'd introduce either less stable models or subjective models (which goes against what I want this to be).
However, both the 0% and the 100% seem to fit reality. Would they not fit reality, models would eventually output nonsense. If real data contradicts these bounds, the model stops fitting and this breakdown is visible.
So far, mature markets (e.g. Norway) genuinely converge towards 100%, not 80% or 90%


7. This is a statement about TODAY
This deserves to be absolutely unambiguous:

This is not a forecast.
This is not a prediction.
This is not a statement about the future.

The curve represents a best-fit description of the transition as of today. If future data changes the trajectory also changes, which is why I update it regularly.
The parameters change, the curve changes, the derived thresholds change.

Think of it as:
“Given everything we know right now,
what would the transition look like if things simply continued?”

Not:
“What will happen?”


8. Early-stage instability
Uncertainty is not only a function of data quantity. It is also a function of where a market sits on the curve. Early-stage markets (low BEV share) are inherently volatile. Small absolute changes produce large parameter swings. This stabilizes naturally as the transition progresses. This stabilization is visible in the transition-time curves. Stability is also greater in bigger markets.

---

## 🌍 License & Usage

Charts and model outputs may be shared freely with attribution to **@LeRaffl**.
Original data sources are subject to their respective licenses.
Feel free to use these outputs for your own purposes, but please link me to whatever you do.

---

