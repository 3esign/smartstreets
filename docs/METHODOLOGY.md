# SmartStreet — Scientific Methodology (v2)

This document specifies every model implemented in SmartStreet, its equations,
parameter values, scientific sources, assumptions and known limitations. It
replaces the v1 ad-hoc formulations following a full methodological review.

Maintained by: Center for Applied Design Intelligence (CADI) · PhD Poturak Semir

---

## 1. Data model

Raw geometry, attributes and derived analytics are fetched live from
OpenStreetMap (Overpass API) for a user-drawn bounding box (≤ 50 km²,
progressive detail tiers A ≤ 5 km², B 5–15 km², C 15–50 km²) and stored in a
3-tier SQLite schema (raw → analytics → decisions). OSM completeness varies
by region; a per-edge **data-quality score** (share of the five key tags
`maxspeed, lanes, surface, width, name` present) is computed and surfaced so
users can judge reliability. Missing attributes are imputed from national
defaults per road class (e.g. residential → 30 km/h).

## 2. Network graph

Streets are represented as a directed graph G = (N, E): nodes are OSM way
endpoints, edges carry length, free-flow speed v₀, lane count and capacity.
Directional capacities (pcu/h) follow Highway Capacity Manual-informed class
values (motorway 2000 … living street 300; TRB, *Highway Capacity Manual*,
6th ed., 2016). Free-flow time t₀ = L / v₀.

### 2.1 Centrality

- **Betweenness centrality** (Freeman 1977) computed with Brandes' algorithm
  (Brandes 2001) on travel-time weights, sampled with k ≤ 300 pivots for
  tractability (Geisberger et al. 2008 justify pivot sampling).
- **Closeness centrality** on a systematic node sample.
Edge values are averaged from their endpoint nodes.

### 2.2 Flow proxy and congestion

Peak-hour link flow is estimated from relative betweenness — a standard proxy
when OD surveys are unavailable; betweenness correlates with observed traffic
volumes (Kazerani & Winter 2009; Puzis et al. 2013):

    q_e = (b_e / b_max) · 0.85 · C_e        [veh/h]

Congestion feedback uses the **BPR volume-delay function** (Bureau of Public
Roads, *Traffic Assignment Manual*, 1964):

    t = t₀ · (1 + α (q/C)^β),  α = 0.15, β = 4

yielding the volume/capacity ratio (v/c) and congested speed v_c published
per edge and mappable ("Congestion (v/c, BPR)").

## 3. Environmental models

### 3.1 CO₂ emissions — COPERT-style average-speed curves

Emission factors follow the average-speed methodology of COPERT / the
EMEP-EEA Air Pollutant Emission Inventory Guidebook (Ntziachristos & Samaras,
EMEP/EEA Guidebook 2019, Part B 1.A.3.b):

    EF_petrol(v) = 231 − 3.62 v + 0.0263 v² + 2526/v     [g/km], 10–130 km/h
    EF_diesel(v) = 286 − 4.07 v + 0.0271 v²              [g/km]
    EF_fleet(v)  = p·EF_petrol + (1−p)·EF_diesel,  default p = 0.6

Edge emission rate: E = EF(v_c) · L · q / 10⁶ [kg CO₂/h], where v_c is the
congested speed. Daily totals expand the peak hour by a factor 10 (peak ≈
10 % of daily traffic, a standard design-hour assumption).

### 3.2 Traffic noise — simplified CNOSSOS-EU

Source emission follows the EU common noise assessment framework
**CNOSSOS-EU** (Directive (EU) 2015/996; Kephalopoulos et al. 2012), category
1 (light vehicles), broadband A-weighted approximation:

    L_roll = 79.7 + 30.0·log₁₀(v/70)
    L_prop = 94.5 − 1.3·(v−70)/70
    L_veh  = 10·log₁₀(10^(L_roll/10) + 10^(L_prop/10))
    L_W′   = L_veh + 10·log₁₀(q / (1000·v))          [line source, per m]
    L(10m) = L_W′ − 10·log₁₀(2π·10)                  [geometric divergence]

Reported value is the receiver level at 10 m. Simplifications vs. full
CNOSSOS: octave bands collapsed to broadband; no façade reflections, air
absorption, ground effect or meteorological correction. Streets above 65 dB
are counted as "noisy km" (WHO *Environmental Noise Guidelines* 2018
recommends L_den < 53 dB for road traffic; 65 dB marks clearly harmful
exposure).

## 4. Active-travel models

### 4.1 Walkability

Edge walkability ∈ [0,1] combines four literature-grounded components
(weights in parentheses), following the built-environment "5 D" evidence
(Ewing & Cervero 2010) and GIS walkability indices (Frank et al. 2010):

- infrastructure quality (0.35): way type and surface;
- personal safety proxy (0.20): lighting, steps penalty;
- destination accessibility (0.25): log-saturating count of POIs within
  250 m (≈ 3-min walk);
- network connectivity (0.20): log-saturating count of intersections
  (degree ≥ 2 nodes) within 250 m.

### 4.2 Cycling Level of Traffic Stress

