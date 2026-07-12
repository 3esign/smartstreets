"""Tier-2 analytics for SmartStreet.

Street network centrality, modeled flow, congestion (BPR), emissions
(COPERT-style average-speed curves), noise (simplified CNOSSOS-EU source
model) and composite StreetIQ; pedestrian walkability (infrastructure +
destination accessibility); cycling Level-of-Traffic-Stress (Furth/Mekuria
criteria) and bikeability; per-edge data-quality completeness. Also exposes
a shared `build_street_graph` used by isochrones, optimization, scenarios
and the multi-year simulator.

Scientific references are listed in docs/METHODOLOGY.md.
"""

import math

import networkx as nx
import numpy as np

from . import database as db

DEFAULT_MAXSPEED = {
    "motorway": 100, "trunk": 80, "primary": 60, "secondary": 50,
    "tertiary": 50, "residential": 30, "living_street": 20, "service": 20,
    "unclassified": 40, "road": 40,
}
# Directional capacity in passenger-car units/hour (HCM-informed class values)
CAPACITY = {
    "motorway": 2000, "trunk": 1800, "primary": 1500, "secondary": 1200,
    "tertiary": 900, "residential": 600, "living_street": 300, "service": 300,
}
# Time-of-day demand multipliers applied to flow/emissions/noise
TIME_SLOTS = {
    "morning_rush": 1.35, "midday": 0.85, "evening_rush": 1.5, "night": 0.35,
}
DEFAULT_WEIGHTS = {"centrality": 0.35, "flow": 0.25, "emissions": 0.20, "noise": 0.20}

# ---- BPR volume-delay (Bureau of Public Roads 1964) ----------------------
BPR_ALPHA, BPR_BETA = 0.15, 4.0


def bpr_time(t0, voc, alpha=BPR_ALPHA, beta=BPR_BETA):
    """Congested travel time from free-flow time t0 and volume/capacity."""
    return t0 * (1.0 + alpha * (max(voc, 0.0) ** beta))


# ---- COPERT-style average-speed CO2 emission factors (g/km) --------------
# Petrol PC (COPERT/EMEP-EEA form):  231 - 3.62 v + 0.0263 v^2 + 2526/v
# Diesel PC:                          286 - 4.07 v + 0.0271 v^2
# Fleet blend defaults to 60 % petrol / 40 % diesel.
def co2_gpkm(speed_kmh, petrol_share=0.6):
    v = min(max(speed_kmh, 10.0), 130.0)
    petrol = 231.0 - 3.62 * v + 0.0263 * v * v + 2526.0 / v
    diesel = 286.0 - 4.07 * v + 0.0271 * v * v
    return petrol_share * petrol + (1.0 - petrol_share) * diesel


# ---- Simplified CNOSSOS-EU road noise source (EU Directive 2015/996) -----
# Broadband A-weighted coefficients, vehicle category 1 (light vehicles):
#   rolling    L_R = A_R + B_R log10(v/70)   with A_R = 79.7, B_R = 30.0
#   propulsion L_P = A_P + B_P (v-70)/70     with A_P = 94.5, B_P = -1.3
# Line source per metre: L_W' = L_W,veh + 10 log10(Q/(1000 v)),  Q veh/h.
# Receiver level reported at 10 m (geometric divergence of a line source).
CNOSSOS = {"A_R": 79.7, "B_R": 30.0, "A_P": 94.5, "B_P": -1.3, "V_REF": 70.0}


def noise_db_at_10m(flow_vph, speed_kmh):
    v = min(max(speed_kmh, 20.0), 130.0)
    q = max(flow_vph, 0.1)
    l_roll = CNOSSOS["A_R"] + CNOSSOS["B_R"] * math.log10(v / CNOSSOS["V_REF"])
    l_prop = CNOSSOS["A_P"] + CNOSSOS["B_P"] * (v - CNOSSOS["V_REF"]) / CNOSSOS["V_REF"]
    l_veh = 10.0 * math.log10(10 ** (l_roll / 10.0) + 10 ** (l_prop / 10.0))
    l_line = l_veh + 10.0 * math.log10(q / (1000.0 * v))          # per metre
    l_recv = l_line - 10.0 * math.log10(2.0 * math.pi * 10.0)     # at 10 m
    return max(30.0, min(90.0, l_recv))


def _hwbase(hw):
    return (hw or "").split("_")[0]


def _speed(row):
    return row["maxspeed"] or DEFAULT_MAXSPEED.get(_hwbase(row["highway"]), 40)


