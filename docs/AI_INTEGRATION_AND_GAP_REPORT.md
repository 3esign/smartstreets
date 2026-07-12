# SmartStreet — Gap Analysis & AI Integration Report

> **Version**: 1.1
> **Date**: 2026-07-10
> **Companion to**: `ARCHITECTURE.md` v0.1.0-draft
> **Scope**: Full review of the planned architecture; gaps and risks; a formal network-first spatial ontology (streets as the essential axis, buildings/places as attached nodes, 3D analysis as a separate module); new models, frameworks, papers, and data sources worth adopting; and a detailed, implementation-ready design for the AI layer (BYOK multi-provider LLM integration for analysis, simulation interpretation, scenario generation, and reporting).

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Assessment of the Current Architecture](#2-assessment-of-the-current-architecture)
3. [Gap Analysis](#3-gap-analysis)
4. [Network-First Spatial Ontology](#4-network-first-spatial-ontology)
   - 4.1 The Three Planes
   - 4.2 Plane A — The Network Spine
   - 4.3 Plane B — Anchored Entities (Proximity & Attraction)
   - 4.4 Plane C — 3D / Volumetric Module (Separate)
   - 4.5 Where the H3 Grid Fits
   - 4.6 Consequences for Schema, Pipeline & UI
5. [AI Integration Architecture (Core Focus)](#5-ai-integration-architecture)
   - 5.1 Ground Rules (what the research says)
   - 5.2 AI Gateway: BYOK Key Management & Provider Abstraction
   - 5.3 Capability Track AI-1: Grounded Narrative Synthesis
   - 5.4 Capability Track AI-2: Conversational Analyst (Tool-Calling Agent)
   - 5.5 Capability Track AI-3: Scenario Generation (NL → Scenario Overrides)
   - 5.6 Capability Track AI-4: Persona Debate on Recommendations
   - 5.7 Capability Track AI-5: VLM Street Audits (Imagery → Scores)
   - 5.8 Capability Track AI-6: RAG over Municipal Plans & Standards
   - 5.9 Capability Track AI-7: LLM-Assisted Optimization
   - 5.10 Capability Track AI-8: Golden-Set Evaluation Harness
   - 5.11 MCP Server: SmartStreet as a Tool Provider
   - 5.12 AI Database Schema, API Endpoints & Frontend Components
   - 5.13 Security, Cost Control, Caching, Provenance
6. [Computation Engine Upgrades](#6-computation-engine-upgrades)
7. [New Analytics Models & Indices](#7-new-analytics-models--indices)
8. [New Data Sources](#8-new-data-sources)
9. [Schema Changes (DDL)](#9-schema-changes-ddl)
10. [Revised Roadmap & First-90-Days Implementation Order](#10-revised-roadmap)
11. [Licensing & Legal Notes](#11-licensing--legal-notes)
12. [References](#12-references)

---

## 1. Executive Summary

The ARCHITECTURE.md plan is unusually coherent for a pre-implementation project: the 3-tier pipeline (raw → analytics → decisions), dual network/H3 representation, and modular report system are the right skeleton, and the chosen theories (BPR/Beckmann user equilibrium, Webster, Frank's walkability, LTS, space syntax, gravity accessibility) are all defensible, literature-standard choices. Nothing in the plan needs to be thrown away.

The review produced five structural findings:

**Finding 1 — Adopt a network-first spatial ontology.** The street/road network is the platform's essential analytical axis. Every metric, score, and recommendation should live on network elements (edges and nodes). Buildings, POIs, and transit stops are not co-equal layers: they are *anchored entities* — points projected onto their nearest network element, influencing edge metrics through distance-decayed attraction weights. 3D/volumetric analysis (urban canyon geometry, sky view factor, noise reflection, pollutant trapping) is a *separate module* that consumes building heights and street widths and writes enrichment attributes back to edges — never a dependency of the core 2D network analytics. This ontology (formalized in §4) matches how the strongest tools in the field are built (cityseer, pandana, space syntax) and resolves several schema ambiguities in the current plan.

**Finding 2 — The single biggest technical gap is travel demand.** The plan says "Traffic Flow Assignment" but never says where the origin–destination (OD) matrix comes from. BPR assignment without OD demand is undefined. This must become a first-class pipeline stage (zone-based gravity model fed by population rasters and POI attractions — §6.2). Several other planned features silently depend on data sources the plan never names: elevation (schema has the column, no source), transit frequencies (OSM has geometry, not schedules — GTFS is required for Route Overlap and "Transit Frequency Tuning"), and population (needed for walkability, accessibility, and equity).

**Finding 3 — Don't hand-build solvers that exist as maintained libraries.** AequilibraE (v1.6.x, active) ships bi-conjugate Frank-Wolfe user equilibrium — the exact Beckmann/BPR solver planned — and runs on in-memory graphs buildable from the OSMnx pipeline. UXsim (MIT, pure Python) adds mesoscopic dynamic simulation (queues, spillback) for the scenario sandbox at ~zero integration cost. Emission factors should come from the free EMEP/EEA COPERT Tier-3 coefficient tables, and noise from CNOSSOS-EU (simple emission formulas in NumPy now; the NoiseModelling Docker sidecar for publication-grade maps later). §6 details each.

**Finding 4 — The AI layer should be a tool-calling architecture, not a "text about data" architecture.** The 2023–2026 research record is unambiguous: LLMs fail at unaided geospatial reasoning (best models score <67% on MapEval; ~22% execution accuracy on hard Overpass queries; systematic coordinate biases of hundreds of meters), but excel when orchestrating typed tools over a trusted computation layer (TrafficGPT, Open-TI, SUMO-MCP, LLM-Geo). SmartStreet is perfectly shaped for this: every Tier-2 metric becomes a tool the LLM can call; the LLM writes words and decisions-with-rationale; the backend computes every number and resolves every geometry. Three hard rules follow (§5.1): the LLM never emits coordinates, never invents numbers, and every entity it mentions is validated against the DB before display. The network-first ontology makes this natural — the LLM's vocabulary is edge IDs and node IDs, which the backend resolves to geometry.

**Finding 5 — BYOK (paste-your-own-key) is a solved pattern with specific 2026 best practices.** Recommended stack: **Pydantic AI V2** as the single LLM dependency (provider abstraction across OpenAI/Anthropic/Gemini/Ollama, typed structured outputs with retry, streaming, MCP support, bundled evals), session-first key handling (never store keys in v1; envelope encryption if persistence is added), backend-only proxying, key validation via `models.list`, per-user token budgets, prompt caching, and full prompt/response provenance logging so every AI sentence in a PDF report is traceable (§5.2, §5.13).

Eight concrete AI capability tracks are specified in §5 with schemas, endpoints, and code. The highest value-per-effort additions beyond AI: gravity demand model, GTFS ingestion (gtfs_kit + Mobility Database), per-hex population (GHSL), edge grades from Copernicus GLO-30 DEM, momepy streetscape morphology, BNA-style low-stress cycling connectivity, 15-minute-city score, transit headway LOS, and accessibility-equity metrics (Gini/Theil) — each mapped to the network-first schema in §7–§9.

---

## 2. Assessment of the Current Architecture

### 2.1 What the plan gets right (keep as-is)

| Decision | Verdict |
|---|---|
| 3-tier pipeline with strict write-direction (raw → analytics → decisions) | Correct; it is exactly the "numbers from pipeline, words from LLM" separation the AI literature (CityBench, MapEval) recommends. Tier boundaries become the AI grounding boundary for free. |
| Dual representation (directed graph + H3 grid) with explicit interpolation formulas | Correct method choices; §4.5 refines the *roles*: network = analytical substrate, H3 = aggregation/presentation surface. |
| Progressive bbox tiers A/B/C | Correct; prevents the #1 failure mode of OSM-based tools (Overpass timeouts). |
| SQLite+SpatiaLite → PostGIS migration path | Correct order for a small team. One caveat: do the PostGIS move **before** shipping any NL-querying AI feature — LLMs know PostGIS far better than SpatiaLite dialect (§5.4). |
| Scenario overrides as sequence-numbered rows (undo/redo) | Correct; also turns out to be the ideal target representation for LLM-generated scenarios (§5.5). |
| WeasyPrint + Jinja2 modular report catalog | Correct; the report loader/template registry is exactly where grounded AI narrative slots in (§5.3). |
| Sensitivity analysis → confidence field on decisions | Correct and rare; extend it from BPR parameters to demand uncertainty (§6.2). |
| GA/SA for DNDP direction flipping | Correct problem framing (bilevel, discrete upper level, UE lower level). No maintained open-source DNDP solver exists, so metaheuristic + repair is the practical approach — but use pymoo/DEAP for the GA loop and AequilibraE warm-starts for fitness, not hand-rolled everything (§6.5). |

### 2.2 Intent read-back

The document reveals a consistent product thesis worth making explicit, because the AI layer should serve it: *SmartStreet turns open geodata into defensible, explainable street-design decisions for planners who are not data scientists.* Every recommendation carries impact, confidence, and rationale; every metric is traceable to a tier; scenarios are cheap to try. The AI layer's job is therefore not to be smart about cities — it is to make the pipeline's intelligence conversational, narrative, and auditable.

A second, newly explicit commitment (owner directive, 2026-07): **the street and road network is the essential axis of the whole platform**. Analysis is *of the network*; everything else either attaches to the network (buildings, places → anchored nodes with proximity/attraction effects) or enriches it from a separate module (3D canyon analysis). This is formalized in §4 and threaded through every subsequent section.

### 2.3 Where the plan is thinnest

- **Spatial ontology** — the current plan treats streets, buildings, POIs, and the H3 grid as sibling layers; the roles and coupling rules are undefined (which analyses read buildings? does walkability depend on 3D? where do POI effects enter edge scores?). §4 defines this precisely.
- **Demand modeling** — absent (Finding 2). §6.2.
- **AI section** — one roadmap line ("AI synthesis endpoint: packages Tier 2 data, calls LLM, stores rationale") and an `ai_rationale` column. The entire §5 of this report replaces that line.
- **Validation/calibration** — no plan for checking modeled flow, noise, or emissions against any observation (counts, sensors, stations). Partial fixes: OpenAQ/EEA stations for air quality (§8), golden-set eval for AI outputs (§5.10), demand calibration hooks (§6.2).
- **Users/auth** — no user model at all. Fine for local-first v1, but BYOK key handling and per-user budgets force a minimal `users` concept the moment the app is served to more than one person (§5.13).
- **Transit analytics depend on schedules** — Route Overlap Index and "Transit Frequency Tuning" are listed, but OSM contains geometry only. GTFS ingestion is a prerequisite, not an enhancement (§8.3).
- **StreetIQ definition** — "normalize each metric to [0,1]" is underspecified (min-max is outlier-dominated; metric direction varies). §7.8 proposes a robust formulation.

---

## 3. Gap Analysis

Severity: 🔴 blocks a planned feature · 🟠 materially weakens a planned feature · 🟡 improvement opportunity.

| # | Gap | Severity | What breaks without it | Fix (section) |
|---|---|---|---|---|
| G0 | Spatial ontology undefined (network vs. buildings vs. 3D coupling) | 🟠 | Schema ambiguity; analytics with hidden cross-dependencies; unclear UI layer semantics | Network-first ontology (§4) |
| G1 | No OD demand model | 🔴 | Traffic assignment, DNDP fitness, emissions, signal warrant volumes are all undefined | Zone-based gravity demand stage (§6.2) |
| G2 | No GTFS ingestion | 🔴 | Route Overlap Index, frequency tuning, stop-level LOS impossible from OSM alone | gtfs_kit + Mobility Database (§8.3) |
| G3 | No population data source | 🔴 | Frank's index (residential density term), gravity accessibility, equity metrics | GHSL/WorldPop per-hex → anchored to network (§8.2) |
| G4 | No elevation data source | 🟠 | `elevation`/`slope_gradient` columns stay NULL; LTS and walkability degrade | Copernicus GLO-30 + osmnx.elevation (§8.4) |
| G5 | AI layer unspecified (provider, grounding, security, UX) | 🔴 | The product's headline differentiator is a stub | Full AI architecture (§5) |
| G6 | Hand-rolled UE solver implied | 🟠 | Months of work to reach what AequilibraE ships; convergence bugs | AequilibraE engine (§6.1) |
| G7 | No dynamic/queueing model | 🟡 | Scenario sandbox can't show spillback, signal effects on queues | UXsim mesoscopic lane (§6.3) |
| G8 | Emission factors unspecified | 🟠 | "speed-dependent CO2/NOx" needs coefficient tables | EMEP/EEA Tier-3 XLSX (§6.6) |
| G9 | Noise model unspecified | 🟠 | "Noise Propagation Model" is a name, not a method | CNOSSOS-lite NumPy + NoiseModelling sidecar (§6.7) |
| G10 | Signal placement lacks adaptive baseline | 🟡 | Webster is fixed-time only; no queue-responsive comparison | MaxPressure on UXsim (§6.4) |
| G11 | No scenario-evaluation speedup path | 🟡 | GA over DNDP re-runs full UE per genome → hours | Warm-starts, caching, GNN surrogate later (§6.5, §6.8) |
| G12 | No validation against observations | 🟠 | Credibility gap with municipal customers | AQ stations, count-calibration hooks, golden set (§8, §5.10) |
| G13 | No users/auth model | 🟠 | BYOK keys and budgets have no owner entity | Minimal users table + session keys (§5.13) |
| G14 | Walkability missing streetscape/enclosure inputs | 🟡 | Frank's index covers density/mix but not street form | momepy streetscape module (§7.1) |
| G15 | LTS lacks connectivity interpretation | 🟡 | Stress labels per edge, but no "can you actually get anywhere low-stress" | BNA low-stress reachability (§7.4) |
| G16 | No equity dimension | 🟡 | Public-sector differentiator missed | Gini/Theil on access distribution (§7.6) |
| G17 | No green/heat environmental layer | 🟡 | Environment tier = noise+emissions only | Sentinel-2 NDVI, Landsat LST (§7.7) |
| G18 | StreetIQ normalization underspecified | 🟡 | Composite score dominated by outliers, sign errors | Robust scaling spec (§7.8) |
| G19 | OSM-only POI/building data | 🟡 | Sparse or stale POIs in many cities | Overture places + GERS IDs (§8.1) |
| G20 | No imagery ground-truth | 🟡 | Sidewalk presence, crossings, greenery unverifiable | Mapillary + VLM audits (§5.7) |

---

## 4. Network-First Spatial Ontology

> Owner directive (2026-07): *"Our focus is network analysis — the street and road network of the city is the essential axis. Buildings and places should be presented as nodes with proximity and attraction effects. Canyon and other 3D analysis should be a separate part."* This section makes that doctrine precise so every schema decision, analytic, and AI tool follows from it.

### 4.1 The Three Planes

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  PLANE A — NETWORK SPINE (the essential axis)                                │
│  Directed multigraph G = (V, E): intersections + street/road/path segments  │
│  ALL analytical results live here: per-edge & per-node metric columns.      │
│  Sub-networks: vehicular ⊇ cycling ⊇ pedestrian (shared node space).        │
├──────────────────────────────────────────────────────────────────────────────┤
│  PLANE B — ANCHORED ENTITIES (points that attach to the spine)              │
│  Buildings, POIs, transit stops, AQ sensors, charging points, population.    │
│  Each entity is PROJECTED onto its nearest network element and stored with  │
│  (anchor_edge_id, anchor_node_id, anchor_offset, network_distance).          │
│  Entities influence edge metrics ONLY through explicit attraction functions  │
│  w(d) with distance decay — never by direct geometry overlay.                │
├──────────────────────────────────────────────────────────────────────────────┤
│  PLANE C — 3D / VOLUMETRIC MODULE (separate, optional, decoupled)           │
│  Urban canyon geometry (H/W ratio), sky view factor, noise reflection,      │
│  pollutant trapping, shadow/insolation. Reads Plane A geometry + Plane B     │
│  building heights; WRITES enrichment columns back to edges. No Plane A or B  │
│  analytic may DEPEND on Plane C — it only gets refined by it.                │
└──────────────────────────────────────────────────────────────────────────────┘
```

The rule that makes this an ontology rather than a diagram: **every analytical question must be answerable as a function over Plane A**. Buildings and places never carry final scores; they contribute weight to the network. 3D effects never gate core results; they adjust them.

### 4.2 Plane A — The Network Spine

The spine is the directed multigraph already planned (`network_nodes`, `street_edges`, plus pedestrian/cycling edges sharing the node space). What changes:

1. **Edges and nodes are the only first-class analytical citizens.** `street_analytics`, `pedestrian_analytics`, `cycling_analytics` remain the canonical result tables. Any new metric (15-min score, transit LOS, green view, canyon factor) becomes a column or companion row *keyed by edge/node id* — not a new geometry layer.
2. **One consolidated node space.** Run `osmnx.consolidate_intersections` at ingest so "intersection" means a real junction, not an OSM topology artifact. All three modal sub-networks reference the same consolidated nodes; modal edges carry a `mode_mask` (vehicle/bike/foot bitmask) rather than living in disconnected graphs. This is what makes multimodal metrics (e.g., "pedestrian access to transit") a pure graph operation.
3. **Stable edge identity across refetches.** Add a deterministic `edge_key` (hash of sorted endpoint node coords + highway class) so analytics, scenarios, and AI references survive OSM refreshes; adopt Overture GERS IDs as a cross-reference when Overture ingestion lands (§8.1).
4. **The AI vocabulary is Plane A vocabulary.** LLM tools accept and return `edge_id` / `node_id` / `edge_key` — the geometry lookup is always the backend's job (§5.1).

### 4.3 Plane B — Anchored Entities (Proximity & Attraction)

Every non-network entity is reduced, for analytical purposes, to an **anchored node**: a point with a projection onto the spine.

**Anchoring (at ingest, once per entity):**

```
anchor_edge_id   = argmin over edges e of d(entity_centroid, e)     -- nearest edge
anchor_offset    = position along that edge, 0.0–1.0 (linear referencing)
anchor_node_id   = nearest consolidated intersection node
anchor_distance  = straight-line distance from centroid to the projected point (m)
```

Implementation: buildings collapse to `ST_Centroid`; POIs and stops are already points; population rasters are sampled to H3 cells whose centroids are then anchored the same way. Use an STRtree (Shapely 2) or PostGIS `<->` KNN for the projection; store results in an `entity_anchors` table (§9) so anchoring is computed once and reused by every analytic.

**Attraction (how entities affect the network):** all entity→edge influence flows through one shared kernel family, so "how much does this school affect this street" has a single, tunable answer everywhere:

```
w(d) = exp(-β · d_net)          -- gravity/exponential decay (default)
w(d) = 1 if d_net ≤ D else 0    -- cumulative-opportunity (15-min counts)
w(d) = (1 - (d_net/D)²)²        -- quartic kernel (KDE-style smoothing)
```

where `d_net` is **network distance from the entity's anchor point** (not Euclidean — this is the whole point of anchoring). Per-analytic parameters (β, D) live in one `attraction_params` config table. Concretely:

| Entity type | Attraction it exerts on edges | Consumed by |
|---|---|---|
| POI (shop, school, clinic…) | opportunity weight by category | Hansen access, 15-min score, Walk-Score-like, land-use mix |
| Building (residential) | population/dwelling weight (via GHSL dasymetric split) | walkability density term, demand generation, equity |
| Building (any) | mass/height at anchor | *inputs to Plane C only* |
| Transit stop | boarding opportunity, headway-weighted | transit LOS on nearby edges, stop catchments |
| AQ/weather sensor | observation with IDW credence | calibration of modeled emission/noise layers |
| EV charger | service weight | electrification-readiness corridor indicator |

This resolves a quiet ambiguity in the original plan: Frank's index, gravity accessibility, POI density, and stop catchments each implied their own ad-hoc buffering of points near streets. Under the ontology they are all *the same operation* — anchored entities aggregated onto edges/nodes through a kernel — implemented once (pandana and cityseer are purpose-built engines for exactly this aggregation pattern; see §7.2–§7.3).

**Rendering note:** on the map, Plane B entities may still be *displayed* as polygons (building footprints look right extruded in 3D), but their analytical existence is the anchored node. Display geometry ≠ analytical geometry.

### 4.4 Plane C — 3D / Volumetric Module (Separate)

Everything that requires the third dimension is quarantined in one module with a narrow contract:

**Inputs:** edge geometry + width (Plane A), building heights/levels at anchors within a corridor buffer of each edge (Plane B), optionally DEM.

**Analyses (roadmap order):**
1. **Canyon geometry**: per-edge height-to-width ratio `H/W` (mean flanking building height ÷ street width; momepy `street_profile` computes exactly this — §7.1), canyon symmetry, orientation.
2. **Sky View Factor (SVF)** per edge midpoint — standard estimator from flanking heights; refines both noise and thermal comfort.
3. **Noise enrichment**: canyon reflection correction to the CNOSSOS emission-only baseline (§6.7) — multiple-reflection addition as a function of H/W (up to ~+3 dB in deep canyons).
4. **Pollutant trapping**: canyon-aware dispersion modifier for the emission layer (deep canyons with low wind → concentration multiplier; literature-standard operational street-canyon parameterization, e.g., OSPM-style).
5. Later: shadow/insolation hours per sidewalk, wind channeling.

**Outputs:** columns written back to Plane A (`street_analytics.canyon_hw`, `svf`, `noise_canyon_db_adj`, `pm_trap_factor`) plus an H3 presentation layer.

**The decoupling contract:** Plane A/B analytics must produce valid results when Plane C has never run (all its columns NULL → adjustments default to 0). The UI presents Plane C as its own panel section ("3D / Canyon") with its own run button, and reports mark canyon-adjusted values explicitly. This keeps the core network pipeline fast, testable, and runnable in cities with poor building-height data — and lets the 3D module grow ambitious (CFD-lite, shadow casting) without ever blocking a release.

### 4.5 Where the H3 Grid Fits

The dual-representation section of ARCHITECTURE.md stands, with sharpened roles: **H3 is an aggregation and presentation surface, not an analytical home.** Metrics are computed on Plane A, then projected to H3 for choropleth display, cross-city comparison, and as a convenient zoning system (demand model zones, population anchoring, equity aggregation). The two interpolation formulas already specified (length-weighted network→grid, IDW grid→network) are correct; the only addition is that grid→network interpolation is reserved for genuinely ambient fields (air quality from CAMS/OpenAQ, weather, LST) — never for entity effects, which flow through anchors (§4.3).

### 4.6 Consequences for Schema, Pipeline & UI

- **Schema**: new `entity_anchors` and `attraction_params` tables; `mode_mask` and `edge_key` on edges; Plane C columns on `street_analytics` (all nullable); `points_of_interest` and `building_footprints` unchanged as *storage* but always joined through anchors for analysis. DDL in §9.
- **Pipeline ordering**: ingest → consolidate intersections → anchor entities → (analytics …) → optional Plane C enrichment → decisions. Anchoring is stage 2, not an afterthought.
- **UI**: layer panel groups reorganize to mirror the planes — "Network" (streets/pedestrian/cycling + metric coloring), "Places" (buildings, POIs, stops — rendered but flagged as anchored), "3D & Environment" (canyon, SVF, extrusions), "Grid" (H3 overlays). The inspector popup for any building/POI shows *its anchor*: which edge it attaches to, at what network distance, and which analytics it currently influences — making the ontology visible and debuggable.
- **AI**: tool schemas expose Plane A queries (`get_edge_metrics`, `top_edges_by`), Plane B queries (`entities_near_edge`, `access_from_node`), and Plane C as clearly-labeled enrichment (`canyon_profile`) — the LLM cannot confuse display layers with analytical truth (§5).

---

## 5. AI Integration Architecture

This is the core of the report. The design goal: **AI as the platform's narrator, analyst, and scenario author — never its calculator or cartographer.** Users paste their own API keys (OpenAI / Anthropic / Google / local Ollama); SmartStreet orchestrates those models over its own trusted computation layer.

### 5.1 Ground Rules (what the research says)

The 2023–2026 evidence base converges on a clear division of labor:

- **MapEval** (ICML 2025): none of 30 frontier models (GPT-4o, Claude 3.5, Gemini 1.5) exceeded 67% on map reasoning; distances, directions, and route planning are systematically weak.
- **Text-to-OverpassQL** (TACL 2024): GPT-4 with retrieval-augmented few-shot reaches only ~22% execution accuracy on hard OSM queries.
- **Coordinate studies** (2025–26): systematic latitude bias of ~316 m mean; models "pull" coordinates toward prominent landmarks; GPS-coordinate understanding fundamentally unreliable.
- **GeoSQL-Eval** (2025): general LLMs score <60% generating PostGIS spatial SQL (function selection, SRID handling, multi-hop spatial reasoning fail).
- **CityBench / UrbanPlanBench** (2025): LLMs handle semantic/commonsense urban tasks well but fail numeric geospatial prediction and traffic control; even the best fall short of professional-planner exam standards.
- **What works**: TrafficGPT, Open-TI, SUMO-MCP, LLM-Geo, GeoGPT — all successful systems are *tool-calling controllers* over curated, typed toolsets; UrbanKGent adds tool-based self-verification of claims before output.

Therefore, five hard rules enforced in code (not in prompts alone):

| Rule | Enforcement |
|---|---|
| **R1 — No LLM coordinates or geometry.** The model references `edge_id`/`node_id`/`h3_index`; backend resolves geometry. | Output schemas contain ID fields only; any lat/lon in free text is stripped by a regex post-filter and replaced with entity links. |
| **R2 — No LLM arithmetic on metrics.** Every number shown to users comes from Tier 2/3 tables. | Narrative templates interpolate numbers server-side; LLM output referencing numbers not present in the input packet fails validation (§5.3). |
| **R3 — Every entity mention is verified.** Street names / IDs the model cites must exist in the region. | Post-generation pass resolves each cited ID against the DB; unresolvable citations → regenerate or flag (UrbanKGent pattern). |
| **R4 — Structured output or no output.** All machine-consumed AI responses are Pydantic-validated with bounded retry, then abstain. | Pydantic AI `output_type` + reflection retries (≤3), then graceful "cannot answer reliably". |
| **R5 — Everything logged.** Prompt, context packet, model, tokens, cost, output, validation result. | `ai_interactions` table (§5.12) + optional Langfuse. |

### 5.2 AI Gateway: BYOK Key Management & Provider Abstraction

**Library decision: Pydantic AI V2** (stable since June 2026) as the single LLM dependency. Rationale: model-agnostic across exactly the four required providers (OpenAI, Anthropic, `google-genai`, Ollama via OpenAI-compatible endpoint), FastAPI-native dependency-injection idioms, typed `output_type` with automatic validation-retry, `FallbackModel`, streaming with UI event protocols, MCP client+server, `TestModel` for key-free CI, and bundled `pydantic-evals`. Alternatives considered: LiteLLM SDK (good thin abstraction, keep as optional cost-map/router utility; its proxy server is overkill here), LangGraph (ceremony unneeded until multi-day stateful workflows), OpenAI Agents SDK (provider-centric), smolagents (executes model-written Python — a sandboxing liability in a web backend).

**Key handling (v1 — session-only, "we never store your key"):**

```
POST /api/ai/keys          {provider, api_key}  → validate → keep in server-side
                           session store (Redis or in-memory dict keyed by session id,
                           TTL 24h, AES-GCM under an ephemeral process key)
GET  /api/ai/keys          → [{provider, last4, models_available, status}]
DELETE /api/ai/keys/{provider}
```

- **Validation on paste** (cheapest authenticated call): OpenAI/Anthropic `GET /v1/models`; Gemini `models.list`; Ollama `GET /api/tags`. Return the model list so the UI can populate a model picker per provider.
- **Backend-only proxying**: the React app never talks to providers; every call goes through FastAPI tagged with session/user id. No keys in browser storage, no CORS pain, full logging.
- **v2 (optional persistence)**: envelope encryption — per-user AES-256-GCM data key, wrapped by a master KEK (file-sealed for self-host, KMS for cloud). Show last-4 only; instant delete; scrub keys from all logs and tracebacks (custom logging filter).
- **Budgets even though users pay**: per-session daily token budget + concurrent-stream cap (protects against runaway agent loops and abuse of leaked keys). Configurable in Settings.

**Model routing config** (stored per project): `{task: {provider, model, max_tokens, temperature}}` for tasks = `narrative | analyst | scenario | vision | debate | embedding`. Defaults: narrative/analyst → user's best available reasoning model; vision → Gemini or GPT-4o-class (research shows strongest geospatial imagery performance); embedding → **platform-level** local model (BGE-M3 via Ollama) or OpenAI `text-embedding-3-small` — never per-user keys for embeddings (index fragmentation; see §5.8).

```python
# backend/services/ai/gateway.py
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.openai import OpenAIProvider

def build_model(cfg: TaskModelConfig, keys: SessionKeys):
    match cfg.provider:
        case "openai":    return OpenAIChatModel(cfg.model, provider=OpenAIProvider(api_key=keys["openai"]))
        case "anthropic": return AnthropicModel(cfg.model, api_key=keys["anthropic"])
        case "google":    return GoogleModel(cfg.model, api_key=keys["google"])
        case "ollama":    return OpenAIChatModel(cfg.model, provider=OpenAIProvider(
                                 base_url="http://localhost:11434/v1", api_key="ollama"))
```

### 5.3 Capability Track AI-1: Grounded Narrative Synthesis

*The planned "AI synthesis endpoint", specified.* Turns Tier-2/3 results into the prose that fills report sections, recommendation rationales, and the dashboard "AI card".

**The Metric Packet pattern** (from TrafficGPT / structured-prompting practice): the backend assembles a compact, ID-rich JSON context — never raw tables:

```json
{
  "region": {"name": "Ljubljana SE", "area_km2": 3.2, "edges": 4231},
  "time_slot": "morning_rush",
  "headline_metrics": {"avg_delay_s": 42.1, "total_co2_kg_h": 512.4, "walkability_p50": 0.61},
  "top_bottlenecks": [{"edge_id": 1042, "name": "Slovenska cesta", "v_c_ratio": 1.31, "delay_s": 118}, ...],
  "worst_walkability": [{"edge_id": 2210, "name": null, "index": 0.12, "missing": ["lit", "surface"]}, ...],
  "scenario_delta": {"baseline": "Baseline", "modified": "One-Way Center",
                     "total_travel_time_pct": -8.2, "co2_pct": -5.1, "walkability_pct": +0.4},
  "data_quality": {"completeness": 0.67, "caveats": ["maxspeed imputed on 41% of edges"]}
}
```

**Output contract** (Pydantic): `NarrativeSection{title, markdown_body, cited_edge_ids: list[int], caveats: list[str], confidence: Literal["high","medium","low"]}`. Validation asserts every number in `markdown_body` appears in the packet (R2) and every `edge_id` resolves (R3).

**System prompt skeleton** (static → cacheable): role ("transport planning analyst writing for a municipal audience"), the five ground rules, house style (impact → evidence → caveat ordering; no superlatives without a metric; SI units), and 2–3 few-shot exemplars. The packet is the only dynamic part — this maximizes prompt-cache hits (90% input discount on all three providers; order static-first matters).

**Where it lands**: `actionable_decisions.ai_rationale` (per decision), a new `report_narratives` table keyed by (report_id, section) so PDF reports embed reviewed text, and the right-sidebar AI card. Each of the 8 report modules registers which packet-builder feeds its narrative section — the existing `REPORT_CATALOG` pattern extends cleanly: `"narrative_packets": [build_traffic_packet, ...]`.

### 5.4 Capability Track AI-2: Conversational Analyst (Tool-Calling Agent)

The "Ask AI" button becomes a chat panel where planners interrogate the network: *"Which streets got worse for cyclists in this scenario?" "Why is this intersection flagged for a signal?"*

**Architecture: curated typed tools, NOT free-form text-to-SQL.** GeoSQL-Eval's <60% accuracy on spatial SQL settles this: the model must not write `ST_DWithin`. Instead, ~12–18 parameterized tools wrap operations the pipeline already performs. Draft toolset:

| Tool | Signature (abridged) | Plane |
|---|---|---|
| `get_region_summary` | `(region_id) → stats` | A |
| `get_edge_metrics` | `(edge_ids[], time_slot) → rows` | A |
| `top_edges_by` | `(metric, n, ascending, time_slot, mode) → rows` | A |
| `compare_scenarios` | `(baseline_id, modified_id, metrics[]) → deltas (+per-edge top movers)` | A |
| `get_node_signal_analysis` | `(node_id) → CPI, Webster delay, centrality` | A |
| `entities_near_edge` | `(edge_id, category?, max_net_dist) → anchored entities` | B |
| `access_from_node` | `(node_id, mode, minutes) → reachable POIs by category, population` | B |
| `isochrone_stats` | `(node_id, mode, minutes) → area, population, POI counts` | B |
| `canyon_profile` | `(edge_id) → H/W, SVF, adjustments` (labeled enrichment) | C |
| `get_data_quality` | `(region_id | edge_ids[]) → completeness, imputed fields` | meta |
| `search_edges` | `(name_query) → candidate edges` (resolves street names → IDs) | meta |
| `run_analysis` | `(kind, params) → job_id` — **requires user confirmation in UI** | action |
| `propose_scenario` | delegates to AI-3 (§5.5) — confirmation gated | action |

Read tools execute immediately; action tools return a confirmation card the user must click (human-in-the-loop, consistent with UrbanPlanBench's finding that LLM planning must stay advisory). For long-tail analytical questions not covered by tools, add *one* escape hatch later: `query_analytics_view(sql)` restricted to 5–10 flat, documented, non-spatial views, validated by sqlglot AST (SELECT-only, allow-listed views, LIMIT injected), read-only role, statement timeout, execution-feedback retry ≤3, then abstain — and only after the PostGIS migration.

```python
# backend/services/ai/analyst.py
analyst = Agent(
    deps_type=AnalystDeps,          # db session, region_id, scenario_id, user
    output_type=str,                 # markdown answer with [edge:1042] link tokens
    system_prompt=ANALYST_RULES,     # ground rules + tool guidance + abstention policy
)

@analyst.tool
async def top_edges_by(ctx: RunContext[AnalystDeps], metric: MetricName,
                       n: int = 10, ascending: bool = False,
                       time_slot: TimeSlot = "morning_rush") -> list[EdgeMetricRow]:
    """Rank street edges by a Tier-2 metric. Returns ids, names, values."""
    return await queries.top_edges(ctx.deps.db, ctx.deps.region_id, metric, n, ascending, time_slot)
```

**Frontend contract**: SSE stream (sse-starlette `EventSourceResponse`) with events `token`, `tool_call`, `tool_result`, `entity_refs`, `cost`, `done`. The chat renders `[edge:1042]` tokens as hoverable chips that highlight/zoom the map — the answer *is* a map interaction, which is SmartStreet's differentiation over a generic chatbot. (GIS Copilot's finding: agents embedded in the GIS UI outperform standalone chat.)

### 5.5 Capability Track AI-3: Scenario Generation (NL → Scenario Overrides)

*"Make the city center a 30 km/h zone, pedestrianize the market street, and flip the one-way pair on the ring."* → a named scenario with sequenced `scenario_overrides` rows, previewed as map diff, applied only on user confirm.

The existing `scenario_overrides` design (target_type, target_id, action_type, attribute_overrides JSONB, sequence_number) is a perfect LLM target — small, discrete, validatable. Output schema:

```python
class ProposedOverride(BaseModel):
    target_type: Literal["street", "pedestrian", "cycling", "transit"]
    target_edge_ids: list[int]                 # resolved via search_edges tool, never geometry (R1)
    action_type: Literal["closure", "direction_change", "attribute_change"]
    attribute_overrides: dict[str, int | str | bool] = {}
    rationale: str

class ProposedScenario(BaseModel):
    name: str
    description: str
    overrides: list[ProposedOverride]          # ordered
    expected_effects: list[str]                # qualitative only; numbers come from re-analysis
    warnings: list[str]                        # e.g. "severs bus line 6", "creates dead-end"
```

**Validation cascade** before anything is shown: (1) Pydantic schema; (2) every `target_edge_id` exists in region (R3); (3) *network feasibility* — apply overrides to a graph copy, run NetworkX strong-connectivity + isolated-subgraph checks, transit-route severance check; (4) legality guards (no `maxspeed` on footways, etc.). Failures feed back for one repair round (execution-feedback loop — the single most effective reliability technique in the geospatial-codegen literature), then surface as warnings. Note `new_construction` is deliberately excluded from v1: AI-drawn geometry violates R1; "AI-generated scenario layouts" stays in the R&D backlog exactly where ARCHITECTURE.md put it.

After user confirmation, the standard pipeline takes over: overrides applied → Tier-2 recompute → scenario comparison → AI-1 narrates the measured (not predicted) deltas. The LLM proposes; the pipeline disposes.

### 5.6 Capability Track AI-4: Persona Debate on Recommendations

From *LLM-empowered participatory urban planning* (Zhou, Lin & Li, 2024 — role-played planner + resident agents beat human experts on satisfaction/inclusion metrics) and the 2025 multi-stakeholder generative-agents line: before a Tier-3 decision is finalized, a small persona panel critiques it.

- 4–8 fixed personas: commuter-driver, cyclist, parent-pedestrian, transit rider, local shop owner, delivery operator, resident (noise/air), emergency services.
- Each receives the *same* metric packet plus persona-specific derived metrics (e.g., cyclist gets LTS deltas along desire lines; shop owner gets footfall-proxy changes from anchored-POI access).
- One round: each persona emits `{position: support|oppose|conditional, top_concerns[], affected_edge_ids[]}`; a moderator call synthesizes `objections_summary` + `mitigations[]`.
- Weight persona salience by measured mode share / anchored-entity density (from Plane B), not vibes: a proposal touching a street with 40 anchored shops elevates the shop-owner persona.
- Lands in `decision_debates` table; rendered as an expandable "Stakeholder lens" on each recommendation card and an optional report section. Cost control: single round, small packets, batched (~8 short calls per decision).

This is a few hundred lines for a genuinely differentiating feature — recommendation cards that anticipate objections.

### 5.7 Capability Track AI-5: VLM Street Audits (Imagery → Scores)

Pattern from **SAGAI** (2025, open source) + peer-reviewed GPT-4o street-audit validations: sample points along Plane-A edges → fetch street-level imagery → VLM scores prompt-defined indicators → aggregate to per-edge columns.

- **Imagery: Mapillary** (CC-BY-SA, free API v4, includes detections/traffic-sign layers). **Not Google Street View** — its ToS prohibit bulk/ML analysis.
- Indicators v1 (structured 0–5 outputs + booleans): sidewalk presence/continuity, crossing quality, greenery (Green View proxy), night-lighting cues, parked-car intrusion, façade activity.
- Calibration caveat from the PLOS ONE 2025 study: VLM ratings align with humans on *functional* attributes (infrastructure presence) but diverge on *perceptual* comfort — so v1 audits feed only functional fields (e.g., filling `pedestrian_edges.lit`, `tactile_paving`, sidewalk gaps) and a `visual_quality` column expressly labeled model-estimated.
- Sampling: 1 point per ~50 m, max N images per edge, dedupe by capture angle; batch through the user's vision-capable key (Gemini-class recommended); cache aggressively (`street_audits` table keyed by image_id + prompt_version).
- These audit columns then flow into Frank's index (missing-data imputation) and iRAP-lite safety proxies (§7.5) — closing gap G20 with ground truth OSM can't provide.

### 5.8 Capability Track AI-6: RAG over Municipal Plans & Standards

Lets recommendations cite local policy: *"conflicts with Mobility Plan 2030 §4.2"* (Urban Institute zoning-RAG and PlanGPT patterns).

- **Corpus: user-uploaded documents only** (municipal mobility plans, local street-design guides). Copyrighted manuals (NACTO, CROW) must be user-supplied licensed copies in per-project private indexes — never a shared platform corpus (§11).
- Chunking: heading-aware, ~500–800 tokens, store page numbers for citations.
- **Embeddings: one platform-level model** (local BGE-M3 via Ollama for a key-free default, or OpenAI text-embedding-3-small) — never per-user keys, or the index fragments across embedding spaces.
- Store: `sqlite-vec` during the SQLite phase (adequate, but maintenance-slowed — treat as temporary) → **pgvector** after the PostGIS migration. One `documents`/`doc_chunks` schema either way (§9).
- Retrieval joins AI-1/AI-2/AI-4 context packets as `policy_context[]` with mandatory `{doc, page, quote}` citations rendered as footnotes in reports.

### 5.9 Capability Track AI-7: LLM-Assisted Optimization

Two research-backed, low-risk injections into the planned GA/SA optimizer (§6.5):

1. **Seeding** (EoH-line evidence that LLMs propose good heuristic starting points): before the GA runs, ask the LLM — given the bottleneck packet — for 20–50 candidate direction-flip genomes near congested corridors (edge-ID lists, R1-compliant). Seed a portion of the initial population; keep the rest random. Cheap, measurable (compare convergence curves with/without), zero correctness risk since fitness always comes from the solver.
2. **Weight elicitation** (Intelli-Planner pattern): a short dialogue turns a user's stated priorities ("safety first, then emissions; don't hurt transit") into StreetIQ weight vectors and multi-objective GA weightings, stored as a named preference profile on the project.

Explicitly rejected: LLM-as-fitness-evaluator (CityBench shows numeric traffic judgment is exactly what LLMs lack).

### 5.10 Capability Track AI-8: Golden-Set Evaluation Harness

The field's clearest lesson: ungrounded LLM geography fails silently, so regression-test the AI layer against the pipeline's own computed truth.

- ~100 question/answer pairs *generated from the DB*: "Which of these 5 edges has highest betweenness in morning_rush?" (answer known), "Does scenario B reduce CO₂ vs baseline?" (known), name-resolution probes, abstention probes ("What's the crash count?" — no crash data loaded → must abstain).
- Runner: `pydantic-evals` (bundled with Pydantic AI) in CI with `TestModel` for structure and a cheap real model weekly; assertions: exact-answer accuracy, citation resolvability (R3), abstention correctness, zero-coordinate rule (R1).
- Gate: any prompt change, tool-schema change, or provider default change must pass the golden set before merge. Track per-provider scores in `ai_eval_runs` — this also powers an honest "which model works best for this" recommendation in Settings.

### 5.11 MCP Server: SmartStreet as a Tool Provider

MCP is now the vendor-neutral standard (Linux Foundation, Dec 2025; all major clients speak it). Since §5.4 already defines typed analytics tools, exposing them via **FastMCP** (official Python SDK) is ~2–3 days of work and turns SmartStreet into infrastructure: a planner's Claude/ChatGPT/IDE session can query their city's metrics directly (SUMO-MCP validated this pattern for traffic toolchains). Same functions, two registrations (Pydantic AI internal agent + MCP server); streamable-HTTP transport; token auth; read-only tools by default, action tools excluded from the public surface.

### 5.12 AI Database Schema, API Endpoints & Frontend Components

**New tables** (full DDL in §9): `users` (minimal), `ai_task_configs`, `ai_interactions` (provenance: task, model, packet hash, prompt/response, tokens, cost, validation status, latency), `report_narratives`, `decision_debates`, `street_audits`, `documents` + `doc_chunks` (+vector index), `ai_eval_cases` + `ai_eval_runs`, `entity_anchors`, `attraction_params` (§4).

**Endpoints:**

```
POST   /api/ai/keys                        validate & hold session key
GET    /api/ai/keys                        list providers + models + last4
DELETE /api/ai/keys/{provider}
GET    /api/ai/config        PUT …         task→model routing
POST   /api/ai/narrate                     {packet_kind, region, scenario, time_slot} → SSE
POST   /api/ai/chat                        {message, context} → SSE (tools, entity_refs, cost events)
POST   /api/ai/scenario/propose            {instruction} → ProposedScenario (+validation report)
POST   /api/ai/scenario/{id}/apply         confirmation gate → creates overrides
POST   /api/ai/debate/{decision_id}        persona panel → decision_debates
POST   /api/ai/audit/street                {edge_ids | bbox} → job (Mapillary+VLM)
POST   /api/documents  /api/documents/{id}/index      upload + embed
GET    /api/ai/interactions?report_id=…    provenance browser
POST   /api/ai/eval/run                    golden set execution
```

**Frontend components:** ① Settings→AI: key paste + validation status + model routing + budget + "never stored" copy. ② Right-sidebar **AI Analyst chat** with entity-chip ↔ map linking, tool-call transparency ("looked up top 10 bottlenecks"), streaming, per-message cost badge. ③ **Recommendation cards** (Green-Light style): what/where (map-linked), expected impact % (from pipeline), confidence (sensitivity), stakeholder lens (AI-4), policy citations (AI-6), rationale (AI-1). ④ **Scenario proposal diff-preview** modal (proposed overrides on map + warnings) with Apply/Discard. ⑤ Report generation dialog gains "include AI narrative ✓ (reviewed)" checkboxes with inline editing before PDF compile.

### 5.13 Security, Cost Control, Caching, Provenance

- **Threat model additions**: prompt injection via OSM data (street names are user-generated content! a `name="Ignore previous instructions…"` tag must be treated as data — wrap all DB strings in delimited data blocks, instruct model accordingly, and strip control tokens); SSRF via document upload (sanitize, no URL fetch in v1); key exfiltration (session-only storage, log scrubbing filter, last4-only display).
- **Cost**: static-first prompt layout for provider caching (90% input discount); packet compaction (IDs + rounded numbers); per-request cost surfaced in UI (LiteLLM cost map or `tokencost`); daily budget with hard stop + friendly resume.
- **Rate/abuse**: token-bucket per session; concurrent-stream cap (2); tool-call cap per turn (8); wall-clock cap per agent run (60 s).
- **Provenance**: every AI artifact in a report footnoted with interaction id; `ai_interactions` retained with the project so a municipality can audit "why did the tool say this" years later. Optional self-hosted Langfuse for tracing during development.
- **Graceful degradation ladder**: no key → all AI panels show "connect a provider" but *every* analytic still works; key without vision → audits disabled only; Ollama-only → narrative/chat on local models, vision marked unavailable. The platform must never gate a deterministic feature behind AI availability.

---

## 6. Computation Engine Upgrades

All engines operate on Plane A (§4.2). Recommended minimal stack: **AequilibraE** (equilibrium assignment) + **own gravity demand** + **UXsim** (dynamics) + **own Webster/MaxPressure** + **pymoo GA** (DNDP) + **EMEP/EEA factors** (emissions) + **CNOSSOS-lite → NoiseModelling sidecar** (noise). SUMO stays an optional high-fidelity lane; GNN surrogate is a Phase-later accelerator.

### 6.1 Traffic Assignment: AequilibraE (replace hand-rolled UE)

- **What**: multi-class user equilibrium with MSA, Frank-Wolfe, conjugate and **bi-conjugate Frank-Wolfe** (state of the art for link-based UE), generalized cost, skimming, IPF; active project (v1.6.2, Apr 2026), permissive license.
- **How it fits**: its algorithms run on in-memory graph objects built from Pandas/NumPy — feed it link/node DataFrames exported from the OSMnx graph; you do *not* adopt its SpatiaLite project format (though it natively uses SpatiaLite too, a happy coincidence for debugging). Run inside a FastAPI background worker; write `modeled_flow_volume`, `modeled_delay` (BPR at equilibrium flows) back to `street_analytics`.
- **Scenario sandbox**: closures/flips = rebuild the link DataFrame with overrides applied → re-assign. Warm-start from baseline link flows for GA inner loops.
- **Effort**: ~1 week to first converged assignment on a demo city. Validate once against the classic Sioux Falls dataset (public TNTP files) before trusting city runs.

### 6.2 Travel Demand: the missing stage (closes G1)

Standard, defensible minimal chain — all formulas are textbook (Ortúzar & Willumsen):

1. **Zones**: H3 res-8/9 cells within the region (the grid earns a second job as TAZ system).
2. **Productions**: per-zone population (GHSL raster → hex → §8.2) × trip rate per time slot (defaults from literature, editable in Settings).
3. **Attractions**: per-zone weighted anchored-POI/building counts (Plane B attraction weights by category — jobs-proxy: offices/shops/schools).
4. **Distribution**: doubly-constrained gravity with exponential deterrence `f(c_ij)=exp(-β·c_ij)`, costs from free-flow skims (AequilibraE), balanced by IPF (~50 lines of NumPy; or PySAL `spint` for calibrated GLM variants).
5. **Assignment**: §6.1. 
6. **Calibration hooks**: if the user has *any* counts (manual, municipal), adjust β and trip rates to minimize count error (simple grid search first; ODME later). Store demand parameters + provenance in `demand_models` table (§9); sensitivity analysis (already planned for BPR α/β) extends to β_gravity and trip rates → the same confidence field.

Honest-uncertainty note for the UI and reports: with no local calibration data, flows are *relative* screening indicators, not forecasts — exactly the framing municipal reviewers respect. (OMOD, an OSM-calibrated activity-based generator, is the upgrade path if German-style HTS-calibrated realism is wanted later.)

### 6.3 Dynamic Simulation: UXsim (new capability, ~free)

- **What**: pure-Python mesoscopic simulator (Newell/kinematic-wave), dynamic user-optimal routing, built-in signals, OSM import, pandas outputs; MIT license; active (v1.13, Mar 2026; JOSS 2025 paper; faster C++ sibling UXsimpp exists). 60k vehicles ≈ 30 s.
- **Why**: static UE (§6.1) can't show queues, spillback, or signal timing effects — precisely what planners ask about in scenario comparisons. UXsim gives "before/after animation + queue metrics" for the sandbox at `pip install uxsim` cost.
- **How**: convert Plane-A subgraph + OD (from §6.2, time-sliced) → UXsim World; run; write per-edge time-sliced speeds/queues to `street_analytics_dynamic` (§9); drive the map's time-slider animation from it. Also the natural testbed for MaxPressure (§6.4) and, later, RL experiments.

### 6.4 Signals: Webster + MaxPressure (+ Green-Light-style cards)

- **Webster** (planned — keep): ~30 lines: optimal cycle `C₀=(1.5L+5)/(1−Y)`, green splits by flow ratios, Webster delay per approach (needs §6.2 volumes). SUMO's `tlsCycleAdaptation.py` is a reference implementation to test against.
- **Add MaxPressure** (Varaiya 2013): decentralized, model-free, provably stabilizing; needs only per-movement queue estimates — available from UXsim. Gives the platform an *adaptive* baseline to compare against fixed-time, answering "would a smart signal help here?" without RL complexity. (RL-based control: research-only for now — sim-to-real gap; revisit via SUMO-RL/LibSignal later.)
- **Placement logic** (planned CPI + centrality — keep) upgraded to output **recommendation cards** in the Google Green Light style: intersection (node-linked), proposed change (new signal / retiming with cycle+splits), expected delay/emission impact from Webster+UXsim, implementation effort tag, confidence. This card format is the product benchmark users will recognize.

### 6.5 DNDP Direction Optimizer: engineering the planned GA/SA

No maintained OSS DNDP solver exists — the plan to build one is right. Make it tractable:

- **Encoding**: gene per candidate street (not per edge): `{keep, flip, make_oneway_A, make_oneway_B}`; candidate set pre-filtered (two-way streets in congested corridors, or user-selected area) to keep genome ≤ ~200.
- **Feasibility repair**: after mutation, strong-connectivity check (NetworkX `is_strongly_connected` on the affected component) + transit-severance check; repair or reject.
- **Fitness**: total system travel time from AequilibraE **warm-started** at parent flows, relative-gap 1e-3 (screening precision); cache genome→fitness (dict on genome hash — GA revisits).
- **Solver**: **pymoo** (Apache-2, active) NSGA-II — multi-objective from day one: minimize TSTT, minimize CO₂ (§6.6), maximize walkability-preservation; SA fallback via simple loop for small cases. Population 50–100, generations 50–200 → hundreds–thousands of assignments: with warm-starts and a 5k-edge network this is minutes–hours, acceptable for an overnight job; surface progress via the existing computation_log + progress bar.
- **AI hooks**: LLM seeding + weight elicitation (§5.9); GNN surrogate pre-filter later (§6.8).
- **Literature anchors** (cite in methodology report section): LeBlanc 1975 (problem class); Wang, Meng & Yang 2013 (global-optimal benchmarks, small nets); GA/SA metaheuristic line incl. Drezner & Wesolowsky one-way network design; Miandoabchi & Farahani direction+lane allocation.

### 6.6 Emissions: EMEP/EEA (COPERT) Tier-3 factors (closes G8)

- **Source**: EMEP/EEA Guidebook road-transport chapter — speed-dependent emission-factor functions EF(v) per vehicle segment/Euro class, with full coefficients in a **freely downloadable XLSX** (2023 guidebook, 2024/25 updates). The COPERT *software* is commercial; the formulas/coefficients are open.
- **Implementation**: one-time ingest of the coefficient sheet → `emission_factors` table; per edge & time slot: `E = volume × length × EF(v_congested)` where `v_congested` comes from BPR at equilibrium (§6.1) or UXsim speeds (§6.3). Fleet mix: default Euro-class distribution per country (editable) — store as region parameter.
- CO₂, NOx, PM per edge → `street_analytics`; H3 aggregation for the pollution layer; canyon trap factor from Plane C multiplies *concentration proxy*, never the emission mass (§4.4).
- If SUMO is used for a flagship study, its built-in HBEFA4-derived model provides a cross-check. (HBEFA database itself: paid license — skip. US MOVES: Java+MariaDB, US-centric — skip.)

### 6.7 Noise: CNOSSOS-lite now, NoiseModelling sidecar later (closes G9)

- **Tier 1 (in-process, instant)**: CNOSSOS-EU *road emission* only — sound power `L_w` per edge from flow, speed, fleet mix (published closed-form coefficients) + geometric divergence + air absorption in NumPy → indicative façade-free `noise_level_db` per edge and a "noise delta" that updates live in the scenario sandbox. Honest label: screening indicator, no buildings/reflection.
- **Tier 2 (full maps)**: **NoiseModelling** (Université Gustave Eiffel; GPL Java; v6.0, May 2026 — very alive) as a **Docker sidecar** called via CLI/WPS: full CNOSSOS propagation (diffraction, reflections, ground, meteo), building-aware, Lden/Lnight, population exposure. GPL isolation via process boundary keeps SmartStreet's license clean (§11). Feed it edges+flows+buildings; import result grids to H3 + IDW back to edges (§4.5 rule: ambient fields may use grid→network).
- Plane C canyon reflection adjustment applies to Tier-1 outputs only (Tier-2 models reflections properly).

### 6.8 Scenario-Speed Ladder & GNN Surrogate (closes G11)

1. **Now**: warm-starts + genome caching (§6.5) + incremental recompute (only affected component's centrality re-run — exact for closures/flips given localized change bounds).
2. **Later (Phase 2 of AI)**: train a GNN surrogate (scenario graph → equilibrium link flows) on scenario/assignment pairs the platform itself mass-produces; use as instant preview in the sandbox and GA pre-filter, with true assignment re-run on shortlists. Library: **Torch Spatiotemporal (tsl)** or PyG; this is an active 2025–26 research direction (GNN metamodels for UE), feasible precisely because SmartStreet generates its own training data. Defer until the pipeline runs end-to-end.

---

## 7. New Analytics Models & Indices

Each entry: what it adds → where it lands in the network-first schema. License flags matter (§11): **pandana, cityseer, UrbanAccess are AGPL** — keep behind a thin interface or reimplement math if SaaS plans firm up.

### 7.1 Urban Morphology & Streetscape — momepy (BSD-3, low effort)

GeoPandas/NetworkX-native. Three immediate wins: (a) **`street_profile`** — street width, width deviation, openness and **flanking building heights** → gives both walkability enclosure inputs *and* the H/W ratio that seeds Plane C (§4.4); (b) COINS **continuity strokes** → natural street "axes" for presenting results along whole streets rather than fragmented OSM segments (big UX win: name-level aggregation); (c) the 2025–26 **`streetscape` module** — pedestrian-view morphometrics (façade continuity, setbacks). Lands as `street_analytics.street_width/enclosure/facade_continuity/stroke_id`.

### 7.2 Accessibility Engine — pandana (AGPL; or reimplement)

Contraction-hierarchy aggregations: nearest-N-POI and decay-weighted sums for 10⁵ origins in seconds — the *engine* for §4.3's attraction kernels at scale (Hansen, 15-min counts, Walk-Score-like). Feed it the Plane-A graph + anchored entities. AGPL: isolate behind `AccessibilityEngine` interface; swap candidates: cityseer (also AGPL), NetworKit betweenness+custom, or own CH implementation later.

### 7.3 Pedestrian-Scale Centrality & Mixed Use — cityseer (AGPL, medium)

Rust-accelerated segment-based centrality including **simplest-path (angular) closeness/betweenness** — i.e., the machinery for the planned Space Syntax ASA, plus **NAIN/NACH normalization** (Hillier): `NACH = log(CH+1)/log(TD+3)` making angular results comparable across cities. Also distance-decayed land-use accessibility and Hill-number diversity (a more robust mixed-use measure than Shannon entropy — use it for Frank's LUM term). Lands as `edge_nain`, `edge_nach`, `edge_mixed_use`. If AGPL is unacceptable, compute plain ASA in NetworkX (angular-weighted dual graph) + apply NAIN/NACH formulas — slower but license-clean.

### 7.4 Cycling: BNA Low-Stress Connectivity (methodology adoption)

PeopleForBikes BNA on top of the planned LTS: binarize LTS 1–2 = low-stress; score = share of anchored destinations reachable using *only* the low-stress subgraph vs. the full network, per origin. Exposes the "islands" problem single-edge LTS labels hide. Open reference: brokenspoke-analyzer (adopt scoring logic, not their pipeline). Lands as `cycling_analytics.low_stress_reach_pct` + hex `bna_score`; the BNA public map is the UX template for presenting a 0–100 network score.

### 7.5 Safety: proxy ladder (data-dependent)

1. **Now (no crash data)**: risk-factor proxy per edge — speed × volume × VRU exposure (anchored school/shop density) × missing-infrastructure flags (no sidewalk, unlit, no crossing within X m — VLM audits §5.7 fill these) → `safety_proxy`. Present as "risk factors", never "predicted crashes".
2. **Where users upload crash points**: Vision-Zero **High-Injury Network** — sliding-window severity-weighted density; top ~5% of mileage flagged `edge_hin` (SF/Boston methodology, low effort, high impact overlay).
3. **Later**: HSM-style Safety Performance Functions (needs AADT + multi-year geocoded crashes) and iRAP-lite star-rating proxy from OSM/audit attributes (iRAP v3.10 methodology public; full coefficients gated — hence "lite").

### 7.6 Equity of Access (new dimension, trivial math)

Gini/Theil + Lorenz curves over the *population-weighted distribution* of accessibility (jobs/services reachable) using per-hex population (§8.2) — "not just how good is average access, but how fairly is it distributed", the Pereira/Karner transport-justice framing. PySAL `inequality` (BSD). Lands as region-level scalars + hex deviation layer + a StreetIQ-adjacent "Equity" card and report section. Rare in commercial tools; municipalities increasingly must report it.

### 7.7 Green & Heat (environment tier completion)

Per-hex **NDVI** (Sentinel-2 L2A, 10 m) and **land-surface-temperature anomaly** (Landsat 8/9 ST, ~100 m) via Microsoft Planetary Computer STAC (`pystac-client` + `odc-stac`, free) — batch zonal stats, quarterly refresh. Street-level Green View Index later from Mapillary segmentation or VLM audit greenery scores (§5.7). Lands as `grid_cell_metrics.ndvi/lst_anomaly` + IDW to edges as ambient fields (§4.5) → comfort inputs to walkability and a heat-equity overlay.

### 7.8 Transit LOS + StreetIQ Formalization

- **Transit LOS**: TCQSM-style headway bands (A: <10 min … F: >60) per stop and corridor from GTFS (§8.3, gtfs_kit) + "frequent network" flag (≤15 min all day); edges inherit LOS within stop catchments via anchors. Powers the planned Route Overlap and frequency-tuning honestly.
- **StreetIQ spec (closes G18)**: per metric m with direction flag s_m∈{+1,−1}: robust-scale `z = clip((x − median)/(1.4826·MAD), −3, 3)`, then `u = (s_m·z + 3)/6` → [0,1]; StreetIQ = Σ w_m·u_m with weights normalized Σw=1; document each metric's direction; recompute scaling per region+time-slot; persist `(median, MAD)` per metric in `metric_scaling` so scores are stable across sessions and scenario diffs are meaningful. Weight profiles (user sliders / AI-elicited §5.9) stored per project.

### 7.9 Plane C Catalog (separate module, per §4.4)

Roadmapped analyses with their standard methods: H/W ratio (momepy street_profile), SVF (flanking-height estimator), CNOSSOS canyon reflection add-on, OSPM-style street-canyon concentration modifier, sidewalk insolation hours (shadow casting on extruded footprints — later). All nullable enrichments; own UI panel; own report section ("3D Street Environment").

---

## 8. New Data Sources

| Source | What / resolution | Access & license | Feeds (tier/table) |
|---|---|---|---|
| **Overture Maps** (2026-06 release, schema v1.17) | Places (confidence-scored POIs), buildings w/ heights, transportation w/ **GERS stable IDs** | GeoParquet on S3/Azure; DuckDB or `overturemaps` CLI; CDLA-P v2 (transport theme ODbL) | Plane B entities: `points_of_interest`, `building_footprints`; `edge_key`↔GERS cross-ref. ⚠ category schema migration Sept 2026 — build against `basic_category`. |
| **GHSL GHS-POP** (default) / WorldPop (LMIC) / Meta HRSL (30 m where available) | population rasters, 100 m | free download / API; CC BY 4.0 | `grid_cell_metrics.population_density` → demand (§6.2), Frank's density, equity (§7.6) |
| **Mobility Database** | 6,000+ GTFS/GTFS-RT feed catalog (TransitFeeds is dead) | REST API + CSV catalog | automated per-city GTFS fetch → `gtfs_*` tables (§9) → transit LOS, ROI, catchments |
| **Copernicus GLO-30 DEM** | 30 m global elevation (DSM caveat: includes buildings) | OpenTopography API / AWS COGs; free w/ attribution | `network_nodes.elevation`, `edges.grade` via `osmnx.elevation` (local raster batch — skip per-point APIs) |
| **OpenAQ v3** (+ **EEA Parquet download service** in EU) | station AQ observations, hourly | API key, 60/min; Parquet bulk; mostly CC BY | `aq_stations` (Plane B anchored sensors) → calibrate modeled emissions; live badge |
| **Open-Meteo** | historical weather (ERA5, 1940–) + CAMS gridded AQ (11 km EU) | keyless REST, CC BY, free tier | `weather_slots` → weather-impacted conditions (planned feature's actual data source); CAMS fills AQ where no stations |
| **Mapillary v4** | street imagery + detections + traffic signs | free token; CC BY-SA imagery | VLM audits (§5.7), sidewalk ground-truth, Green View; ⚠ Google Street View ToS prohibit this use |
| **OpenChargeMap** | EV charging POIs | free API key; CC BY 4.0 (per-record caveats) | Plane B entity category → electrification-readiness indicator |
| **Microsoft Planetary Computer** | Sentinel-2, Landsat ST | STAC API, free | §7.7 NDVI/LST |

Ingestion principle (extends the OSM cache design): every source gets a fetch-log table row (source, bbox, params, fetched_at, license, attribution) — the report engine then auto-generates a per-report "Data sources & licenses" appendix, which municipalities require and almost no tool provides.

---

## 9. Schema Changes (DDL)

Additions only — nothing in ARCHITECTURE.md's schema is removed. Grouped by concern.

### 9.1 Network-First Ontology (§4)

```sql
-- Plane A hardening
ALTER TABLE street_edges     ADD COLUMN edge_key VARCHAR(32);   -- deterministic hash, survives refetch
ALTER TABLE street_edges     ADD COLUMN gers_id VARCHAR(32);    -- Overture cross-ref (nullable)
ALTER TABLE street_edges     ADD COLUMN mode_mask INT DEFAULT 1; -- bitmask: 1 vehicle, 2 bike, 4 foot
ALTER TABLE street_edges     ADD COLUMN stroke_id INT;          -- momepy COINS continuity stroke

-- Plane B: anchoring (computed once at ingest, reused by every analytic)
CREATE TABLE entity_anchors (
    entity_type VARCHAR(20) NOT NULL,     -- 'poi','building','transit_stop','aq_station','charger','hex_pop'
    entity_id   BIGINT NOT NULL,
    region_id   INT REFERENCES regions(id) ON DELETE CASCADE,
    anchor_edge_id INT REFERENCES street_edges(id),
    anchor_offset  DOUBLE PRECISION,      -- 0..1 along edge (linear referencing)
    anchor_node_id BIGINT REFERENCES network_nodes(id),
    anchor_distance_m DOUBLE PRECISION,   -- centroid → projected point
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX idx_anchors_edge ON entity_anchors(anchor_edge_id);

-- Attraction kernel parameters (one place to tune all entity→network influence)
CREATE TABLE attraction_params (
    analytic VARCHAR(50) PRIMARY KEY,     -- 'hansen','15min','walkscore','transit_los',...
    kernel   VARCHAR(20) NOT NULL,        -- 'exp_decay','cumulative','quartic'
    beta     DOUBLE PRECISION,            -- for exp_decay
    max_dist_m DOUBLE PRECISION,          -- for cumulative/quartic
    category_weights JSONB DEFAULT '{}'   -- e.g. {"grocery": 3.0, "school": 2.0}
);

-- Plane C enrichment (all nullable; core analytics valid when NULL)
ALTER TABLE street_analytics ADD COLUMN canyon_hw DOUBLE PRECISION;
ALTER TABLE street_analytics ADD COLUMN svf DOUBLE PRECISION;
ALTER TABLE street_analytics ADD COLUMN noise_canyon_db_adj DOUBLE PRECISION;
ALTER TABLE street_analytics ADD COLUMN pm_trap_factor DOUBLE PRECISION;
```

### 9.2 Demand, Dynamics, Environment (§6)

```sql
CREATE TABLE demand_models (
    id SERIAL PRIMARY KEY,
    region_id INT REFERENCES regions(id) ON DELETE CASCADE,
    zone_resolution INT DEFAULT 8,                 -- H3 res used as TAZ
    trip_rates JSONB, beta_gravity DOUBLE PRECISION,
    calibration JSONB,                             -- counts used, achieved error
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE od_matrices (          -- sparse triplets per time slot
    demand_model_id INT REFERENCES demand_models(id) ON DELETE CASCADE,
    time_slot_id INT REFERENCES time_slots(id),
    origin_h3 VARCHAR(15), dest_h3 VARCHAR(15),
    trips DOUBLE PRECISION,
    PRIMARY KEY (demand_model_id, time_slot_id, origin_h3, dest_h3)
);
CREATE TABLE street_analytics_dynamic (   -- UXsim time-sliced outputs
    edge_id INT REFERENCES street_edges(id) ON DELETE CASCADE,
    scenario_id INT REFERENCES scenarios(id) ON DELETE CASCADE,
    t_start INT, t_end INT,                       -- seconds from slot start
    speed_kmh DOUBLE PRECISION, queue_veh DOUBLE PRECISION, flow_vph DOUBLE PRECISION,
    PRIMARY KEY (edge_id, scenario_id, t_start)
);
CREATE TABLE emission_factors (   -- EMEP/EEA Tier-3 coefficient ingest
    segment VARCHAR(50), euro_class VARCHAR(20), pollutant VARCHAR(10),
    coef JSONB,                                    -- rational-polynomial coefficients
    valid_kmh_min INT, valid_kmh_max INT,
    PRIMARY KEY (segment, euro_class, pollutant)
);
CREATE TABLE metric_scaling (     -- StreetIQ robust scaling persistence (§7.8)
    region_id INT, time_slot_id INT, metric VARCHAR(50),
    median DOUBLE PRECISION, mad DOUBLE PRECISION, direction INT,  -- +1/-1
    PRIMARY KEY (region_id, time_slot_id, metric)
);
-- GTFS (minimal analytical subset; raw feed kept on disk)
CREATE TABLE gtfs_feeds (id SERIAL PRIMARY KEY, region_id INT, source_url TEXT,
                         license TEXT, fetched_at TIMESTAMP);
CREATE TABLE gtfs_stop_metrics (
    stop_id VARCHAR(64), feed_id INT REFERENCES gtfs_feeds(id),
    transit_stop_id INT REFERENCES transit_stops(id),   -- matched to OSM stop
    headway_peak_min DOUBLE PRECISION, headway_offpeak_min DOUBLE PRECISION,
    los CHAR(1), frequent_network BOOLEAN,
    PRIMARY KEY (feed_id, stop_id)
);
```

### 9.3 AI Layer (§5)

```sql
CREATE TABLE users (              -- minimal; local-first single user is row 1
    id SERIAL PRIMARY KEY, email VARCHAR(255), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE ai_task_configs (    -- task → provider/model routing
    user_id INT REFERENCES users(id), task VARCHAR(20),
    provider VARCHAR(20), model VARCHAR(100), params JSONB,
    PRIMARY KEY (user_id, task)
);
CREATE TABLE ai_interactions (    -- provenance for every call (R5)
    id SERIAL PRIMARY KEY,
    user_id INT, project_id INT, task VARCHAR(20),
    provider VARCHAR(20), model VARCHAR(100),
    packet_hash VARCHAR(64), prompt_tokens INT, completion_tokens INT,
    cost_usd DOUBLE PRECISION, latency_ms INT,
    request JSONB, response JSONB,
    validation_status VARCHAR(20),        -- 'passed','repaired','abstained','failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE report_narratives (
    report_id INT REFERENCES reports(id) ON DELETE CASCADE,
    section VARCHAR(50), interaction_id INT REFERENCES ai_interactions(id),
    markdown TEXT, reviewed BOOLEAN DEFAULT FALSE,   -- human-approved before PDF
    PRIMARY KEY (report_id, section)
);
CREATE TABLE decision_debates (
    decision_id INT REFERENCES actionable_decisions(id) ON DELETE CASCADE,
    persona VARCHAR(30), position VARCHAR(12),
    concerns JSONB, affected_edge_ids JSONB,
    interaction_id INT REFERENCES ai_interactions(id),
    PRIMARY KEY (decision_id, persona)
);
CREATE TABLE street_audits (      -- VLM imagery audits (§5.7)
    id SERIAL PRIMARY KEY, edge_id INT REFERENCES street_edges(id),
    image_id VARCHAR(64), image_source VARCHAR(20) DEFAULT 'mapillary',
    prompt_version VARCHAR(10), scores JSONB,       -- {"sidewalk":4,"greenery":2,...}
    model VARCHAR(100), audited_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE documents (          -- RAG corpus, per-project (§5.8)
    id SERIAL PRIMARY KEY, project_id INT REFERENCES projects(id) ON DELETE CASCADE,
    title VARCHAR(255), filename VARCHAR(255), license_note TEXT,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE doc_chunks (
    id SERIAL PRIMARY KEY, document_id INT REFERENCES documents(id) ON DELETE CASCADE,
    page INT, heading TEXT, content TEXT
    -- + embedding: sqlite-vec virtual table now; pgvector `vector(1024)` after migration
);
CREATE TABLE ai_eval_cases (id SERIAL PRIMARY KEY, kind VARCHAR(30), question TEXT,
                            expected JSONB, region_id INT);
CREATE TABLE ai_eval_runs (id SERIAL PRIMARY KEY, run_at TIMESTAMP, provider VARCHAR(20),
                           model VARCHAR(100), passed INT, failed INT, details JSONB);
```

Note: **no `api_keys` table in v1** — session-only by design (§5.2). Also extend `computation_log` with an `error TEXT` column (currently failures have status but no diagnostics).

---

## 10. Revised Roadmap

Original Phases 1–5 stand; changes are **inserts** (marked ●) and one new phase. AI is deliberately staged *after* the analytics it narrates, except the gateway which lands early to de-risk.

**Phase 1 — Foundation & Digital Twin** (as planned, plus)
- ● Intersection consolidation + `edge_key` + `mode_mask` at ingest (§4.2).
- ● `entity_anchors` computation stage — anchor POIs/buildings/stops at fetch time (§4.3).
- ● Copernicus GLO-30 elevation → node elevation + edge grades (§8.4).
- ● Fetch-log + license tracking for every external source (§8).

**Phase 2 — Analytical Calculators** (as planned, plus)
- ● GHSL population → hex (§8.2). ● Gravity demand model + OD matrices (§6.2). ● AequilibraE assignment (§6.1) — *before* centrality-based "flow" claims.
- ● GTFS ingest (Mobility Database + gtfs_kit) → stop headways, transit LOS (§7.8, §8.3).
- ● momepy street_profile + strokes (§7.1); NAIN/NACH normalization on ASA (§7.3).
- ● StreetIQ robust-scaling spec + `metric_scaling` (§7.8).
- ● EMEP/EEA emission factors (§6.6); CNOSSOS-lite noise (§6.7 Tier 1).
- ● **AI Gateway + AI-1 narrative synthesis + golden-set harness v0** (§5.2, §5.3, §5.10) — narrative cards on the analytics that now exist.

**Phase 3 — Optimization Engine & AI** (as planned, plus)
- ● pymoo NSGA-II DNDP with repair + warm-started fitness (§6.5); MaxPressure baseline (§6.4); Green-Light-style cards.
- ● **AI-2 conversational analyst** (tool registry §5.4) + SSE chat panel. ● **AI-7 seeding/weights** (§5.9). ● **AI-4 persona debate** on decisions (§5.6).

**Phase 4 — Scenario Sandbox** (as planned, plus)
- ● UXsim dynamic lane + time-slider animation (§6.3). ● **AI-3 NL scenario generation** with validation cascade (§5.5) — lands here because it composes the sandbox primitives.

**Phase 5 — Output Pipeline & Polish** (as planned, plus)
- ● `report_narratives` with human-review checkbox before PDF (§5.3). ● Data-sources/licenses auto-appendix. ● **AI-6 RAG over uploaded plans** with citations (§5.8). ● Provenance browser UI (§5.13).

**Phase 6 — NEW: Enrichment & Interop**
- **AI-5 VLM street audits** (Mapillary) (§5.7). Plane C module: H/W, SVF, canyon noise/PM adjustments (§4.4, §7.9). NDVI/LST layers (§7.7). Equity metrics + report (§7.6). BNA low-stress connectivity (§7.4). Safety proxy ladder / HIN where data allows (§7.5). **MCP server** (§5.11). NoiseModelling sidecar (§6.7 Tier 2). GNN surrogate exploration (§6.8).

### First 90 days (strict order, each step unblocks the next)

1. **Wk 1–2**: Scaffold (FastAPI/React/SpatiaLite per plan) + OSMnx ingest with consolidation, `edge_key`, anchoring stage. *Exit: map shows network + anchored POIs with inspector showing anchors.*
2. **Wk 3–4**: GHSL population + GLO-30 grades + GTFS fetch for demo city. *Exit: hexes have population; edges have grade; stops have headways.*
3. **Wk 5–6**: Demand model (gravity+IPF) → AequilibraE UE validated on Sioux Falls then demo city. *Exit: `modeled_flow_volume`/`modeled_delay` populated; congestion map renders.*
4. **Wk 7–8**: Centrality, Frank's (with real density), LTS, isochrones, StreetIQ with robust scaling. *Exit: metric switcher + weight sliders live.*
5. **Wk 9–10**: EMEP/EEA emissions + CNOSSOS-lite noise. *Exit: environment layers + time-slot deltas.*
6. **Wk 11–12**: **AI Gateway (session BYOK, validation endpoint) + AI-1 narratives + golden set v0 (30 cases)**. *Exit: paste a key → AI card narrates the demo city with verified entity links; eval green.*
7. **Wk 13**: Demo-city report (Network Overview + Traffic Analysis PDFs with reviewed AI narrative). *Exit: shareable PDF — the artifact that sells the project.*

Demo city recommendation (open question Q3): a mid-size European city with strong OSM + GTFS + a published mobility plan PDF (exercises RAG later). Ljubljana fits all three and matches the existing UI mock.

---

## 11. Licensing & Legal Notes

| Item | Status | Action |
|---|---|---|
| pandana, cityseer, UrbanAccess | **AGPL-3.0** | Fine while SmartStreet is internal/open; if closed SaaS: isolate behind interfaces (§7.2) or reimplement. Decide before deep coupling. |
| NoiseModelling | GPL-3.0 (Java) | Docker sidecar via CLI/WPS = process isolation; don't link. |
| r5py | GPL **or MIT dual** | Choose MIT terms; needs JVM. |
| AequilibraE, UXsim, momepy, pymoo, gtfs_kit, osmnx, PySAL | permissive | Clean. |
| HBEFA database | paid license | Don't ingest; SUMO's built-in HBEFA-derived model is the licensed backdoor when SUMO is used. |
| COPERT software vs EMEP/EEA factors | software commercial; **factor tables free** | Use the XLSX coefficients with attribution. |
| OSM / Overture | ODbL / CDLA-P (transport theme ODbL) | Attribution + share-alike on derived *databases*; keep the auto-generated license appendix (§8). |
| Google Street View | ToS prohibits bulk/ML analysis | **Never** — Mapillary (CC BY-SA) or user-supplied imagery only. |
| NACTO/CROW manuals in RAG | copyrighted | Per-user uploaded licensed copies, per-project index, short excerpts with citations; no shared corpus (§5.8). |
| User API keys | user property | Session-only v1; envelope encryption if persisted; last4 display; log scrubbing (§5.13). |
| OSM tags in prompts | injection surface | Treat street names as untrusted data (§5.13). |

---

## 12. References

**LLM × urban/GIS**: TrafficGPT (Transport Policy 2024) · Open-TI (2024, github.com/DaRL-LibSignal/OpenTI) · SUMO-MCP (2025, arXiv:2506.03548) · ChatSUMO (IEEE TIV 2024) · LLM-Geo / Autonomous GIS (IJDE 2023, github.com/gladcolor/LLM-Geo) · GIS Copilot (IJDE 2025) · GeoGPT (JAG 2024) · ChatGeoAI (ISPRS IJGI 2024) · PlanGPT (2024) · UrbanGPT (KDD 2024, github.com/HKUDS/UrbanGPT) · CityGPT/CityEval (2024, arXiv:2406.13948) · UrbanLLM (EMNLP Findings 2024) · UrbanKGent (NeurIPS 2024) · LLM-empowered participatory planning (2024, arXiv:2402.01698) · DRL urban planning (Nature Comput. Sci. 2023, github.com/tsinghua-fib-lab/DRL-urban-planning) · EoH LLM-heuristics (ICML 2024, github.com/FeiLiu36/EoH) · Urban Institute zoning-RAG (2024) · "Urban planning in the era of LLMs" (Nat. Comput. Sci. 2025). Trackers: github.com/HKUDS/Awesome-LLM4Urban-Papers · github.com/usail-hkust/Awesome-Urban-LLM-Agents.

**Benchmarks & pitfalls**: MapEval (ICML 2025, arXiv:2501.00316) · CityBench (KDD 2025) · UrbanPlanBench (arXiv:2504.21027) · Text-to-OverpassQL (TACL 2024) · GeoSQL-Eval (arXiv:2509.25264) · GPT4GEO (2023) · coordinate-bias studies (arXiv:2506.00203; GPSBench 2026) · geospatial hallucination (arXiv:2507.19586) · GeoBenchX (2025) · GeoAnalystBench (Trans. GIS 2025).

**Vision**: SAGAI (2025, github.com/perezjoan/SAGAI) · GPT-4o walkability alignment (PLOS ONE 2025) · pavement audit VLM (2026) · Tile2Net (CEUS 2023) · GeoChat (CVPR 2024).

**Traffic/OR**: AequilibraE (aequilibrae.com) · UXsim (JOSS 2025, github.com/toruseo/UXsim) · SUMO 1.27 (eclipse.dev/sumo) · Path4GMNS/DTALite/osm2gmns/grid2demand · PySAL spint · OMOD (CEUS 2023) · Webster (1958) · Varaiya MaxPressure (2013) · SUMO-RL · LibSignal · LeBlanc (Transp. Sci. 1975) · Wang, Meng & Yang (TR-B 2013) · GA-for-NDP line (Drezner & Wesolowsky; Miandoabchi & Farahani) · pymoo · EMEP/EEA Guidebook road transport ch. (2023, upd. 2025) · CNOSSOS-EU (Directive 2015/996) · NoiseModelling v6 (github.com/Universite-Gustave-Eiffel/NoiseModelling) · Torch Spatiotemporal (tsl) · GNN4Traffic tracker.

**Urban analytics**: momepy (incl. streetscape module, 2025) · cityseer (arXiv:2106.15314) · pandana · r5py · PySAL access (2SFCA/RAAM) & inequality · gtfs_kit · partridge · Hillier NAIN/NACH · Frank's walkability (2010) · Moreno 15-minute city (+2025 review) · PeopleForBikes BNA (brokenspoke-analyzer) · HSM SPFs · iRAP v3.10 · SF/Boston Vision Zero HIN methodology · TCQSM transit LOS · Pereira/Karner accessibility equity.

**Data**: Overture (docs.overturemaps.org, 2026-06 release) · GHSL · WorldPop · Meta HRSL · Mobility Database (mobilitydatabase.org) · Copernicus GLO-30 (OpenTopography) · OpenAQ v3 · EEA AQ download service · Open-Meteo · Mapillary v4 · OpenChargeMap · Microsoft Planetary Computer.

**AI engineering**: Pydantic AI V2 (ai.pydantic.dev) · LiteLLM · instructor · LangGraph 1.0 · MCP (Linux Foundation / Agentic AI Foundation, 2025) + FastMCP · pgvector / sqlite-vec · BGE-M3 · Langfuse v3 · pydantic-evals / deepeval / promptfoo · sse-starlette · sqlglot · provider prompt-caching docs (OpenAI/Anthropic/Google) · GitGuardian & envelope-encryption key-management guides.

---

*End of report. This document extends `ARCHITECTURE.md`; on conflict, this report's §4 (ontology) and §5 (AI) take precedence as the newer decision record.*



