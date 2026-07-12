"""SmartStreet FastAPI application — API + static dashboard server."""

import os

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (analytics, database as db, isochrones, optimization, osm,
               reports, scenarios)

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

app = FastAPI(title="SmartStreet", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    db.init_db()


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    name: str
    bbox: list[float]          # [w, s, e, n]
    center_lat: float | None = None
    center_lon: float | None = None
    zoom_level: float | None = 13


class Weights(BaseModel):
    centrality: float = 0.35
    flow: float = 0.25
    emissions: float = 0.20
    noise: float = 0.20


class LayerState(BaseModel):
    layer_state: dict


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "smartstreet"}


# --------------------------------------------------------------------------
# Geocoding (city / place search) — proxied to OSM Nominatim
# --------------------------------------------------------------------------
@app.get("/api/geocode")
def geocode(q: str, limit: int = 6):
    q = (q or "").strip()
    if len(q) < 2:
        return []
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "jsonv2", "limit": limit,
                    "addressdetails": 0, "polygon_geojson": 0},
            headers={"User-Agent": "SmartStreet/0.1 (local dashboard)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise HTTPException(502, f"Geocoding failed: {exc}")
    out = []
    for r in data:
        bb = r.get("boundingbox")  # [south, north, west, east] as strings
        bbox = None
        if bb and len(bb) == 4:
            s, n, w, e = (float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]))
            bbox = [w, s, e, n]
        out.append({
            "name": r.get("display_name"),
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "type": r.get("type"), "category": r.get("category"),
            "bbox": bbox,
        })
    return out


# --------------------------------------------------------------------------
# Projects
# --------------------------------------------------------------------------
@app.post("/api/projects")
def create_project(body: ProjectCreate):
    if len(body.bbox) != 4:
        raise HTTPException(400, "bbox must be [w,s,e,n]")
    w, s, e, n = body.bbox
    area = osm.bbox_area_km2(w, s, e, n)
    if area > 50:
        raise HTTPException(400, f"Area {area:.1f} km² exceeds the 50 km² limit.")
    try:
        region_id, tier, area, counts = osm.fetch_region(w, s, e, n, body.name)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))

    clat = body.center_lat if body.center_lat is not None else (s + n) / 2
    clon = body.center_lon if body.center_lon is not None else (w + e) / 2
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO projects(name,region_id,center_lat,center_lon,zoom_level,"
            "bbox,detail_tier,layer_state) VALUES(?,?,?,?,?,?,?,?)",
            (body.name, region_id, clat, clon, body.zoom_level or 13,
             db.j(body.bbox), tier, db.j({
                 "streets": True, "pedestrian": True, "cycling": True,
                 "transit": False, "pois": False, "buildings": False,
             })),
        )
        project_id = cur.lastrowid

    # auto-run all analytics so every layer is immediately colorable
    summary = analytics.compute_all(region_id)
    return {
        "project_id": project_id, "region_id": region_id, "tier": tier,
        "area_km2": round(area, 2), "counts": counts, "analytics": summary,
    }


@app.get("/api/projects")
def list_projects():
    with db.cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["bbox"] = db.unj(r["bbox"], [])
        r["layer_state"] = db.unj(r["layer_state"], {})
    return rows


@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "project not found")
    proj = dict(row)
    proj["bbox"] = db.unj(proj["bbox"], [])
    proj["layer_state"] = db.unj(proj["layer_state"], {})
    proj["stats"] = _region_stats(proj["region_id"])
    return proj


@app.put("/api/projects/{project_id}/layers")
def save_layers(project_id: int, body: LayerState):
    with db.cursor() as cur:
        cur.execute("UPDATE projects SET layer_state=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?", (db.j(body.layer_state), project_id))
    return {"ok": True}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int):
    with db.cursor() as cur:
        cur.execute("SELECT region_id FROM projects WHERE id=?", (project_id,))
        row = cur.fetchone()
        if row:
            cur.execute("DELETE FROM regions WHERE id=?", (row["region_id"],))
        cur.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"ok": True}


