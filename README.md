# SmartStreet

Street & road intelligence platform — a runnable implementation of the SmartStreet
architecture. Fetches live OpenStreetMap data for a bounding box, stores it in a
3-tier SQLite pipeline, computes network analytics (centrality, modeled flow,
emissions, noise, composite **StreetIQ**), and renders everything on an interactive
MapLibre dashboard.

## Quick start (Windows)

Double-click **`start.bat`**, or from a terminal in this folder:

```bat
start.bat
```

It creates a virtual environment, installs dependencies (first run only), starts
the server, and opens your browser at **http://localhost:8000**.

## Quick start (manual / macOS / Linux)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Then open **http://localhost:8000**.

> Requires Python 3.10+ and an internet connection (OpenStreetMap data is fetched
> live via the Overpass API, and basemap tiles come from OSM/Esri).

## Using it

1. Click **+ New Project (Draw BBox)** in the left sidebar.
2. Click **two corners** on the map to draw a bounding box (area + detail tier are
   shown live; must be ≤ 50 km²).
3. Name the project and click **Fetch OSM & Analyze**. Streets, pedestrian and
   cycling paths, transit routes/stops, POIs and buildings are downloaded, parsed
   and scored automatically.
4. Toggle layers, switch **Color streets by** (StreetIQ, centrality, flow, CO₂,
   noise, or road class), and click any feature for its attributes.
5. Adjust the **StreetIQ weight** sliders and click **Recompute StreetIQ** to
   re-rank streets in real time.
6. Projects are saved automatically — reopen any from the Projects list.

## What's implemented

- **City search** (type a place name → fly there / fetch it) via OSM Nominatim.
- **Progressive bbox tiers** (A ≤ 5 km², B 5–15, C 15–50) that adjust OSM query detail.
- **3-tier schema** (raw geometry → analytics → decisions) in SQLite.
- **Street analytics**: sampled betweenness/closeness centrality (NetworkX),
  capacity-based modeled flow, speed-dependent CO₂, noise model, weighted **StreetIQ**,
  and per-edge **data-quality** completeness.
- **Multimodal analytics**: pedestrian **walkability** and cycling **Level-of-Traffic-Stress**
  / bikeability, with the pedestrian and cycling layers colored by their own scores.
- **Time-of-day**: morning/midday/evening/night demand factors recolor flow, CO₂, noise.
- **Isochrones**: click a point → walk/cycle/drive reachability polygons (5/10/15 min).
- **Optimization engine**: signal placement (conflict index × centrality), connectivity
  gap finder (circuity), and a direction (one-way) solver — rendered as map overlays and
  ranked recommendation cards with confidence levels.
- **Scenario sandbox**: create scenarios, edit streets (close / make one-way / change
  speed), undo/redo, and compare against baseline (travel time, CO₂, one-way %, reachability)
  as a delta bar chart.
- **Exports**: streets CSV, streets GeoJSON, and a printable HTML report (print → PDF).
- **Dashboard**: MapLibre map, 7 toggleable layers, metric-driven coloring with legend,
  popups, summary metric cards, distribution histogram, region radar profile, project
  save/load, vector/satellite basemaps, and a polished dark UI.

## Deployment

See **`DEPLOY.md`**. Simplest free option: one Render service (Docker) serves both the
API and the UI. Split option: static frontend on Vercel + backend on Render.

## Project layout

```
backend/
  app.py         FastAPI app + REST API + static serving
  database.py    SQLite schema & connection layer
  osm.py         Overpass fetching + parsing (bbox tiers)
  analytics.py   NetworkX centrality, emissions, noise, StreetIQ
frontend/
  index.html     Dashboard shell
  app.js         Map, layers, drawing, panels
  style.css      Styling
run.py           Launcher (starts server + opens browser)
start.bat        One-command Windows start
requirements.txt
```

## Notes

- The database file `smartstreet.db` is created on first run in this folder.
- This is the Phase 1–2 foundation (digital twin + analytics). Optimization,
  scenarios, the AI layer and PDF reports from the architecture docs are the
  planned next phases.
