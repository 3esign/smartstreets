"""Tier-2 analytics for SmartStreet.

Street network centrality, modeled flow, emissions, noise and composite
StreetIQ; pedestrian walkability; cycling Level-of-Traffic-Stress and
bikeability; per-edge data-quality completeness. Also exposes a shared
`build_street_graph` used by isochrones, optimization and scenarios.
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
CAPACITY = {
    "motorway": 2000, "trunk": 1800, "primary": 1500, "secondary": 1200,
    "tertiary": 900, "residential": 600, "living_street": 300, "service": 300,
}
# Time-of-day demand multipliers applied to flow/emissions/noise
TIME_SLOTS = {
    "morning_rush": 1.35, "midday": 0.85, "evening_rush": 1.5, "night": 0.35,
}
DEFAULT_WEIGHTS = {"centrality": 0.35, "flow": 0.25, "emissions": 0.20, "noise": 0.20}


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

    results = []
    for e in edges:
        s, t = e["source_node"], e["target_node"]
        bt = (node_bt.get(s, 0.0) + node_bt.get(t, 0.0)) / 2
        cl = (node_cl.get(s, 0.0) + node_cl.get(t, 0.0)) / 2
        speed = _speed(e)
        cap = CAPACITY.get(_hwbase(e["highway"]), 500)
        flow = bt * cap
        co2_gpkm = 180 + 0.0035 * (speed - 70) ** 2
        co2 = co2_gpkm * (e["length"] or 0) / 1000.0 * (1 + flow / 1000.0)
        noise = 42 + 10 * math.log10(1 + flow) + 0.15 * speed
        # data quality completeness (5 key tags)
        present = sum(1 for f in ("maxspeed", "lanes", "surface", "width", "name") if e.get(f))
        completeness = present / 5.0
        results.append({"edge_id": e["id"], "bt": bt, "cl": cl, "flow": flow,
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
            "(edge_id,betweenness,closeness,modeled_flow,co2_emissions,noise_db,street_iq,completeness) "
            "VALUES(?,?,?,?,?,?,?,?)",
            [(r["edge_id"], r["bt"], r["cl"], r["flow"], r["co2"], r["noise"],
              float(iq[i]), r["completeness"]) for i, r in enumerate(results)],
        )
    return {
        "edges": len(results),
        "avg_betweenness": float(np.mean([r["bt"] for r in results])),
        "avg_co2": float(np.mean([r["co2"] for r in results])),
        "avg_noise": float(np.mean([r["noise"] for r in results])),
        "avg_street_iq": float(np.mean(iq)),
        "avg_completeness": float(np.mean([r["completeness"] for r in results])),
    }


# --------------------------------------------------------------------------
# Pedestrian walkability
# --------------------------------------------------------------------------
def compute_pedestrian(region_id):
    with db.cursor() as cur:
        cur.execute("SELECT id,type,surface,lit,geom FROM pedestrian_edges WHERE region_id=?",
                    (region_id,))
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {"edges": 0}
    good_surface = {"paved", "asphalt", "concrete", "paving_stones"}
    out = []
    for r in rows:
        base = {"footway": 0.75, "pedestrian": 0.9, "path": 0.55,
                "steps": 0.4, "track": 0.45, "corridor": 0.6}.get(r["type"], 0.6)
        surf = 1.0 if (r["surface"] in good_surface) else (0.7 if r["surface"] else 0.6)
        safety = 0.5 + (0.4 if r["lit"] else 0.0) + (0.1 if r["type"] != "steps" else -0.2)
        safety = max(0.0, min(1.0, safety))
        walk = max(0.0, min(1.0, 0.6 * base + 0.25 * surf + 0.15 * safety))
        out.append((r["id"], walk, safety, base))
    with db.cursor() as cur:
        cur.execute("DELETE FROM pedestrian_analytics WHERE edge_id IN "
                    "(SELECT id FROM pedestrian_edges WHERE region_id=?)", (region_id,))
        cur.executemany("INSERT OR REPLACE INTO pedestrian_analytics"
                        "(edge_id,walkability,safety,connectivity) VALUES(?,?,?,?)", out)
    return {"edges": len(out), "avg_walkability": float(np.mean([o[1] for o in out]))}


# --------------------------------------------------------------------------
# Cycling Level of Traffic Stress + bikeability
# --------------------------------------------------------------------------
def compute_cycling(region_id):
    with db.cursor() as cur:
        cur.execute("SELECT id,type,surface FROM cycling_edges WHERE region_id=?", (region_id,))
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return {"edges": 0}
    lts_by_type = {"cycle_track": 1, "bike_path": 1, "cycle_lane": 2, "shared_road": 3}
    good_surface = {"paved", "asphalt", "concrete", "paving_stones", "smooth"}
    out = []
    for r in rows:
        lts = lts_by_type.get(r["type"], 3)
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