@app.post("/api/projects/{project_id}/analytics")
def run_analytics(project_id: int, weights: Weights):
    with db.cursor() as cur:
        cur.execute("SELECT region_id FROM projects WHERE id=?", (project_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "project not found")
    return analytics.compute_all(row["region_id"], weights.model_dump())


# --------------------------------------------------------------------------
# Region stats + layers
# --------------------------------------------------------------------------
def _region_stats(region_id):
    stats = {}
    with db.cursor() as cur:
        for label, table in [
            ("streets", "street_edges"), ("pedestrian", "pedestrian_edges"),
            ("cycling", "cycling_edges"), ("transit_routes", "transit_routes"),
            ("transit_stops", "transit_stops"), ("pois", "points_of_interest"),
            ("buildings", "building_footprints"), ("nodes", "network_nodes"),
        ]:
            cur.execute(f"SELECT COUNT(*) c FROM {table} WHERE region_id=?", (region_id,))
            stats[label] = cur.fetchone()["c"]
        cur.execute("SELECT COALESCE(SUM(length),0) l, "
                    "COALESCE(SUM(oneway),0) ow, COUNT(*) c "
                    "FROM street_edges WHERE region_id=?", (region_id,))
        r = cur.fetchone()
        stats["road_km"] = round((r["l"] or 0) / 1000.0, 2)
        stats["oneway_pct"] = round(100 * r["ow"] / r["c"], 1) if r["c"] else 0
        cur.execute("SELECT AVG(street_iq) iq, AVG(co2_emissions) co2, "
                    "AVG(noise_db) noise FROM street_analytics WHERE edge_id IN "
                    "(SELECT id FROM street_edges WHERE region_id=?)", (region_id,))
        a = cur.fetchone()
        stats["avg_street_iq"] = round(a["iq"], 3) if a["iq"] is not None else None
        stats["avg_co2"] = round(a["co2"], 1) if a["co2"] is not None else None
        stats["avg_noise"] = round(a["noise"], 1) if a["noise"] is not None else None
        cur.execute("SELECT AVG(completeness) c FROM street_analytics WHERE edge_id IN "
                    "(SELECT id FROM street_edges WHERE region_id=?)", (region_id,))
        cc = cur.fetchone()["c"]
        stats["data_quality_pct"] = round(cc * 100) if cc is not None else None
        cur.execute("SELECT AVG(walkability) w FROM pedestrian_analytics WHERE edge_id IN "
                    "(SELECT id FROM pedestrian_edges WHERE region_id=?)", (region_id,))
        w = cur.fetchone()["w"]
        stats["avg_walkability"] = round(w, 3) if w is not None else None
        cur.execute("SELECT AVG(bikeability) b, AVG(lts) l FROM cycling_analytics WHERE edge_id IN "
                    "(SELECT id FROM cycling_edges WHERE region_id=?)", (region_id,))
        cy = cur.fetchone()
        stats["avg_bikeability"] = round(cy["b"], 3) if cy["b"] is not None else None
        stats["avg_lts"] = round(cy["l"], 1) if cy["l"] is not None else None
    return stats


@app.get("/api/regions/{region_id}/stats")
def region_stats(region_id: int):
    return _region_stats(region_id)


def _fc(features):
    return JSONResponse({"type": "FeatureCollection", "features": features})


@app.get("/api/regions/{region_id}/layers/streets")
def layer_streets(region_id: int, time_slot: str = "midday"):
    factor = analytics.TIME_SLOTS.get(time_slot, 1.0)
    feats = []
    with db.cursor() as cur:
        cur.execute(
            "SELECT e.id,e.name,e.highway,e.oneway,e.maxspeed,e.length,e.geom,"
            "a.betweenness,a.closeness,a.modeled_flow,a.co2_emissions,a.noise_db,"
            "a.street_iq,a.completeness "
            "FROM street_edges e LEFT JOIN street_analytics a ON a.edge_id=e.id "
            "WHERE e.region_id=?", (region_id,))
        for r in cur.fetchall():
            flow = (r["modeled_flow"] or 0) * factor
            co2 = (r["co2_emissions"] or 0) * factor
            noise = (r["noise_db"] or 0) + (2.0 if factor > 1 else (-2.0 if factor < 0.6 else 0))
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": db.unj(r["geom"])},
                "properties": {
                    "id": r["id"], "name": r["name"], "highway": r["highway"],
                    "oneway": r["oneway"], "maxspeed": r["maxspeed"],
                    "length": round(r["length"] or 0, 1),
                    "betweenness": r["betweenness"], "closeness": r["closeness"],
                    "modeled_flow": flow, "co2_emissions": co2,
                    "noise_db": noise, "street_iq": r["street_iq"],
                    "completeness": r["completeness"],
                },
            })
    return _fc(feats)