def _norm(vals):
    arr = np.array(vals, dtype=float)
    if arr.size == 0:
        return arr
    lo, hi = np.percentile(arr, 5), np.percentile(arr, 95)
    if hi - lo < 1e-9:
        return np.zeros_like(arr)
    return np.clip((arr - lo) / (hi - lo), 0, 1)


# --------------------------------------------------------------------------
# Shared graph builder (reused by isochrones / optimization / scenarios)
# --------------------------------------------------------------------------
def build_street_graph(region_id, overrides=None):
    """Return (DiGraph, nodes{ id:(lon,lat) }, edges[list of dict]).

    overrides: {edge_id: {"action": "closure"|"direction_change"|"attribute_change",
                          "maxspeed": int, "oneway": 0/1}} applied on top.
    """
    overrides = overrides or {}
    with db.cursor() as cur:
        cur.execute(
            "SELECT id,osm_id,source_node,target_node,highway,name,lanes,oneway,"
            "maxspeed,surface,width,length FROM street_edges WHERE region_id=?",
            (region_id,))
        edges = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT id,lon,lat FROM network_nodes WHERE region_id=?", (region_id,))
        nodes = {r["id"]: (r["lon"], r["lat"]) for r in cur.fetchall()}

    G = nx.DiGraph()
    for nid, (lon, lat) in nodes.items():
        G.add_node(nid, lon=lon, lat=lat)

    for e in edges:
        s, t = e["source_node"], e["target_node"]
        if s is None or t is None:
            continue
        ov = overrides.get(e["id"], {})
        if ov.get("action") == "closure":
            e["_closed"] = True
            continue
        oneway = e["oneway"]
        maxspeed = e["maxspeed"]
        if ov.get("action") == "direction_change":
            oneway = 1 if not oneway else oneway
            if ov.get("oneway") is not None:
                oneway = ov["oneway"]
        if ov.get("action") == "attribute_change":
            if ov.get("maxspeed") is not None:
                maxspeed = ov["maxspeed"]
            if ov.get("oneway") is not None:
                oneway = ov["oneway"]
        length = e["length"] or 1.0
        speed = maxspeed or DEFAULT_MAXSPEED.get(_hwbase(e["highway"]), 40)
        tt = length / max(speed * 1000 / 3600, 1.0)
        G.add_edge(s, t, edge_id=e["id"], weight=tt, length=length)
        if not oneway:
            G.add_edge(t, s, edge_id=e["id"], weight=tt, length=length)
    return G, nodes, edges


# --------------------------------------------------------------------------
# Street analytics + StreetIQ + data quality
# --------------------------------------------------------------------------
def compute(region_id, weights=None):
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    G, nodes, edges = build_street_graph(region_id)
    edges = [e for e in edges if not e.get("_closed")]
    if not edges:
        return {"edges": 0}

    n = G.number_of_nodes()
    node_bt, node_cl = {}, {}
    if n > 2:
        k = min(n, 300)
        node_bt = nx.betweenness_centrality(G, k=k, weight="weight", seed=42)
        sample = list(G.nodes())[:: max(1, n // 400)]
        for src in sample:
            lengths = nx.single_source_dijkstra_path_length(G, src, weight="weight")
            tot = sum(lengths.values())
            if len(lengths) > 1 and tot > 0:
                node_cl[src] = (len(lengths) - 1) / tot

    # Betweenness -> flow proxy. Scale so the busiest edges approach their
    # class capacity in the peak hour (betweenness-flow correlation; see
    # METHODOLOGY.md). Then apply BPR congestion feedback once.
    raw_bt = {}
    for e in edges:
        s, t = e["source_node"], e["target_node"]
        raw_bt[e["id"]] = (node_bt.get(s, 0.0) + node_bt.get(t, 0.0)) / 2
    bt_max = max(raw_bt.values()) if raw_bt else 1.0

    results = []
    for e in edges:
        s, t = e["source_node"], e["target_node"]
        bt = raw_bt[e["id"]]
        cl = (node_cl.get(s, 0.0) + node_cl.get(t, 0.0)) / 2
        vff = _speed(e)                                   # free-flow km/h
        cap = CAPACITY.get(_hwbase(e["highway"]), 500)
        # peak-hour demand estimate: relative betweenness x 0.85 capacity
        flow = (bt / bt_max if bt_max > 0 else 0.0) * cap * 0.85
        voc = flow / max(cap, 1.0)
        t0 = (e["length"] or 1.0) / max(vff * 1000 / 3600, 1.0)   # s
        tc = bpr_time(t0, voc)
        v_cong = max(5.0, vff * t0 / tc)                  # congested speed km/h
        # CO2 (kg/h on this edge): EF(v) g/km x length km x flow veh/h
        co2 = co2_gpkm(v_cong) * (e["length"] or 0) / 1000.0 * flow / 1000.0
        noise = noise_db_at_10m(flow, v_cong)
        # data quality completeness (5 key tags)
        present = sum(1 for f in ("maxspeed", "lanes", "surface", "width", "name") if e.get(f))
        completeness = present / 5.0
        results.append({"edge_id": e["id"], "bt": bt, "cl": cl, "flow": flow,
                        "voc": voc, "v_cong": v_cong,
                        "co2": co2, "noise": noise, "completeness": completeness})

    nbt = _norm([r["bt"] for r in results])
    nflow = _norm([r["flow"] for r in results])
    nco2 = _norm([r["co2"] for r in results])
    nnoise = _norm([r["noise"] for r in results])
    wsum = sum(weights[k] for k in DEFAULT_WEIGHTS) or 1.0
    iq = (weights["centrality"] * nbt + weights["flow"] * nflow
          + weights["emissions"] * nco2 + weights["noise"] * nnoise) / wsum

    with db.cursor() as cur:
        cur.execute("DELETE FROM street_analytics WHERE edge_id IN "
                    "(SELECT id FROM street_edges WHERE region_id=?)", (region_id,))
        cur.executemany(
            "INSERT OR REPLACE INTO street_analytics"
            "(edge_id,betweenness,closeness,modeled_flow,co2_emissions,noise_db,"
            "street_iq,completeness,voc,congested_speed) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(r["edge_id"], r["bt"], r["cl"], r["flow"], r["co2"], r["noise"],
              float(iq[i]), r["completeness"], r["voc"], r["v_cong"])
             for i, r in enumerate(results)],
        )
    return {
        "edges": len(results),
        "avg_betweenness": float(np.mean([r["bt"] for r in results])),
        "avg_co2": float(np.mean([r["co2"] for r in results])),
        "avg_noise": float(np.mean([r["noise"] for r in results])),
        "avg_voc": float(np.mean([r["voc"] for r in results])),
        "avg_street_iq": float(np.mean(iq)),
        "avg_completeness": float(np.mean([r["completeness"] for r in results])),
    }


