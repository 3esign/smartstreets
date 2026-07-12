"""Isochrone (reachability) computation via Dijkstra over the street graph."""

import math

import networkx as nx
from shapely.geometry import MultiPoint, mapping
from shapely.ops import unary_union

from . import analytics, database as db

MODE_SPEED_MS = {"walk": 1.4, "cycle": 4.5, "drive": None}  # drive uses edge speed


def _nearest_node(nodes, lon, lat):
    best, bd = None, 1e18
    for nid, (nlon, nlat) in nodes.items():
        d = (nlon - lon) ** 2 + (nlat - lat) ** 2
        if d < bd:
            bd, best = d, nid
    return best


def compute_isochrone(region_id, lon, lat, mode="walk", minutes=(5, 10, 15)):
    G, nodes, _ = analytics.build_street_graph(region_id)
    if not nodes:
        return {"origin": [lon, lat], "mode": mode, "bands": []}
    origin = _nearest_node(nodes, lon, lat)
    speed = MODE_SPEED_MS.get(mode)

    if speed is None:
        weight = "weight"  # drive: seconds already on edge
    else:
        def weight(u, v, d):
            return d.get("length", 1.0) / speed

    max_min = max(minutes)
    lengths = nx.single_source_dijkstra_path_length(G, origin, cutoff=max_min * 60, weight=weight)

    bands = []
    for m in sorted(minutes, reverse=True):
        pts = [nodes[nid] for nid, sec in lengths.items() if sec <= m * 60 and nid in nodes]
        if len(pts) < 3:
            continue
        # buffer points (~metres → degrees) and union into a reachability blob
        buf_deg = _metre_buffer(lat, 90 if mode == "walk" else (140 if mode == "cycle" else 180))
        blob = unary_union([MultiPoint(pts).buffer(buf_deg)]).simplify(buf_deg / 3)
        geom = mapping(blob)
        coords = _first_polygon(geom)
        if coords:
            bands.append({"minutes": m, "reachable_nodes": len(pts), "coords": coords})
    return {"origin": [lon, lat], "origin_node": origin, "mode": mode, "bands": bands}


# --------------------------------------------------------------------------
# Named saves (explicit user action — computation no longer auto-persists)
# --------------------------------------------------------------------------
def save(region_id, name, mode, origin, bands):
    with db.cursor() as cur:
        cur.execute("INSERT INTO isochrone_saves(region_id,name,mode,origin_lon,origin_lat,bands) "
                    "VALUES(?,?,?,?,?,?)",
                    (region_id, name, mode, origin[0], origin[1], db.j(bands)))
        return cur.lastrowid


def list_saved(region_id):
    with db.cursor() as cur:
        cur.execute("SELECT id,name,mode,origin_lon,origin_lat,created_at "
                    "FROM isochrone_saves WHERE region_id=? ORDER BY id DESC", (region_id,))
        return [dict(r) for r in cur.fetchall()]


def get_saved(save_id):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM isochrone_saves WHERE id=?", (save_id,))
        row = cur.fetchone()
    if not row:
        return None
    out = dict(row)
    out["bands"] = db.unj(out["bands"], [])
    out["origin"] = [out.pop("origin_lon"), out.pop("origin_lat")]
    return out


def delete_saved(save_id):
    with db.cursor() as cur:
        cur.execute("DELETE FROM isochrone_saves WHERE id=?", (save_id,))


def _metre_buffer(lat, metres):
    return metres / (111320 * max(math.cos(math.radians(lat)), 0.1))


def _first_polygon(geom):
    if geom["type"] == "Polygon":
        return [list(c) for c in geom["coordinates"][0]]
    if geom["type"] == "MultiPolygon":
        # largest ring
        best, ring = 0, None
        for poly in geom["coordinates"]:
            r = poly[0]
            if len(r) > best:
                best, ring = len(r), r
        return [list(c) for c in ring] if ring else None
    return None