def _simple_lines(region_id, table, props):
    feats = []
    cols = ",".join(props)
    with db.cursor() as cur:
        cur.execute(f"SELECT {cols},geom FROM {table} WHERE region_id=?", (region_id,))
        for r in cur.fetchall():
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": db.unj(r["geom"])},
                "properties": {p: r[p] for p in props},
            })
    return _fc(feats)


@app.get("/api/regions/{region_id}/layers/pedestrian")
def layer_ped(region_id: int):
    feats = []
    with db.cursor() as cur:
        cur.execute("SELECT e.id,e.type,e.surface,e.lit,e.geom,"
                    "a.walkability,a.safety,a.connectivity FROM pedestrian_edges e "
                    "LEFT JOIN pedestrian_analytics a ON a.edge_id=e.id WHERE e.region_id=?",
                    (region_id,))
        for r in cur.fetchall():
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": db.unj(r["geom"])},
                          "properties": {"id": r["id"], "type": r["type"], "surface": r["surface"],
                                         "lit": r["lit"], "walkability": r["walkability"],
                                         "safety": r["safety"], "connectivity": r["connectivity"]}})
    return _fc(feats)


@app.get("/api/regions/{region_id}/layers/cycling")
def layer_cyc(region_id: int):
    feats = []
    with db.cursor() as cur:
        cur.execute("SELECT e.id,e.type,e.surface,e.oneway,e.geom,a.lts,a.bikeability "
                    "FROM cycling_edges e LEFT JOIN cycling_analytics a ON a.edge_id=e.id "
                    "WHERE e.region_id=?", (region_id,))
        for r in cur.fetchall():
            feats.append({"type": "Feature",
                          "geometry": {"type": "LineString", "coordinates": db.unj(r["geom"])},
                          "properties": {"id": r["id"], "type": r["type"], "surface": r["surface"],
                                         "oneway": r["oneway"], "lts": r["lts"],
                                         "bikeability": r["bikeability"]}})
    return _fc(feats)


@app.get("/api/regions/{region_id}/layers/transit")
def layer_transit(region_id: int):
    return _simple_lines(region_id, "transit_routes", ["id", "name", "mode"])


def _simple_points(region_id, table, props):
    feats = []
    cols = ",".join(props)
    with db.cursor() as cur:
        cur.execute(f"SELECT {cols},lon,lat FROM {table} WHERE region_id=?", (region_id,))
        for r in cur.fetchall():
            if r["lon"] is None:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {p: r[p] for p in props},
            })
    return _fc(feats)


@app.get("/api/regions/{region_id}/layers/transit_stops")
def layer_tstops(region_id: int):
    return _simple_points(region_id, "transit_stops", ["id", "name", "mode"])


@app.get("/api/regions/{region_id}/layers/pois")
def layer_pois(region_id: int):
    return _simple_points(region_id, "points_of_interest", ["id", "name", "category"])


@app.get("/api/regions/{region_id}/layers/buildings")
def layer_buildings(region_id: int):
    feats = []
    with db.cursor() as cur:
        cur.execute("SELECT id,building_type,levels,height,geom FROM building_footprints "
                    "WHERE region_id=?", (region_id,))
        for r in cur.fetchall():
            coords = db.unj(r["geom"])
            if not coords or coords[0] != coords[-1]:
                coords = coords + [coords[0]] if coords else coords
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {"id": r["id"], "building_type": r["building_type"],
                               "levels": r["levels"], "height": r["height"]},
            })
    return _fc(feats)


