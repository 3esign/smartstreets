"""Tier-3 scenario sandbox: sequenced overrides, undo/redo, comparison."""

import math
import random

import networkx as nx

from . import analytics, database as db

DEFAULT_MS = analytics.DEFAULT_MAXSPEED


def create(project_id, region_id, name):
    with db.cursor() as cur:
        cur.execute("INSERT INTO scenarios(project_id,region_id,name) VALUES(?,?,?)",
                    (project_id, region_id, name))
        return cur.lastrowid


def list_scenarios(project_id):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM scenarios WHERE project_id=? ORDER BY id", (project_id,))
        scs = [dict(r) for r in cur.fetchall()]
    for s in scs:
        s["overrides"] = list_overrides(s["id"])
    return scs


def add_override(scenario_id, target_id, action_type, attribute_overrides=None):
    with db.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(sequence_number),0)+1 n FROM scenario_overrides "
                    "WHERE scenario_id=?", (scenario_id,))
        seq = cur.fetchone()["n"]
        # any redo-able (inactive) overrides are discarded when a new edit is made
        cur.execute("DELETE FROM scenario_overrides WHERE scenario_id=? AND active=0",
                    (scenario_id,))
        cur.execute("INSERT INTO scenario_overrides"
                    "(scenario_id,sequence_number,target_id,action_type,attribute_overrides,active) "
                    "VALUES(?,?,?,?,?,1)",
                    (scenario_id, seq, target_id, action_type, db.j(attribute_overrides or {})))
        return cur.lastrowid


def list_overrides(scenario_id, active_only=False):
    with db.cursor() as cur:
        q = "SELECT * FROM scenario_overrides WHERE scenario_id=?"
        if active_only:
            q += " AND active=1"
        cur.execute(q + " ORDER BY sequence_number", (scenario_id,))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["attribute_overrides"] = db.unj(r["attribute_overrides"], {})
    return rows


def undo(scenario_id):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM scenario_overrides WHERE scenario_id=? AND active=1 "
                    "ORDER BY sequence_number DESC LIMIT 1", (scenario_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE scenario_overrides SET active=0 WHERE id=?", (row["id"],))
    return list_overrides(scenario_id)


def redo(scenario_id):
    with db.cursor() as cur:
        cur.execute("SELECT id FROM scenario_overrides WHERE scenario_id=? AND active=0 "
                    "ORDER BY sequence_number ASC LIMIT 1", (scenario_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE scenario_overrides SET active=1 WHERE id=?", (row["id"],))
    return list_overrides(scenario_id)


def _overrides_dict(scenario_id):
    out = {}
    for o in list_overrides(scenario_id, active_only=True):
        attrs = o["attribute_overrides"] or {}
        out[o["target_id"]] = {"action": o["action_type"], **attrs}
    return out


def _metrics(region_id, overrides):
    """Region-level aggregate metrics for a given override set."""
    G, nodes, edges = analytics.build_street_graph(region_id, overrides)
    live = [e for e in edges if not e.get("_closed")]
    node_list = list(G.nodes())
    if len(node_list) < 4:
        return {"total_travel_time": 0, "total_co2": 0, "oneway_pct": 0, "reachability": 0}
    random.seed(21)
    od = [(random.choice(node_list), random.choice(node_list)) for _ in range(50)]
    tt, ok = 0.0, 0
    for s, t in od:
        try:
            tt += nx.shortest_path_length(G, s, t, weight="weight")
            ok += 1
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            tt += 3600
    reach = ok / len(od)
    # total CO2 with override speeds
    total_co2, oneway = 0.0, 0
    for e in live:
        ov = overrides.get(e["id"], {})
        speed = ov.get("maxspeed") or e["maxspeed"] or DEFAULT_MS.get(
            (e["highway"] or "").split("_")[0], 40)
        co2_gpkm = 180 + 0.0035 * (speed - 70) ** 2
        total_co2 += co2_gpkm * (e["length"] or 0) / 1000.0
        is_ow = ov.get("oneway", e["oneway"])
        if ov.get("action") == "direction_change":
            is_ow = ov.get("oneway", 1)
        if is_ow:
            oneway += 1
    return {
        "total_travel_time": round(tt, 1),
        "total_co2": round(total_co2, 1),
        "oneway_pct": round(100 * oneway / max(len(live), 1), 1),
        "reachability": round(reach, 3),
    }


def compare(scenario_id):
    with db.cursor() as cur:
        cur.execute("SELECT region_id FROM scenarios WHERE id=?", (scenario_id,))
        row = cur.fetchone()
    if not row:
        return None
    region_id = row["region_id"]
    base = _metrics(region_id, {})
    mod = _metrics(region_id, _overrides_dict(scenario_id))
    deltas = {}
    for k in base:
        b, m = base[k], mod[k]
        pct = ((m - b) / b * 100) if b else 0
        deltas[k] = {"baseline": b, "modified": m, "delta_pct": round(pct, 1)}
    return {"scenario_id": scenario_id, "metrics": deltas}


def delete(scenario_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
