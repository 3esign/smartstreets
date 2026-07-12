"""Tier-3 optimization: signal placement, connectivity gaps, direction solver.

Deterministic, network-first heuristics that read Tier-1/2 data and write
ranked recommendations to `actionable_decisions`.
"""

import math
import random

import networkx as nx

from . import analytics, database as db


def _confidence(score, hi, lo):
    if score >= hi:
        return "high"
    if score >= lo:
        return "medium"
    return "low"


def _clear(region_id, category):
    with db.cursor() as cur:
        cur.execute("DELETE FROM actionable_decisions WHERE region_id=? AND category=?",
                    (region_id, category))


def _store(region_id, category, rows):
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO actionable_decisions"
            "(region_id,category,geom,impact_score,confidence,rationale,props) "
            "VALUES(?,?,?,?,?,?,?)",
            [(region_id, category, db.j(r["geom"]), r["impact"], r["confidence"],
              r["rationale"], db.j(r.get("props", {}))) for r in rows])


# --------------------------------------------------------------------------
# Signal placement — Conflict Point Index x betweenness
# --------------------------------------------------------------------------
def signal_placement(region_id, top_n=12):
    G, nodes, edges = analytics.build_street_graph(region_id)
    if G.number_of_nodes() < 3:
        return []
    node_bt = nx.betweenness_centrality(G, k=min(G.number_of_nodes(), 300),
                                        weight="weight", seed=42)
    # flow per node from connecting edge modeled_flow
    with db.cursor() as cur:
        cur.execute("SELECT e.source_node s,e.target_node t,a.modeled_flow f "
                    "FROM street_edges e JOIN street_analytics a ON a.edge_id=e.id "
                    "WHERE e.region_id=?", (region_id,))
        flowrows = cur.fetchall()
    node_flow = {}
    for r in flowrows:
        for nd in (r["s"], r["t"]):
            node_flow[nd] = node_flow.get(nd, 0.0) + (r["f"] or 0.0)

    cand = []
    for nid in nodes:
        deg = G.degree(nid)  # in+out
        approaches = max(1, deg // 2)
        if approaches < 3:
            continue
        # conflict points grow ~quadratically with approaches
        conflicts = approaches * (approaches - 1)
        cpi = conflicts * (1 + node_flow.get(nid, 0) / 500.0)
        score = cpi * (0.5 + node_bt.get(nid, 0) * 50)
        cand.append((nid, score, approaches, cpi))
    if not cand:
        return []
    cand.sort(key=lambda x: -x[1])
    top = cand[:top_n]
    smax = top[0][1] or 1.0
    hi, lo = smax * 0.6, smax * 0.3
    rows = []
    for nid, score, approaches, cpi in top:
        lon, lat = nodes[nid]
        rows.append({
            "geom": {"type": "Point", "coordinates": [lon, lat]},
            "impact": round(score, 2), "confidence": _confidence(score, hi, lo),
            "rationale": f"{approaches}-way junction; conflict index {cpi:.1f}, high routing "
                         f"centrality. Candidate for signal control.",
            "props": {"node_id": nid, "approaches": approaches, "cpi": round(cpi, 1)},
        })
    _clear(region_id, "signalization")
    _store(region_id, "signalization", rows)
    return rows


# --------------------------------------------------------------------------
# Connectivity gap finder — spatial-near but network-far node pairs
# --------------------------------------------------------------------------
def _haversine(a, b):
    r = 6371000.0
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dla = math.radians(b[1] - a[1])
    dlo = math.radians(b[0] - a[0])
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def connectivity_gaps(region_id, top_n=10, max_gap_m=350):
    G, nodes, edges = analytics.build_street_graph(region_id)
    UG = G.to_undirected()
    node_ids = [n for n in nodes if G.degree(n) >= 1]
    random.seed(7)
    if len(node_ids) > 500:
        node_ids = random.sample(node_ids, 500)
    proposals = []
    seen = set()
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            euclid = _haversine(nodes[a], nodes[b])
            if euclid < 40 or euclid > max_gap_m:
                continue
            try:
                net = nx.shortest_path_length(UG, a, b, weight="length")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                net = float("inf")
            circuity = net / euclid if euclid > 0 else 0
            if circuity > 2.5:
                key = tuple(sorted((a, b)))
                if key in seen:
                    continue
                seen.add(key)
                proposals.append((a, b, euclid, circuity if circuity != float("inf") else 99))
    proposals.sort(key=lambda x: -x[3])
    top = proposals[:top_n]
    rows = []
    cmax = top[0][3] if top else 1
    for a, b, euclid, circ in top:
        rows.append({
            "geom": {"type": "LineString", "coordinates": [list(nodes[a]), list(nodes[b])]},
            "impact": round(min(circ, 99), 2),
            "confidence": _confidence(circ, cmax * 0.6, cmax * 0.3),
            "rationale": f"{euclid:.0f} m apart but {circ:.1f}× that by road. A new link "
                         f"would cut detours between these points.",
            "props": {"gap_m": round(euclid), "circuity": round(min(circ, 99), 2)},
        })
    _clear(region_id, "new_link")
    _store(region_id, "new_link", rows)
    return rows


# --------------------------------------------------------------------------
# Direction optimizer — greedy one-way flips minimizing sampled travel time
# --------------------------------------------------------------------------
def _sample_tt(G, od_pairs):
    total, ok = 0.0, 0
    for s, t in od_pairs:
        try:
            total += nx.shortest_path_length(G, s, t, weight="weight")
            ok += 1
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            total += 3600  # penalty for unreachable
    return total / max(ok, 1)


def direction_optimization(region_id, top_n=10, od_samples=40):
    G, nodes, edges = analytics.build_street_graph(region_id)
    if G.number_of_nodes() < 4:
        return []
    node_bt = nx.betweenness_centrality(G, k=min(G.number_of_nodes(), 200),
                                        weight="weight", seed=42)
    node_list = list(G.nodes())
    random.seed(11)
    od = [(random.choice(node_list), random.choice(node_list)) for _ in range(od_samples)]
    base = _sample_tt(G, od)

    # candidate two-way edges (both directions present) ranked by centrality
    twoway = []
    with db.cursor() as cur:
        cur.execute("SELECT id,source_node,target_node,oneway,name,highway,geom "
                    "FROM street_edges WHERE region_id=? AND oneway=0", (region_id,))
        for r in cur.fetchall():
            s, t = r["source_node"], r["target_node"]
            if s is None or t is None:
                continue
            score = (node_bt.get(s, 0) + node_bt.get(t, 0)) / 2
            twoway.append((score, dict(r)))
    twoway.sort(key=lambda x: -x[0])
    candidates = [e for _, e in twoway[:40]]

    accepted = []
    for e in candidates:
        s, t = e["source_node"], e["target_node"]
        if not (G.has_edge(s, t) and G.has_edge(t, s)):
            continue
        # try removing the reverse edge (make one-way s->t)
        data = G[t][s]
        G.remove_edge(t, s)
        if nx.is_strongly_connected(G) if G.number_of_nodes() < 400 else True:
            new_tt = _sample_tt(G, od)
            if new_tt < base - 1e-6:
                improve = (base - new_tt) / base * 100
                accepted.append((e, improve))
                base = new_tt
                continue
        G.add_edge(t, s, **data)  # revert
    accepted.sort(key=lambda x: -x[1])
    top = accepted[:top_n]
    rows = []
    imax = top[0][1] if top else 1
    for e, improve in top:
        rows.append({
            "geom": {"type": "LineString", "coordinates": db.unj(e["geom"])},
            "impact": round(improve, 2),
            "confidence": _confidence(improve, imax * 0.6, imax * 0.3),
            "rationale": f"Converting {e['name'] or 'this ' + (e['highway'] or 'street')} to one-way "
                         f"reduced sampled travel time by {improve:.1f}%.",
            "props": {"edge_id": e["id"], "name": e["name"], "improve_pct": round(improve, 2)},
        })
    _clear(region_id, "direction_change")
    _store(region_id, "direction_change", rows)
    return rows


def get_decisions(region_id, category=None):
    with db.cursor() as cur:
        if category:
            cur.execute("SELECT * FROM actionable_decisions WHERE region_id=? AND category=?",
                        (region_id, category))
        else:
            cur.execute("SELECT * FROM actionable_decisions WHERE region_id=?", (region_id,))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["geom"] = db.unj(r["geom"])
        r["props"] = db.unj(r["props"], {})
    return rows
