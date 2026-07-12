# SmartStreet — Street & Road Intelligence Platform

> **Version**: 0.1.0-draft  
> **Last Updated**: 2026-07-11  
> **Status**: Pre-implementation (Architecture & Planning)

A layered, open-data-driven platform for fetching, analyzing, and simulating urban streets, public transit, cycling, and pedestrian networks. The system uses a structured database-centric pipeline to transform raw geospatial data into combined calculations, producing actionable urban design decisions.

---

## Table of Contents

1. [3-Tier Pipeline Architecture](#3-tier-pipeline-architecture)
2. [OSM Ingestion & Progressive Bounding Box Loading](#osm-ingestion--progressive-bounding-box-loading)
3. [Project Save & Load](#project-save--load-workspace-persistence)
4. [Dual Spatial Representations](#dual-spatial-representations-network-vs-grid)
5. [Relational Database Schema](#relational-database-schema)
6. [Network Models & Optimization Theories](#network-models--optimization-theories)
7. [UI Dashboard Design](#ui-dashboard-design)
8. [Output Pipeline & Modular Report System](#output-pipeline--modular-report-system)
9. [Phased Roadmap](#phased-roadmap)
10. [Open Questions & Future Developments](#open-questions--future-developments)

---

## 3-Tier Pipeline Architecture

All data, computations, and outputs are organized into three tiers. This separation ensures every new data source, analysis model, or decision output has a clear place, and that future extensions don't break existing flows.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        3-Tier Data Pipeline                            │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  TIER 1: RAW DATA DATABASES                                            │
│  ├── OSM Street Geometry       ├── Pedestrian Sidewalks/Crossings      │
│  ├── OSM Public Transit Lines  ├── Cycling Infrastructure              │
│  ├── Transit Stops & Stations  ├── Points of Interest (Amenities)      │
│  ├── Building Footprints       ├── Air Quality Sensor Readings         │
│  ├── Weather & Climate Data    ├── Base Demographics & Elevation       │
│  │                                                                     │
│  ▼ (Spatial Joins & Mathematical Models)                               │
│                                                                        │
│  TIER 2: COMBINED CALCULATIONS (ANALYTICAL DATABASES)                  │
│  ├── Traffic Flow Assignment   ├── Network Centrality & Morphology     │
│  ├── Pedestrian Walkability    ├── Speed-Dependent Emissions (CO2/NOx) │
│  ├── Noise Propagation Model   ├── Weather-Impacted Road Conditions    │
│  ├── Isochrone Reachability    ├── Composite StreetIQ Scoring          │
│  ├── Temporal Profiles         ├── Data Quality Indices                │
│  │                                                                     │
│  ▼ (Optimization Solvers & AI Synthesis)                               │
│                                                                        │
│  TIER 3: ACTIONABLE DECISION DATABASES                                 │
│  ├── Street Direction Flipping ├── Traffic Signalization Placement     │
│  ├── Pedestrian Crossing Zones ├── New Street Connectivity Proposals   │
│  ├── Transit Frequency Tuning  ├── Cycling Infrastructure Gaps         │
│  ├── Scenario Comparisons      └── AI Policy & Design Recommendations  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Design Principle**: Every data source enters at Tier 1. Every mathematical model reads from Tier 1 and writes to Tier 2. Every optimization or AI output reads from Tier 2 and writes to Tier 3. This guarantees traceability and modularity.

---

## OSM Ingestion & Progressive Bounding Box Loading

### BBox Selector

Users draw a bounding box directly on the map. The backend enforces **progressive detail tiers** based on area size to prevent Overpass API timeouts and ensure smooth performance:

| Tier | Area | Detail Level | What Gets Fetched |
|------|------|-------------|-------------------|
| **A** | ≤ 5 km² | Full detail | All edges, pedestrian paths, cycling, transit, buildings, POIs |
| **B** | 5–15 km² | Simplified | Primary/secondary/tertiary roads, transit, major pedestrian paths |
| **C** | 15–50 km² | Skeleton | Major roads (motorway/trunk/primary), rail lines only |

### OSM Caching Strategy

- Fetched data is **parsed immediately** into the structured relational tables (`street_edges`, `pedestrian_edges`, etc.) with a `fetched_at` timestamp on each row.
- The `osm_cache` table serves as a **fetch log** (which bbox was queried, at what detail tier, and when) to prevent duplicate external requests.
- Overlapping requests are served from the existing parsed tables, spatially clipped to the new bbox.

---

## Project Save & Load (Workspace Persistence)

| Saved State | Description |
|-------------|-------------|
| `name` | User-chosen project name |
| `bbox` | Geographic extent polygon |
| `center_lat`, `center_lon` | Map center coordinates |
| `zoom_level` | Current zoom |
| `layer_state` (JSONB) | Which layers are visible (streets, pedestrian, cycling, transit, satellite, H3, buildings, POIs) |
| `region_id` | Link to all fetched data |

Reopening a project restores the exact map viewport, visible layers, and all associated network data.

---

## Dual Spatial Representations (Network vs. Grid)

SmartStreet maintains two concurrent spatial frameworks. Each is optimized for different analysis types, and they are linked via spatial interpolation:

```
┌──────────────────────────────────────┐     Spatial Interpolation     ┌──────────────────────────────────────┐
│        Vector Network Graph          │ ────────────────────────────> │       Uber H3 Grid Cells             │
│   - Directed Graph G = (V, E)        │   Length-Weighted / KDE       │   - Auto-resolution by zoom:         │
│   - Node: Intersections (Point)      │                               │     Zoom ≤ 12 → H3 Res 7 (~5 km²)   │
│   - Edge: Streets (LineString)       │ <──────────────────────────── │     Zoom 13-14 → Res 8 (~0.7 km²)   │
│   - Routing, capacity, traffic flow  │   Centroid Distance-Decay     │     Zoom 15-16 → Res 9 (~0.1 km²)   │
└──────────────────────────────────────┘                               │     Zoom ≥ 17 → Res 10 (~0.015 km²) │
                                                                       └──────────────────────────────────────┘
```

### 1. Vector Graph Representation
- Used for routing, traffic flow simulations, centrality, and morphological calculations.
- Represented as a directed graph **G = (V, E)** where nodes V represent intersections and edges E represent street segments.

### 2. Grid-Cell Representation (Uber H3 Indexing)
- Used for aggregating multi-layered datasets: air pollution, noise, demographics, walkability.
- Streets and transit lines are mapped onto **H3 hexagons** with auto-adapting resolution based on user zoom level.

### 3. Spatial Interpolation Methods

**Network → Grid** (Length-Weighted Intersection):

```
A_c = Σ (L_{e∩c} / L_e) · A_e    for all edges e intersecting cell c
```

Where `A_c` is the aggregated attribute in cell `c`, `L_{e∩c}` is the length of edge `e` within cell `c`, `L_e` is total edge length, and `A_e` is the edge attribute.

**Grid → Network** (Inverse Distance Weighting):

```
A_e = Σ w(d_{c,e}) · A_c / Σ w(d_{c,e})    for all cells c near edge e
```

Projects ambient variables (air quality, noise) onto road segments.

---

## Relational Database Schema

### Tier 1: Raw Geometry & Data Tables

```sql
-- Regions of Interest
CREATE TABLE regions (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    bbox GEOMETRY(Polygon, 4326),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Saved Projects (Workspace State)
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    center_lat DOUBLE PRECISION NOT NULL,
    center_lon DOUBLE PRECISION NOT NULL,
    zoom_level DOUBLE PRECISION NOT NULL,
    bbox GEOMETRY(Polygon, 4326) NOT NULL,
    layer_state JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- OSM Query Cache (Fetch Log)
CREATE TABLE osm_cache (
    id SERIAL PRIMARY KEY,
    bbox GEOMETRY(Polygon, 4326) NOT NULL,
    detail_tier VARCHAR(1) DEFAULT 'A',  -- 'A', 'B', 'C'
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Network Nodes (Intersections)
CREATE TABLE network_nodes (
    id BIGINT PRIMARY KEY,                -- OSM Node ID
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    geom GEOMETRY(Point, 4326) NOT NULL,
    elevation DOUBLE PRECISION,
    degree INT DEFAULT 0                  -- Number of connecting edges
);

-- Street Network (Vehicular)
CREATE TABLE street_edges (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    source_node BIGINT REFERENCES network_nodes(id),
    target_node BIGINT REFERENCES network_nodes(id),
    highway VARCHAR(50),
    name VARCHAR(255),
    lanes INT,
    oneway BOOLEAN DEFAULT FALSE,
    maxspeed INT,
    surface VARCHAR(50),
    width DOUBLE PRECISION,
    length DOUBLE PRECISION,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    geom GEOMETRY(LineString, 4326) NOT NULL
);

-- Pedestrian Infrastructure
CREATE TABLE pedestrian_edges (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    type VARCHAR(50),            -- 'sidewalk', 'crossing', 'footway', 'steps', 'pedestrian'
    surface VARCHAR(50),
    width DOUBLE PRECISION,
    lit BOOLEAN,
    tactile_paving BOOLEAN,
    geom GEOMETRY(LineString, 4326) NOT NULL
);

-- Cycling Infrastructure
CREATE TABLE cycling_edges (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    type VARCHAR(50),            -- 'cycle_lane', 'cycle_track', 'shared_road', 'bike_path'
    surface VARCHAR(50),
    width DOUBLE PRECISION,
    oneway BOOLEAN DEFAULT FALSE,
    geom GEOMETRY(LineString, 4326) NOT NULL
);

-- Public Transit Routes
CREATE TABLE transit_routes (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    name VARCHAR(255),
    mode VARCHAR(50),            -- 'bus', 'tram', 'subway', 'rail', 'trolleybus'
    operator VARCHAR(255),
    geom GEOMETRY(LineString, 4326) NOT NULL
);

-- Public Transit Stops
CREATE TABLE transit_stops (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    name VARCHAR(255),
    mode VARCHAR(50),            -- 'bus_stop', 'tram_stop', 'railway_station', 'subway_entrance'
    geom GEOMETRY(Point, 4326) NOT NULL
);

-- Points of Interest (Amenities)
CREATE TABLE points_of_interest (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    category VARCHAR(50),        -- 'shop', 'school', 'hospital', 'park', 'restaurant', 'pharmacy'
    name VARCHAR(255),
    geom GEOMETRY(Point, 4326) NOT NULL
);

-- Building Footprints
CREATE TABLE building_footprints (
    id SERIAL PRIMARY KEY,
    osm_id BIGINT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    building_type VARCHAR(50),   -- 'residential', 'commercial', 'industrial', 'yes'
    levels INT,
    height DOUBLE PRECISION,
    geom GEOMETRY(Polygon, 4326) NOT NULL
);
```

### Tier 2: Combined Analytical Metrics

```sql
-- Temporal Profiles
CREATE TABLE time_slots (
    id SERIAL PRIMARY KEY,
    label VARCHAR(50),            -- 'morning_rush', 'midday', 'evening_rush', 'night'
    start_hour INT,
    end_hour INT,
    day_type VARCHAR(20)          -- 'weekday', 'weekend', 'holiday'
);

-- Street-Level Analytics (per time slot)
CREATE TABLE street_analytics (
    edge_id INT REFERENCES street_edges(id) ON DELETE CASCADE,
    time_slot_id INT REFERENCES time_slots(id) ON DELETE CASCADE,
    betweenness_centrality DOUBLE PRECISION,
    closeness_centrality DOUBLE PRECISION,
    modeled_flow_volume DOUBLE PRECISION,
    modeled_delay DOUBLE PRECISION,
    co2_emissions_hourly DOUBLE PRECISION,
    noise_level_db DOUBLE PRECISION,
    street_iq DOUBLE PRECISION,          -- Composite weighted score
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (edge_id, time_slot_id)
);

-- Pedestrian Walkability
CREATE TABLE pedestrian_analytics (
    edge_id INT PRIMARY KEY REFERENCES pedestrian_edges(id) ON DELETE CASCADE,
    walkability_index DOUBLE PRECISION,   -- Frank's composite
    connectivity_index DOUBLE PRECISION,
    safety_score DOUBLE PRECISION,
    slope_gradient DOUBLE PRECISION,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cycling Bikeability
CREATE TABLE cycling_analytics (
    edge_id INT PRIMARY KEY REFERENCES cycling_edges(id) ON DELETE CASCADE,
    bikeability_score DOUBLE PRECISION,
    stress_level INT,                     -- Level of Traffic Stress (LTS 1-4)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- H3 Grid-Cell Aggregated Metrics
CREATE TABLE grid_cell_metrics (
    h3_index VARCHAR(15),
    h3_resolution INT,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    population_density DOUBLE PRECISION,
    ambient_pm25 DOUBLE PRECISION,
    ambient_noise_db DOUBLE PRECISION,
    walkability_index DOUBLE PRECISION,
    poi_density DOUBLE PRECISION,
    building_coverage_ratio DOUBLE PRECISION,
    PRIMARY KEY (h3_index, h3_resolution)
);

-- Isochrone Results (Reachability Polygons)
CREATE TABLE isochrone_results (
    id SERIAL PRIMARY KEY,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    origin_node BIGINT REFERENCES network_nodes(id),
    mode VARCHAR(20),             -- 'walk', 'drive', 'cycle'
    travel_minutes INT,           -- 5, 10, 15, 30
    geom GEOMETRY(Polygon, 4326) NOT NULL,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Data Quality Assessment
CREATE TABLE data_quality (
    edge_id INT PRIMARY KEY REFERENCES street_edges(id) ON DELETE CASCADE,
    has_maxspeed BOOLEAN DEFAULT FALSE,
    has_lanes BOOLEAN DEFAULT FALSE,
    has_surface BOOLEAN DEFAULT FALSE,
    has_width BOOLEAN DEFAULT FALSE,
    has_name BOOLEAN DEFAULT FALSE,
    completeness_pct DOUBLE PRECISION     -- 0.0 to 1.0
);
```

### Tier 3: Decision & Recommendation Tables

```sql
-- Scenarios
CREATE TABLE scenarios (
    id SERIAL PRIMARY KEY,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Scenario Overrides (individual edits, ordered for undo/redo)
CREATE TABLE scenario_overrides (
    id SERIAL PRIMARY KEY,
    scenario_id INT REFERENCES scenarios(id) ON DELETE CASCADE,
    sequence_number INT NOT NULL,         -- For undo/redo ordering
    target_type VARCHAR(50),              -- 'street', 'pedestrian', 'transit', 'cycling'
    target_id INT,
    action_type VARCHAR(50),              -- 'closure', 'direction_change', 'new_construction', 'attribute_change'
    attribute_overrides JSONB,            -- {"maxspeed": 30, "lanes": 3, "surface": "asphalt"}
    new_geometry GEOMETRY(LineString, 4326)
);

-- Scenario Comparison Results
CREATE TABLE scenario_comparisons (
    id SERIAL PRIMARY KEY,
    baseline_scenario_id INT REFERENCES scenarios(id),
    modified_scenario_id INT REFERENCES scenarios(id),
    metric VARCHAR(50),                   -- 'total_travel_time', 'total_co2', 'avg_walkability'
    baseline_value DOUBLE PRECISION,
    modified_value DOUBLE PRECISION,
    delta_pct DOUBLE PRECISION,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Actionable Decisions (optimizer + AI outputs)
CREATE TABLE actionable_decisions (
    id SERIAL PRIMARY KEY,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    scenario_id INT REFERENCES scenarios(id) ON DELETE CASCADE,
    category VARCHAR(50),                 -- 'street_direction', 'signalization', 'pedestrian_crossing',
                                          -- 'new_link', 'speed_reduction', 'bike_lane'
    geom GEOMETRY(Geometry, 4326),
    impact_score DOUBLE PRECISION,
    confidence VARCHAR(20),               -- 'high', 'medium', 'low' (sensitivity-based)
    ai_rationale TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Computation Log (provenance & audit trail)
CREATE TABLE computation_log (
    id SERIAL PRIMARY KEY,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    operation VARCHAR(100),               -- 'osm_fetch', 'centrality_calc', 'direction_optimization'
    parameters JSONB,                     -- {"algorithm": "genetic", "generations": 100}
    status VARCHAR(20),                   -- 'completed', 'failed', 'running'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- Generated PDF Reports
CREATE TABLE reports (
    id SERIAL PRIMARY KEY,
    project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    scenario_id INT REFERENCES scenarios(id) ON DELETE SET NULL,
    report_type VARCHAR(50) NOT NULL,     -- See Report Catalog
    title VARCHAR(255) NOT NULL,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    parameters JSONB,                     -- Inputs used (time_slot, weights, etc.)
    pdf_data BYTEA,                       -- The PDF binary blob
    page_count INT,
    file_size_kb INT
);
```

---

## Network Models & Optimization Theories

### 1. Traffic Direction Optimization (DNDP Solver)

- **Problem Type**: Discrete Network Design Problem (DNDP).
- **Objective**: Minimize total system travel time (congestion delay) by changing street directions (two-way → one-way).
- **Model**: Bilevel optimization using **User Equilibrium (Beckmann Formulation)** at the lower level and system delay minimization at the upper level.
- **Solver Options**: Genetic Algorithm (GA) or Simulated Annealing (SA) metaheuristics, comparing routing costs before and after direction changes.

### 2. Traffic Signalization Placement

- **Conflict Point Index (CPI)**: Evaluates collision risk at intersections. Stream volumes multiplied by severity weights (crossing, merging, pedestrian-vehicle conflict). High CPI combined with high betweenness centrality flags intersections that require signal controls.
- **Webster's Delay Model**: Computes intersection delay and optimal cycle length.
- **Betweenness Centrality Thresholds**: Flags critical routing hubs.

### 3. Pedestrian & Walkability Models

- **Frank's Walkability Index**: `2z(ID) + z(RD) + z(FAR) + z(LUM)` — evaluates morphological walkability based on intersection density, net residential density, retail floor area ratio, and land use mix (entropy index).
- **Space Syntax Angular Segment Analysis (ASA)**: Predicts pedestrian flow by minimizing cumulative angular change.
- **Pedestrian Safety Risk Index (PSRI)**: Computes risk factors based on approach speeds, walkway width, crossing types, and vehicle-pedestrian volumes.

### 4. Cycling Analysis

- **Level of Traffic Stress (LTS)**: Rates each road segment 1–4 based on speed, lanes, and separation type. LTS 1 = child-safe, LTS 4 = highway-adjacent.
- **Bikeability Score**: Composite of surface quality, slope, traffic stress, and network connectivity.

### 5. Transit Indices

- **Route Overlap Index (ROI)**: Identifies spatial route duplication on specific corridors to reduce bus congestion.
- **Hanson Gravity Accessibility**: Evaluates transit accessibility to opportunities (jobs, clinics) with an exponential distance decay factor.
- **Stop Catchment Analysis**: Walking isochrones from each transit stop.

### 6. Isochrone Analysis

Walking, cycling, and driving reachability polygons from any point. Stored per origin/mode/time budget. Visualized as translucent concentric zones on the map.

### 7. Composite StreetIQ Score

```
StreetIQ(e) = Σ w_m · normalize(m_e)    for all metrics m in M
```

User-configurable weights via UI sliders. Normalizes each metric to [0, 1] and produces a single composite ranking per edge. Enables "show me the worst/best streets" views.

### 8. Parameter Sensitivity Analysis

Re-runs optimization models with ±20% parameter variation (alpha, beta in BPR function) and reports recommendation robustness as `confidence` (high/medium/low) on each actionable decision.

---

## UI Dashboard Design

The SmartStreet dashboard is a single-page application with a map-centric layout. The interface is organized into **6 functional panels** around a central interactive map.

### Layout Wireframe

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  TOP BAR                                                                    │
│  [SmartStreet]  [Project: Helsinki Center ▼]  [Save] [Export ▼]  [⚙]       │
├────────────────────┬────────────────────────────────────────┬───────────────┤
│                    │                                        │               │
│  LEFT SIDEBAR      │           MAP CANVAS                   │ RIGHT SIDEBAR │
│                    │                                        │               │
│  ┌──────────────┐  │   ┌────────────────────────────────┐   │ ┌───────────┐ │
│  │ Projects     │  │   │                                │   │ │ Analysis  │ │
│  │              │  │   │    Interactive MapLibre +       │   │ │ Panel     │ │
│  │ Helsinki Ctr │  │   │    Deck.gl Canvas               │   │ │           │ │
│  │ Ljubljana SE │  │   │                                │   │ │ Centrality│ │
│  │ + New...     │  │   │    Satellite / Vector toggle    │   │ │ Walkabil. │ │
│  └──────────────┘  │   │                                │   │ │ Emissions │ │
│                    │   │    Road Network                 │   │ │ Noise     │ │
│  ┌──────────────┐  │   │    Pedestrian Paths             │   │ │ StreetIQ  │ │
│  │ Layers       │  │   │    Cycling Infrastructure       │   │ │           │ │
│  │              │  │   │    Transit Routes & Stops        │   │ │ [Weights] │ │
│  │ [x] Streets  │  │   │    Building Footprints           │   │ │ slider    │ │
│  │ [x] Pedestr. │  │   │    H3 Grid Overlay              │   │ │ slider    │ │
│  │ [x] Cycling  │  │   │    Isochrone Polygons            │   │ │           │ │
│  │ [ ] Transit  │  │   │                                │   │ │ Time Slot │ │
│  │ [ ] Buildings│  │   │    ┌──────────────────────┐     │   │ │ [Morning] │ │
│  │ [ ] POIs     │  │   │    │ Draw BBox Tool       │     │   │ │           │ │
│  │ [ ] H3 Grid  │  │   │    │ Isochrone Origin     │     │   │ │ Data Qual │ │
│  │ [ ] Isochron.│  │   │    │ Edit Roads           │     │   │ │ ====  67% │ │
│  │              │  │   │    └──────────────────────┘     │   │ └───────────┘ │
│  │ Color By:    │  │   │                                │   │               │
│  │ [StreetIQ ▼] │  │   └────────────────────────────────┘   │ ┌───────────┐ │
│  │              │  │                                        │ │ Optimiz.  │ │
│  │ Basemap:     │  │   ┌────────────────────────────────┐   │ │           │ │
│  │ o Satellite  │  │   │ BOTTOM PANEL (collapsible)     │   │ │ > Run     │ │
│  │ * Vector     │  │   │                                │   │ │ Direction │ │
│  │ o Hybrid     │  │   │ Charts: Time-series | Histo-   │   │ │ Solver    │ │
│  └──────────────┘  │   │ grams | Network Stats |        │   │ │           │ │
│                    │   │ Scenario Comparison Deltas      │   │ │ > Run     │ │
│  ┌──────────────┐  │   │                                │   │ │ Signal    │ │
│  │ Scenarios    │  │   │ [Chart] [Histogram] [Compare]  │   │ │ Placement │ │
│  │              │  │   └────────────────────────────────┘   │ │           │ │
│  │ Baseline     │  │                                        │ │ > Run     │ │
│  │ + One-Way    │  │                                        │ │ Connect.  │ │
│  │ + Speed 30   │  │                                        │ │ Gaps      │ │
│  │ + New...     │  │                                        │ │           │ │
│  │              │  │                                        │ │ AI Synth. │ │
│  │ [Compare ▼]  │  │                                        │ │ [> Ask AI]│ │
│  │ [Undo] [Redo]│  │                                        │ └───────────┘ │
│  └──────────────┘  │                                        │               │
├────────────────────┴────────────────────────────────────────┴───────────────┤
│  STATUS BAR: Edges: 4,231 | Nodes: 2,847 | Area: 3.2 km² | Last fetch: 2h │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Panel 1: Top Bar

| Element | Description |
|---------|-------------|
| **Project Selector** | Dropdown to switch between saved projects |
| **Save Button** | Persists current map state, layer visibility, and viewport |
| **Export Menu** | GeoJSON, GeoPackage, CSV, PDF report, static HTML map embed |
| **Settings Gear** | API keys, default parameters (alpha, beta for BPR), H3 resolution |

### Panel 2: Map Canvas (Center)

- **Renderer**: MapLibre GL JS base + Deck.gl overlay layers.
- **Basemap Switcher**: Satellite (Esri World Imagery), Vector (OpenFreeMap/MapTiler), Hybrid.
- **Interactive Tools**:
  - *Draw BBox*: Rubberband rectangle. Shows area in km² live. Turns red if > tier limit.
  - *Isochrone Origin*: Click any node to generate walk/cycle/drive reachability polygons.
  - *Edit Roads*: Click edges to flip direction, close, change speed limit, or draw new connections.
  - *Inspect*: Click any element to see its full attribute table in a popup.
- **Layer Rendering** (via Deck.gl):

| Layer | Deck.gl Type | Visual Style |
|-------|-------------|-------------|
| Street edges | `PathLayer` | Solid lines, colored by selected metric |
| Pedestrian paths | `PathLayer` | Dashed lines, colored by walkability/safety |
| Cycling edges | `PathLayer` | Dotted lines, colored by LTS stress level |
| Transit routes | `GeoJsonLayer` | Colored by mode (blue=bus, red=tram, green=rail) |
| Transit stops, POIs, nodes | `ScatterplotLayer` | Sized/colored by category |
| Building footprints | `PolygonLayer` | Extruded in 3D by height/levels |
| H3 grid cells | `H3HexagonLayer` | Colored by aggregated metric |
| Isochrone zones | `PolygonLayer` | Translucent concentric zones |

### Panel 3: Left Sidebar — Projects, Layers & Scenarios

**Projects Section**: List of saved projects with name, date, and thumbnail. "New Project" button opens the BBox draw tool. Click to load and restore viewport, layers, and data.

**Layer Control**: Checkboxes to toggle each data layer. "Color By" dropdown selects which metric drives edge coloring. Opacity sliders per layer.

**Scenarios Section**: Named scenarios under the current project. "Baseline" is always present. Undo/Redo buttons step through `scenario_overrides`. Compare dropdown generates delta metrics.

### Panel 4: Right Sidebar — Analysis & Optimization

**Analysis Panel (Top)**:
- Summary statistics (road length, intersection count, connectivity %, one-way %).
- Metric cards with region-wide averages.
- StreetIQ weight sliders for real-time map recoloring.
- Time slot selector (morning_rush, midday, evening_rush, night).
- Data quality gauge with completeness percentage.

**Optimization Panel (Bottom)**:
- Direction Solver (GA/SA button + progress bar).
- Signal Placement (conflict point + centrality analysis).
- Connectivity Gaps (circuity analysis).
- AI Synthesis ("Ask AI" button → LLM report card).

### Panel 5: Bottom Panel — Charts & Comparisons (Collapsible)

- Time-series chart (flow volume across time slots).
- Histogram (StreetIQ / centrality / emissions distribution).
- Spider/radar chart (region-wide connectivity, walkability, emissions, noise, transit).
- Scenario comparison bar chart (delta % in travel time, CO₂, walkability).

### Panel 6: Status Bar

- Live counters: edges, nodes, transit routes, POIs.
- Current bbox area in km².
- Time since last OSM fetch ("Refresh" button).
- Computation status indicator.

---

## Output Pipeline & Modular Report System

SmartStreet produces outputs at every tier. All outputs flow through a unified pipeline that can render to the web dashboard, export as data files, or compile into **professional PDF reports** stored and served as web-accessible assets.

### Output Pipeline Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│                      SmartStreet Output Pipeline                         │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  TIER 2/3 Analytical & Decision Tables                                    │
│       │                                                                   │
│       ├──> LIVE DASHBOARD (React)                                         │
│       │     Map layers, charts, metric cards, AI cards                    │
│       │                                                                   │
│       ├──> DATA EXPORT                                                    │
│       │     GeoJSON · GeoPackage · CSV · Parquet                          │
│       │                                                                   │
│       └──> REPORT ENGINE                                                  │
│             │                                                             │
│             ├─ 1. Snapshot Renderer (Matplotlib/Folium -> static PNG/SVG) │
│             ├─ 2. Template Composer (Jinja2 HTML templates)               │
│             ├─ 3. PDF Compiler (WeasyPrint: HTML+CSS -> PDF)              │
│             └─ 4. Storage & Serving (DB blob + FastAPI static endpoint)   │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
```

### Report Generation Pipeline (Step by Step)

**Step 1 — Snapshot Renderer**: The backend renders static map images and charts from analytical data.
- **Map snapshots**: Matplotlib + contextily (basemap tiles) or Folium `.save()` → screenshot via Playwright. Produces high-DPI PNG/SVG images of the network colored by the selected metric.
- **Chart snapshots**: Matplotlib generates histograms, bar charts, radar plots, and time-series as SVG files.
- All images are saved to a `reports/assets/` directory under the project.

**Step 2 — Template Composer**: Jinja2 HTML templates are populated with:
- Project metadata (name, region, date, bbox area).
- Summary statistics (edge count, node count, transit coverage, data quality %).
- Embedded map and chart images (`<img>` tags referencing the rendered PNGs/SVGs).
- Per-section analytical tables (top 10 bottleneck edges, worst walkability zones, etc.).
- AI-generated rationale text from the `actionable_decisions` table.
- Scenario comparison deltas (before/after tables).

**Step 3 — PDF Compiler**: WeasyPrint converts the composed HTML+CSS into a paginated PDF.
- Professional CSS styling with headers, footers, page numbers, and a table of contents.
- Print-optimized layout (A4 portrait, with landscape pages for wide map images).
- Color-coded tables and embedded legends matching the dashboard palette.

**Step 4 — Storage & Serving**: The generated PDF binary is stored in the `reports` table and served via FastAPI.
- `GET /api/reports/{report_id}/pdf` — returns `Content-Type: application/pdf`.
- `GET /api/projects/{project_id}/reports` — returns JSON metadata array.
- Each report has a unique shareable URL.

### Modular Report Catalog

Each report type is a self-contained module — a Jinja2 template + a data-fetching function. New report types can be added by registering a template and data loader.

| # | Report Type | Sections Included | When to Generate |
|---|-------------|-------------------|------------------|
| 1 | **Network Overview** | Region summary, road classification breakdown, connectivity indices, intersection density map, data quality summary | After first fetch |
| 2 | **Traffic Analysis** | Centrality heatmap, BPR congestion coloring, volume-delay curves, top 20 bottleneck edges, time-of-day flow comparison | After analytics |
| 3 | **Walkability Assessment** | Walkability index map, pedestrian path coverage, safety score distribution, sidewalk gap analysis, POI accessibility | After analytics |
| 4 | **Cycling Infrastructure** | Bikeability map, LTS stress classification, network connectivity gaps, vehicular coverage comparison | After analytics |
| 5 | **Transit Coverage** | Route map, stop catchment isochrones, route overlap index, accessibility gravity scores, mode distribution | After analytics |
| 6 | **Environmental Impact** | CO₂ emissions map, noise level map, air quality overlay, H3 grid pollution, emission hotspot ranking | After analytics |
| 7 | **Optimization Recommendations** | Direction change proposals (before/after maps), signal placement, connectivity gaps, AI rationale, confidence scores | After optimization |
| 8 | **Scenario Comparison** | Side-by-side maps, delta metrics table, bar charts of % changes, AI policy commentary | After scenarios |

### Adding New Report Modules (Developer Guide)

To create a new report type:

1. Create a new Jinja2 template in `backend/report_templates/my_report.html`.
2. Write a data-loader function in `backend/services/report_service.py` that queries the relevant Tier 2/3 tables and renders map/chart snapshots.
3. Register the report type in the `REPORT_CATALOG` dictionary.
4. The report is immediately available in the UI's Export menu.

```python
# backend/services/report_service.py

REPORT_CATALOG = {
    "network_overview": {
        "template": "network_overview.html",
        "loader": load_network_overview_data,
        "label": "Network Overview Report",
    },
    "traffic_analysis": {
        "template": "traffic_analysis.html",
        "loader": load_traffic_analysis_data,
        "label": "Traffic Analysis Report",
    },
    # Add new report types here...
}
```

### Report Template Structure

Each report template follows a consistent HTML structure:

```html
<!-- report_templates/network_overview.html -->
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="report_style.css">
</head>
<body>
  <!-- Cover Page -->
  <section class="cover">
    <h1>{{ report_title }}</h1>
    <p class="subtitle">{{ project.name }} — {{ project.region_name }}</p>
    <p class="date">Generated: {{ generated_at }}</p>
    <img src="{{ cover_map_image }}" class="cover-map">
  </section>

  <!-- Table of Contents (auto-generated by CSS) -->
  <nav class="toc"><h2>Contents</h2></nav>

  <!-- Section 1: Summary -->
  <section class="chapter">
    <h2>1. Region Summary</h2>
    <table class="stats-table">
      <tr><td>Total Road Length</td><td>{{ stats.total_road_km }} km</td></tr>
      <tr><td>Intersections</td><td>{{ stats.node_count }}</td></tr>
      <tr><td>Transit Stops</td><td>{{ stats.transit_stop_count }}</td></tr>
      <tr><td>Data Completeness</td><td>{{ stats.data_quality_pct }}%</td></tr>
    </table>
  </section>

  <!-- Section 2: Maps (landscape page) -->
  <section class="chapter landscape">
    <h2>2. Network Map</h2>
    <img src="{{ network_map_image }}" class="full-width-map">
    <p class="caption">Road network colored by {{ color_metric }}.</p>
  </section>

  <!-- Section N: AI Recommendations -->
  <section class="chapter">
    <h2>N. AI Analysis</h2>
    <div class="ai-card">{{ ai_rationale | safe }}</div>
  </section>

  <!-- Footer on every page -->
  <footer>
    SmartStreet Report — {{ project.name }} — Page <span class="page-number"></span>
  </footer>
</body>
</html>
```

### Report Viewer in the UI

The dashboard includes a **Reports Panel** accessible from the top bar Export menu:
- Lists all generated reports for the current project (name, type, date, page count, file size).
- Click to **preview** the PDF inline in the browser.
- Click to **download** the PDF file.
- **Generate** button opens a dialog to select report type, time slot, and scenario.
- **Delete** button removes a report from the database.

---

## Phased Roadmap

### Phase 1 — Foundation & Digital Twin

- [ ] Project scaffolding: FastAPI backend + React/Vite frontend.
- [ ] SQLite + SpatiaLite database with full schema (all tables above).
- [ ] OSMnx/Overpass fetcher: streets, pedestrian, cycling, transit routes/stops, POIs, buildings.
- [ ] Progressive BBox loading tiers (A/B/C) with area constraint enforcement.
- [ ] OSM cache log table and parsed-data freshness tracking.
- [ ] Project Save/Load API with layer_state persistence.
- [ ] MapLibre + Deck.gl map canvas with satellite/vector/hybrid basemap switcher.
- [ ] Layer toggle panel with all 8 layer types.
- [ ] Projects panel: list, create, load, delete.
- [ ] Data quality overlay (completeness percentage per edge).

### Phase 2 — Analytical Calculators

- [ ] Time slots table seeded with default profiles (morning_rush, midday, evening_rush, night).
- [ ] NetworkX: betweenness & closeness centrality per edge and node.
- [ ] H3 grid projection: length-weighted interpolation at auto-resolution.
- [ ] Pedestrian walkability scoring (Frank's index, space syntax connectivity).
- [ ] Cycling LTS stress level and bikeability score.
- [ ] Isochrone generation (walk/cycle/drive at 5/10/15/30 min).
- [ ] Composite StreetIQ scoring with configurable weights.
- [ ] Color-coded map rendering by selected metric + time slot.
- [ ] Bottom panel charts: histogram, time-series, network stats radar.
- [ ] Computation log tracking.

### Phase 3 — Optimization Engine & AI

- [ ] DNDP Street Direction Solver (GA + SA).
- [ ] Signalization Placement (CPI + Webster + centrality).
- [ ] Connectivity Gap Finder (circuity analysis).
- [ ] Parameter sensitivity analysis → confidence scores.
- [ ] AI synthesis endpoint: packages Tier 2 data, calls LLM, stores rationale.
- [ ] Map overlays: direction arrows, signal icons, proposed links.
- [ ] AI report card in right sidebar.

### Phase 4 — Scenario Sandbox

- [ ] Scenario editor: close roads, flip directions, change speed limits, draw new roads.
- [ ] Undo/Redo via sequence-numbered overrides.
- [ ] Re-compute Tier 2 metrics on modified network.
- [ ] Scenario comparison table and delta bar charts.
- [ ] Attribute override support (speed, lanes, surface via JSONB).

### Phase 5 — Output Pipeline, Reporting & Polish

- [ ] Data export endpoints: GeoJSON, GeoPackage, CSV, Parquet.
- [ ] Snapshot renderer: Matplotlib + contextily static map images (PNG/SVG per metric).
- [ ] Chart renderer: Matplotlib histogram, bar, radar, time-series SVG outputs.
- [ ] Jinja2 report template system with `report_style.css` (A4, headers, footers, page numbers).
- [ ] WeasyPrint PDF compiler integration.
- [ ] `reports` database table and FastAPI endpoints (generate, list, serve, delete).
- [ ] Report catalog: implement all 8 report modules (Network Overview through Scenario Comparison).
- [ ] Reports panel in frontend: list, preview (inline PDF), download, generate dialog.
- [ ] Static HTML map embed export (Folium self-contained HTML).
- [ ] Keyboard shortcuts for common actions.
- [ ] Dark mode / light mode toggle.
- [ ] Responsive layout for tablet screens.

---

## Tech Stack Summary

| Layer | Technology | Role |
|-------|-----------|------|
| **Backend** | Python 3.11+ / FastAPI | REST API, data processing, OSM fetching |
| **Database** | SQLite + SpatiaLite (→ PostgreSQL + PostGIS later) | Spatial relational storage |
| **Graph Analysis** | NetworkX, OSMnx | Network centrality, routing, isochrones |
| **Spatial** | GeoPandas, Shapely, H3-py | Geometry operations, hex indexing |
| **Charts** | Matplotlib, contextily | Static chart/map rendering for PDF reports |
| **PDF Reports** | WeasyPrint + Jinja2 | HTML/CSS → professional PDF compilation |
| **Frontend** | React + Vite | SPA dashboard |
| **Map** | MapLibre GL JS + Deck.gl | Interactive map canvas with WebGL layers |
| **Basemaps** | Esri (satellite), OpenFreeMap (vector) | Tile sources |

---

## Open Questions & Future Developments

> **Q1: Database Choice** — Start with SQLite + SpatiaLite (instant local setup) or deploy PostgreSQL + PostGIS immediately?
>
> **Q2: AI Provider** — OpenAI, Anthropic, Gemini, or local Ollama for the recommendation engine?
>
> **Q3: Demo City** — Which city or neighborhood should we use for initial testing?

### Long-Term R&D Backlog

- **Dynamic Live Feeds**: Real-time GPS, sensor arrays, live GTFS-Realtime.
- **Agent-Based Pedestrian Simulation**: Mesa framework for dynamic conflict modeling.
- **Multimodal Routing Engines**: Valhalla or R5 for production-grade trip planning.
- **AI-Generated Scenario Layouts**: LLM proposes coordinate-level new street geometries.
- **Multi-User Collaboration**: User accounts, scenario locking, comment threads on edges.
- **Weather-Correlated Accident Risk Models**: Join historical accident data with weather time-series.
- **EV Charging Infrastructure Gap Analysis**: OpenChargeMap overlay + range modeling.
- **Flood / Climate Resilience Overlays**: Copernicus EMS flood zone polygons on the network.
- **3D Urban Canyon Modeling**: Building heights + street widths → noise reflection and pollutant trapping simulations.
- **Machine Learning on Grid Tensors**: Train CNNs / GCNs on the H3 grid feature tensors for predictive analytics (crash risk, congestion forecasting).

---

*This document is the single source of truth for SmartStreet's architecture and implementation plan. All contributors should consult this before making structural changes.*