LTS 1–4 after **Mekuria, Furth & Nixon (2012)**, *Low-Stress Bicycling and
Network Connectivity*, MTI Report 11-19, adapted to km/h. Street speed and
lane attributes are joined to the cycling geometry via the shared OSM way id:

| infrastructure | condition | LTS |
|---|---|---|
| separated track/path | — | 1 |
| bike lane | ≤ 30 km/h | 1 |
| bike lane | ≤ 50 km/h, ≤ 2 lanes | 2 |
| bike lane | ≤ 60 km/h or > 2 lanes | 3 |
| bike lane | > 60 km/h | 4 |
| mixed traffic | ≤ 30 km/h | 2 |
| mixed traffic | ≤ 50 km/h, ≤ 2 lanes | 3 |
| mixed traffic | otherwise | 4 |

Bikeability = 0.7·(5−LTS)/4 + 0.3·surface quality.

## 5. Composite StreetIQ

StreetIQ ∈ [0,1] is a weighted, percentile-normalised composite of
betweenness, modeled flow, CO₂ and noise (default weights 0.35/0.25/0.20/
0.20, user-adjustable). It is a **burden/priority index**: high values mark
streets that carry the network and concentrate environmental externalities —
candidates for intervention. Normalisation clips at the 5th–95th percentile
to resist outliers. (Composite-indicator practice: OECD/JRC *Handbook on
Constructing Composite Indicators*, 2008.)

## 6. Isochrones

Reachability via single-source Dijkstra on the street graph (walk 1.34 m/s —
Bohannon 1997; cycle 4.5 m/s; drive uses congested edge speeds), bands 5/10/
15 min, polygonised by buffering reached nodes and unioning (a concave-hull
approximation). Isochrones can be **named, saved, reloaded and deleted**;
the overlay can be toggled without recomputation. This operationalises
Hansen-type contour accessibility (Hansen 1959; Geurs & van Wee 2004) and
15-minute-city analysis (Moreno et al. 2021).

## 7. Multi-year agent simulation

The simulator is a **mesoscopic land-use / transport interaction (LUTI)
loop** executed annually — the standard integrated-modelling structure
(Wegener 2004; Waddell 2002 UrbanSim; Ortúzar & Willumsen, *Modelling
Transport*, 4th ed. 2011). Each simulated year:

### 7.1 Demographics & land use
Exponential population growth at user rate g. Growth is allocated to zones
(≈ 350 m grid cells, ≤ 64 zones) by a logit on log-accessibility and
remaining floor-space capacity — a simplified residential location-choice
model (McFadden 1974; Waddell 2002). Initial population ≈ residential floor
area / 35 m² per capita.

### 7.2 Travel demand
- Generation: P_i = pop_i · trip rate (2.3 trips/person/day; cf. national
  travel surveys, e.g. NHTS 2017 ≈ 3.4 incl. all purposes; conservative
  urban peak subset) · peak share 0.10.
- Distribution: singly-constrained **gravity model** with negative
  exponential impedance f(t) = e^(−βt), β = 0.08 min⁻¹ (Wilson 1971 entropy
  derivation; calibrated to ~15 min mean trips).
- **Mode choice**: multinomial logit over car / transit / bike / walk with
  generalized-time utilities (θ = −0.055 min⁻¹) and alternative-specific
  constants evolved by policy levers (transit & bike investment, car
  ownership trend) (McFadden 1974; Train, *Discrete Choice Methods*, 2009).

### 7.3 Assignment
Car trips: iterative capacity-restrained assignment by the **Method of
Successive Averages** over all-or-nothing Dijkstra loadings with BPR link
costs — a convergent approximation of Wardrop (1952) user equilibrium
(Sheffi 1985). Shortest paths run on a SciPy sparse-graph kernel.

### 7.4 Network evolution
Demand-responsive rules reproduce the two empirically observed growth
processes of street networks — **densification and exploration** (Strano,
Barthélemy et al. 2012, *Sci. Rep.* 2:296; Barthélemy & Flammini 2008,
*Phys. Rev. Lett.* 100:138702) — under an annual budget (lane-km
equivalents):

1. **Capacity upgrades** on saturated links (v/c > 1), cost 0.7 units/lane-km;
2. **New links** where nodes are close in space (120–450 m) but far on the
   network (detour ratio > 2.5), prioritised by detour severity, cost 3
   units/km — the local optimisation of connection cost vs. benefit of
   Barthélemy & Flammini;
3. optional **pedestrianization** of calm (v/c < 0.25), short, POI-rich
   streets, following contemporary traffic-calming / superblock practice
   (Mueller et al. 2020, *Environ. Int.* 134).

### 7.5 Outputs per year
Population; peak trips; mode shares; VKT & VHT; mean speed; mean v/c;
congested km (v/c > 0.9); CO₂ t/day; noisy km (> 65 dB); Hansen
accessibility A_i = Σ_j O_j e^(−βt_ij) (Hansen 1959); mean trip time;
network km; cumulative new links / upgraded lane-km / pedestrianized km;
investment spent. Exportable as CSV/JSON.