# --------------------------------------------------------------------------
# Pedestrian walkability
# --------------------------------------------------------------------------
def _grid_index(points, cell_deg):
    """Build {(gx,gy): [i,...]} spatial hash for fast radius counting."""
    idx = {}
    for i, (lon, lat) in enumerate(points):
        key = (int(lon / cell_deg), int(lat / cell_deg))
        idx.setdefault(key, []).append(i)
    return idx


def _count_within(idx, points, lon, lat, cell_deg, radius_deg):
    n, gx, gy = 0, int(lon / cell_deg), int(lat / cell_deg)
    r2 = radius_deg * radius_deg
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for i in idx.get((gx + dx, gy + dy), ()):
                plon, plat = points[i]
                if (plon - lon) ** 2 + (plat - lat) ** 2 <= r2:
                    n += 1
    return n


def compute_pedestrian(region_id):
    """Walkability per edge.

    Components follow the walkability / built-environment literature
    (Ewing & Cervero 2010 "5 Ds"; Frank et al. 2010):
      0.35 infrastructure quality (type, surface),
      0.20 personal safety proxy (lighting, steps),
      0.25 destination accessibility (POIs within 250 m),
      0.20 network connectivity (intersections within 250 m).
    """
    with db.cursor() as cur:
        cur.execute("SELECT id,type,surface,lit,geom FROM pedestrian_edges WHERE region_id=?",
                    (region_id,))
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT lon,lat FROM points_of_interest WHERE region_id=? "
                    "AND lon IS NOT NULL", (region_id,))
        pois = [(r["lon"], r["lat"]) for r in cur.fetchall()]
        cur.execute("SELECT lon,lat FROM network_nodes WHERE region_id=? AND degree>=2",
                    (region_id,))
        xnodes = [(r["lon"], r["lat"]) for r in cur.fetchall()]
    if not rows:
        return {"edges": 0}

    # 250 m radius in degrees at region latitude
    lat0 = (xnodes or pois or [(0, 45)])[0][1]
    rad = 250.0 / (111320.0 * max(math.cos(math.radians(lat0)), 0.2))
    cell = rad
    poi_idx = _grid_index(pois, cell)
    node_idx = _grid_index(xnodes, cell)

    good_surface = {"paved", "asphalt", "concrete", "paving_stones"}
    out = []
    for r in rows:
        coords = db.unj(r["geom"], [])
        mid = coords[len(coords) // 2] if coords else [0, 0]
        base = {"footway": 0.75, "pedestrian": 0.9, "path": 0.55,
                "steps": 0.4, "track": 0.45, "corridor": 0.6}.get(r["type"], 0.6)
        surf = 1.0 if (r["surface"] in good_surface) else (0.7 if r["surface"] else 0.6)
        infra = 0.6 * base + 0.4 * surf
        safety = 0.5 + (0.4 if r["lit"] else 0.0) + (0.1 if r["type"] != "steps" else -0.2)
        safety = max(0.0, min(1.0, safety))
        n_poi = _count_within(poi_idx, pois, mid[0], mid[1], cell, rad)
        dest = min(1.0, math.log1p(n_poi) / math.log1p(15))     # saturates ~15 POIs
        n_x = _count_within(node_idx, xnodes, mid[0], mid[1], cell, rad)
        conn = min(1.0, math.log1p(n_x) / math.log1p(40))       # saturates ~40 nodes
        walk = max(0.0, min(1.0, 0.35 * infra + 0.20 * safety + 0.25 * dest + 0.20 * conn))
        out.append((r["id"], walk, safety, conn))
    with db.cursor() as cur:
        cur.execute("DELETE FROM pedestrian_analytics WHERE edge_id IN "
                    "(SELECT id FROM pedestrian_edges WHERE region_id=?)", (region_id,))
        cur.executemany("INSERT OR REPLACE INTO pedestrian_analytics"
                        "(edge_id,walkability,safety,connectivity) VALUES(?,?,?,?)", out)
    return {"edges": len(out), "avg_walkability": float(np.mean([o[1] for o in out]))}


# --------------------------------------------------------------------------
# Cycling Level of Traffic Stress + bikeability
# --------------------------------------------------------------------------
def _lts(cyc_type, maxspeed, lanes):
    """Level of Traffic Stress after Mekuria, Furth & Nixon (2012), MTI 11-19.

    Simplified km/h adaptation of the LTS criteria tables:
      - physically separated infrastructure         -> LTS 1
      - bike lane, <=30 km/h                        -> LTS 1
      - bike lane, <=50 km/h and <=2 lanes          -> LTS 2
      - bike lane, <=50 km/h and >2 lanes, or 60    -> LTS 3
      - bike lane, >60 km/h                         -> LTS 4
      - mixed traffic, <=30 km/h                    -> LTS 2
      - mixed traffic, <=50 km/h and <=2 lanes      -> LTS 3
      - mixed traffic otherwise                     -> LTS 4
    """
    if cyc_type in ("cycle_track", "bike_path"):
        return 1
    ms = maxspeed or 50
    ln = lanes or 2
    if cyc_type == "cycle_lane":
        if ms <= 30:
            return 1
        if ms <= 50 and ln <= 2:
            return 2
        if ms <= 60:
            return 3
        return 4
    # shared road / mixed traffic
    if ms <= 30:
        return 2
    if ms <= 50 and ln <= 2:
        return 3
    return 4


def compute_cycling(region_id):
    # join street attributes through shared OSM way id (cycle lanes are
    # tagged on the same way as the carriageway they run along)
    with db.cursor() as cur:
        cur.execute(
            "SELECT c.id,c.type,c.surface,s.maxspeed,s.lanes,s.highway "
            "FROM cycling_edges c LEFT JOIN street_edges s "
            "ON s.osm_id=c.osm_id AND s.region_id=c.region_id "
            "WHERE c.region_id=?", (region_id,))
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {"edges": 0}
    good_surface = {"paved", "asphalt", "concrete", "paving_stones", "smooth"}
    out, seen = [], set()
    for r in rows:
        if r["id"] in seen:        # LEFT JOIN can duplicate on split ways
            continue
        seen.add(r["id"])
        ms = r["maxspeed"] or DEFAULT_MAXSPEED.get(_hwbase(r["highway"]), None)
        lts = _lts(r["type"], ms, r["lanes"])
        surf = 1.0 if (r["surface"] in good_surface) else (0.7 if r["surface"] else 0.6)
        bike = max(0.0, min(1.0, (5 - lts) / 4 * 0.7 + surf * 0.3))
        out.append((r["id"], lts, bike))
    with db.cursor() as cur:
        cur.execute("DELETE FROM cycling_analytics WHERE edge_id IN "
                    "(SELECT id FROM cycling_edges WHERE region_id=?)", (region_id,))
        cur.executemany("INSERT OR REPLACE INTO cycling_analytics"
                        "(edge_id,lts,bikeability) VALUES(?,?,?)", out)
    return {"edges": len(out), "avg_bikeability": float(np.mean([o[2] for o in out]))}


def compute_all(region_id, weights=None):
    return {
        "street": compute(region_id, weights),
        "pedestrian": compute_pedestrian(region_id),
        "cycling": compute_cycling(region_id),
    }