@app.get("/api/regions/{region_id}/histogram")
def histogram(region_id: int, metric: str = "street_iq", bins: int = 20):
    allowed = {"street_iq", "betweenness", "closeness", "co2_emissions", "noise_db",
               "modeled_flow", "completeness"}
    if metric not in allowed:
        raise HTTPException(400, f"metric must be one of {allowed}")
    with db.cursor() as cur:
        cur.execute(f"SELECT {metric} v FROM street_analytics WHERE edge_id IN "
                    f"(SELECT id FROM street_edges WHERE region_id=?) AND {metric} IS NOT NULL",
                    (region_id,))
        vals = [r["v"] for r in cur.fetchall()]
    if not vals:
        return {"bins": [], "counts": [], "metric": metric}
    import numpy as np
    counts, edges = np.histogram(vals, bins=bins)
    return {"metric": metric, "counts": counts.tolist(),
            "bins": [round(x, 4) for x in edges.tolist()]}


# --------------------------------------------------------------------------
# Isochrones
# --------------------------------------------------------------------------
class IsochroneReq(BaseModel):
    lon: float
    lat: float
    mode: str = "walk"
    minutes: list[int] = [5, 10, 15]


@app.post("/api/regions/{region_id}/isochrone")
def make_isochrone(region_id: int, body: IsochroneReq):
    return isochrones.compute_isochrone(region_id, body.lon, body.lat, body.mode,
                                        tuple(body.minutes))


# --------------------------------------------------------------------------
# Optimization
# --------------------------------------------------------------------------
@app.post("/api/regions/{region_id}/optimize/{kind}")
def optimize(region_id: int, kind: str):
    fn = {"signals": optimization.signal_placement,
          "connectivity": optimization.connectivity_gaps,
          "direction": optimization.direction_optimization}.get(kind)
    if not fn:
        raise HTTPException(400, "kind must be signals|connectivity|direction")
    rows = fn(region_id)
    return {"kind": kind, "count": len(rows), "decisions": rows}


@app.get("/api/regions/{region_id}/decisions")
def decisions(region_id: int, category: str | None = None):
    return optimization.get_decisions(region_id, category)


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
class ScenarioCreate(BaseModel):
    project_id: int
    region_id: int
    name: str


class OverrideReq(BaseModel):
    target_id: int
    action_type: str          # closure | direction_change | attribute_change
    attribute_overrides: dict = {}


@app.post("/api/scenarios")
def scenario_create(body: ScenarioCreate):
    sid = scenarios.create(body.project_id, body.region_id, body.name)
    return {"scenario_id": sid}


@app.get("/api/projects/{project_id}/scenarios")
def scenario_list(project_id: int):
    return scenarios.list_scenarios(project_id)


@app.post("/api/scenarios/{scenario_id}/overrides")
def scenario_add_override(scenario_id: int, body: OverrideReq):
    scenarios.add_override(scenario_id, body.target_id, body.action_type,
                           body.attribute_overrides)
    return {"overrides": scenarios.list_overrides(scenario_id)}


@app.post("/api/scenarios/{scenario_id}/undo")
def scenario_undo(scenario_id: int):
    return {"overrides": scenarios.undo(scenario_id)}


@app.post("/api/scenarios/{scenario_id}/redo")
def scenario_redo(scenario_id: int):
    return {"overrides": scenarios.redo(scenario_id)}


@app.get("/api/scenarios/{scenario_id}/compare")
def scenario_compare(scenario_id: int):
    res = scenarios.compare(scenario_id)
    if res is None:
        raise HTTPException(404, "scenario not found")
    return res


@app.delete("/api/scenarios/{scenario_id}")
def scenario_delete(scenario_id: int):
    scenarios.delete(scenario_id)
    return {"ok": True}


# --------------------------------------------------------------------------
# Exports & reports
# --------------------------------------------------------------------------
@app.get("/api/regions/{region_id}/export/streets.csv")
def export_csv(region_id: int):
    return PlainTextResponse(reports.street_csv(region_id), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=streets.csv"})


@app.get("/api/regions/{region_id}/export/streets.geojson")
def export_geojson(region_id: int):
    import json as _json
    fc = layer_streets(region_id)
    return JSONResponse(_json.loads(fc.body),
                        headers={"Content-Disposition": "attachment; filename=streets.geojson"})


@app.get("/api/regions/{region_id}/report")
def report(region_id: int, name: str = "SmartStreet Project"):
    return HTMLResponse(reports.html_report(region_id, name))


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
# end of app