### 7.6 Agent visualization
A sample (default 800) of individual trips is drawn from the OD × mode
distribution; departure times follow a bimodal AM/PM peak profile. Their
space-time trajectories (congested car speeds; walk 1.34, bike 4.2 m/s) are
animated on the map with a day clock — a visualization sample of the
mesoscopic solution in the spirit of MATSim's agent viewers (Horni, Nagel &
Axhausen 2016). Agents are illustrative of the flow pattern, not a
microsimulation of every resident.

## 8. Optimization suite

- **Signal placement**: ranks intersections by conflict exposure —
  betweenness × converging modeled flow (cf. intersection conflict-point
  analysis, FHWA Signalized Intersections Guide 2013).
- **Connectivity gaps**: detour ratio screening (network/Euclidean distance),
  a standard connectivity diagnostic (Dill 2004).
- **Direction solver**: greedy one-way reconfiguration evaluated against
  total travel time and CO₂.

All recommendations carry an impact score, confidence tier and a plain-text
rationale (explainability by design).

## 9. Assumptions & limitations

1. Flows are betweenness-based estimates (§2.2), not counts; treat absolute
   values as relative indicators. Calibration against local counts is the
   first recommended refinement.
2. Noise is a source+divergence approximation (§3.2) — no barriers,
   reflections or meteorology; suitable for screening, not legal mapping.
3. The simulator's zones, budgets and behavioural constants are defaults to
   be locally calibrated; results are **scenario explorations**, not
   forecasts (cf. "models as learning machines", Epstein 2008).
4. Transit is modelled as a generalized-time alternative (no timetables);
   regions without OSM transit stops disable the mode.
5. OSM completeness bounds all downstream accuracy — check the data-quality
   layer before interpreting results.

## 10. References

- Barthélemy M., Flammini A. (2008). Modeling urban street patterns. *PRL* 100:138702.
- Bohannon R. (1997). Comfortable and maximum walking speed of adults. *Age & Ageing* 26:15-19.
- Brandes U. (2001). A faster algorithm for betweenness centrality. *J. Math. Sociol.* 25:163-177.
- Bureau of Public Roads (1964). *Traffic Assignment Manual*. US DoC.
- Dill J. (2004). Measuring network connectivity for bicycling and walking. TRB 83rd Annual Meeting.
- Directive (EU) 2015/996 — common noise assessment methods (CNOSSOS-EU).
- Epstein J. (2008). Why model? *JASSS* 11(4):12.
- Ewing R., Cervero R. (2010). Travel and the built environment: a meta-analysis. *JAPA* 76:265-294.
- Frank L. et al. (2010). The development of a walkability index. *Br. J. Sports Med.* 44:924-933.
- Freeman L. (1977). A set of measures of centrality based on betweenness. *Sociometry* 40:35-41.
- Geurs K., van Wee B. (2004). Accessibility evaluation of land-use and transport strategies. *J. Transp. Geogr.* 12:127-140.
- Hansen W. (1959). How accessibility shapes land use. *JAIP* 25:73-76.
- Horni A., Nagel K., Axhausen K. (2016). *The Multi-Agent Transport Simulation MATSim*. Ubiquity Press.
- Kazerani A., Winter S. (2009). Can betweenness centrality explain traffic flow? AGILE.
- Kephalopoulos S. et al. (2012). *Common Noise Assessment Methods in Europe (CNOSSOS-EU)*. JRC Reference Report EUR 25379.
- McFadden D. (1974). Conditional logit analysis of qualitative choice behavior. In *Frontiers in Econometrics*.
- Mekuria M., Furth P., Nixon H. (2012). *Low-Stress Bicycling and Network Connectivity*. MTI Report 11-19.
- Moreno C. et al. (2021). Introducing the "15-minute city". *Smart Cities* 4:93-111.
- Mueller N. et al. (2020). Changing the urban design of cities for health: the superblock model. *Environ. Int.* 134:105132.
- Ntziachristos L., Samaras Z. (2019). EMEP/EEA Emission Inventory Guidebook — Road Transport (COPERT).
- OECD/JRC (2008). *Handbook on Constructing Composite Indicators*.
- Ortúzar J., Willumsen L. (2011). *Modelling Transport*, 4th ed. Wiley.
- Puzis R. et al. (2013). Augmented betweenness centrality for environmentally aware traffic monitoring. *IEEE T-ITS* 14:344-353.
- Sheffi Y. (1985). *Urban Transportation Networks*. Prentice-Hall.
- Strano E. et al. (2012). Elementary processes governing the evolution of road networks. *Sci. Rep.* 2:296.
- Train K. (2009). *Discrete Choice Methods with Simulation*, 2nd ed. Cambridge UP.
- TRB (2016). *Highway Capacity Manual*, 6th ed.
- Waddell P. (2002). UrbanSim: modeling urban development. *JAPA* 68:297-314.
- Wardrop J. (1952). Some theoretical aspects of road traffic research. *Proc. ICE* 1:325-362.
- Wegener M. (2004). Overview of land-use transport models. In *Handbook of Transport Geography and Spatial Systems*.
- WHO (2018). *Environmental Noise Guidelines for the European Region*.
- Wilson A. (1971). A family of spatial interaction models. *Environ. Plan. A* 3:1-32.
