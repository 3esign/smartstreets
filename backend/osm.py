"""OSM ingestion via the Overpass API with progressive bbox detail tiers.

Fetches streets, pedestrian, cycling, transit routes/stops, POIs and buildings
for a bounding box, parses the Overpass JSON into the relational tables, and
returns per-layer counts.
"""

import math
import time

import requests

from . import database as db

OVERPASS_URLS = [
    "https://overpass.nchc.org.tw/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

# Highway classes considered "vehicular streets"
STREET_HW = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "living_street", "service",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link", "road",
}
PED_HW = {"footway", "pedestrian", "path", "steps", "track", "corridor"}


def bbox_area_km2(w, s, e, n):
    """Approximate area of a lon/lat bbox in km²."""
    mid = math.radians((s + n) / 2)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(mid)
    return abs((n - s) * km_per_deg_lat) * abs((e - w) * km_per_deg_lon)


def detail_tier(area):
    if area <= 5:
        return "A"
    if area <= 15:
        return "B"
    return "C"


def _haversine(lon1, lat1, lon2, lat2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _line_length(coords):
    return sum(
        _haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )


def _to_int(v):
    if v is None:
        return None
    try:
        return int(float(str(v).split()[0].split(";")[0]))
    except (ValueError, IndexError):
        return None


def build_query(w, s, e, n, tier):
    bbox = f"{s},{w},{n},{e}"
    if tier == "C":
        hw_filter = "motorway|trunk|primary"
        return f"""
[out:json][timeout:90];
(
  way["highway"~"{hw_filter}"]({bbox});
  relation["route"~"train|subway|light_rail|tram"]({bbox});
);
out body geom;
"""
    if tier == "B":
        hw_filter = "motorway|trunk|primary|secondary|tertiary"
        return f"""
[out:json][timeout:120];
(
  way["highway"~"{hw_filter}"]({bbox});
  way["highway"="footway"]({bbox});
  way["highway"="cycleway"]({bbox});
  relation["route"~"bus|trolleybus|tram|subway|train|light_rail"]({bbox});
  node["public_transport"="stop_position"]({bbox});
  node["highway"="bus_stop"]({bbox});
);
out body geom;
"""
    # Tier A — full detail
    return f"""
[out:json][timeout:180];
(
  way["highway"]({bbox});
  way["cycleway"]({bbox});
  relation["route"~"bus|trolleybus|tram|subway|train|light_rail"]({bbox});
  node["public_transport"="stop_position"]({bbox});
  node["highway"="bus_stop"]({bbox});
  node["railway"~"station|halt|tram_stop"]({bbox});
  node["amenity"~"school|hospital|pharmacy|restaurant|cafe|bank"]({bbox});
  node["shop"]({bbox});
  node["leisure"="park"]({bbox});
  way["building"]({bbox});
);
out body geom;
"""


def fetch_overpass(query):
    last_err = None
    max_passes = 3  # Attempt to fetch from all endpoints in rotation up to 3 times
    for pass_idx in range(max_passes):
        for url in OVERPASS_URLS:
            try:
                # Use timeout of 200 seconds to allow the server to complete heavy queries
                resp = requests.post(url, data={"data": query}, timeout=200)
                if resp.status_code == 200:
                    return resp.json()
                
                last_err = f"HTTP {resp.status_code} from {url}"
                if resp.status_code == 429:
                    # Rate limited: skip immediately to try another mirror
                    continue
                elif resp.status_code in (502, 503, 504):
                    # Server busy/timeout: skip immediately to try another mirror
                    continue
            except requests.RequestException as exc:
                last_err = f"Connection error: {exc} for {url}"
            
            # Short sleep before trying next URL to avoid slamming endpoints
            time.sleep(1)
            
        if pass_idx < max_passes - 1:
            # Wait with exponential backoff before making another pass through all endpoints
            time.sleep(2 * (pass_idx + 1))
            
    raise RuntimeError(f"Overpass fetch failed (all endpoints exhausted): {last_err}")


def _cycle_type(tags):
    if tags.get("highway") == "cycleway":
        return "cycle_track"
    cw = tags.get("cycleway") or tags.get("cycleway:left") or tags.get("cycleway:right")
    if cw in ("lane", "opposite_lane"):
        return "cycle_lane"
    if cw == "track":
        return "cycle_track"
    if tags.get("bicycle") == "designated":
        return "shared_road"
    return None


def _poi_category(tags):
    if "shop" in tags:
        return "shop"
    amenity = tags.get("amenity")
    if amenity in ("school", "hospital", "pharmacy", "restaurant", "cafe", "bank"):
        return amenity
    if tags.get("leisure") == "park":
        return "park"
    return None


def parse_and_store(data, region_id):
    counts = {
        "streets": 0, "pedestrian": 0, "cycling": 0,
        "transit_routes": 0, "transit_stops": 0, "pois": 0, "buildings": 0,
        "nodes": 0,
    }
    node_rows = {}          # node_id -> (lon, lat)
    node_degree = {}
    street_rows, ped_rows, cyc_rows = [], [], []
    troute_rows, tstop_rows, poi_rows, bld_rows = [], [], [], []

    for el in data.get("elements", []):
        etype = el.get("type")
        tags = el.get("tags", {}) or {}

        if etype == "node":
            lon, lat = el.get("lon"), el.get("lat")
            if lon is None:
                continue
            if tags.get("highway") == "bus_stop" or tags.get("public_transport") == "stop_position":
                tstop_rows.append((el["id"], region_id, tags.get("name"), "bus_stop", lon, lat))
            elif tags.get("railway") in ("station", "halt", "tram_stop"):
                tstop_rows.append((el["id"], region_id, tags.get("name"),
                                   tags.get("railway"), lon, lat))
            cat = _poi_category(tags)
            if cat:
                poi_rows.append((el["id"], region_id, cat, tags.get("name"), lon, lat))
            continue

        if etype == "way":
            geom = el.get("geometry")
            if not geom or len(geom) < 2:
                continue
            coords = [[g["lng"] if "lng" in g else g["lon"], g["lat"]] for g in geom]

            if "building" in tags:
                bld_rows.append((
                    el["id"], region_id, tags.get("building"),
                    _to_int(tags.get("building:levels")), _to_int(tags.get("height")),
                    db.j(coords),
                ))
                continue

            hw = tags.get("highway")
            cyc_t = _cycle_type(tags)
            if cyc_t:
                cyc_rows.append((
                    el["id"], region_id, cyc_t, tags.get("surface"),
                    1 if tags.get("oneway") == "yes" else 0, db.j(coords),
                ))
            if hw in STREET_HW:
                nds = el.get("nodes", [])
                src = nds[0] if nds else None
                tgt = nds[-1] if nds else None
                if src is not None:
                    node_rows.setdefault(src, (coords[0][0], coords[0][1]))
                    node_rows.setdefault(tgt, (coords[-1][0], coords[-1][1]))
                    node_degree[src] = node_degree.get(src, 0) + 1
                    node_degree[tgt] = node_degree.get(tgt, 0) + 1
                street_rows.append((
                    el["id"], region_id, src, tgt, hw, tags.get("name"),
                    _to_int(tags.get("lanes")),
                    1 if tags.get("oneway") == "yes" else 0,
                    _to_int(tags.get("maxspeed")), tags.get("surface"),
                    _to_int(tags.get("width")), _line_length(coords), db.j(coords),
                ))
            elif hw in PED_HW:
                ped_rows.append((
                    el["id"], region_id, hw, tags.get("surface"),
                    1 if tags.get("lit") == "yes" else 0, db.j(coords),
                ))
            continue

        if etype == "relation":
            route = tags.get("route")
            if not route:
                continue
            coords = []
            for m in el.get("members", []):
                g = m.get("geometry")
                if g:
                    coords.extend([[p.get("lon", p.get("lng")), p["lat"]] for p in g])
            if len(coords) < 2:
                continue
            troute_rows.append((
                el["id"], region_id, tags.get("name") or tags.get("ref"),
                route, tags.get("operator"), db.j(coords),
            ))

    with db.cursor() as cur:
        for nid, (lon, lat) in node_rows.items():
            cur.execute(
                "INSERT OR REPLACE INTO network_nodes(id,region_id,lon,lat,degree) "
                "VALUES(?,?,?,?,?)",
                (nid, region_id, lon, lat, node_degree.get(nid, 0)),
            )
        counts["nodes"] = len(node_rows)

        cur.executemany(
            "INSERT INTO street_edges(osm_id,region_id,source_node,target_node,highway,"
            "name,lanes,oneway,maxspeed,surface,width,length,geom) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", street_rows)
        counts["streets"] = len(street_rows)

        cur.executemany(
            "INSERT INTO pedestrian_edges(osm_id,region_id,type,surface,lit,geom) "
            "VALUES(?,?,?,?,?,?)", ped_rows)
        counts["pedestrian"] = len(ped_rows)

        cur.executemany(
            "INSERT INTO cycling_edges(osm_id,region_id,type,surface,oneway,geom) "
            "VALUES(?,?,?,?,?,?)", cyc_rows)
        counts["cycling"] = len(cyc_rows)

        cur.executemany(
            "INSERT INTO transit_routes(osm_id,region_id,name,mode,operator,geom) "
            "VALUES(?,?,?,?,?,?)", troute_rows)
        counts["transit_routes"] = len(troute_rows)

        cur.executemany(
            "INSERT INTO transit_stops(osm_id,region_id,name,mode,lon,lat) "
            "VALUES(?,?,?,?,?,?)", tstop_rows)
        counts["transit_stops"] = len(tstop_rows)

        cur.executemany(
            "INSERT INTO points_of_interest(osm_id,region_id,category,name,lon,lat) "
            "VALUES(?,?,?,?,?,?)", poi_rows)
        counts["pois"] = len(poi_rows)

        cur.executemany(
            "INSERT INTO building_footprints(osm_id,region_id,building_type,levels,height,geom) "
            "VALUES(?,?,?,?,?,?)", bld_rows)
        counts["buildings"] = len(bld_rows)

    return counts


def fetch_region(w, s, e, n, name="Region"):
    """Fetch a bbox from Overpass, store it, return (region_id, tier, counts)."""
    area = bbox_area_km2(w, s, e, n)
    tier = detail_tier(area)
    with db.cursor() as cur:
        cur.execute("INSERT INTO regions(name,bbox) VALUES(?,?)",
                    (name, db.j([w, s, e, n])))
        region_id = cur.lastrowid
    query = build_query(w, s, e, n, tier)
    data = fetch_overpass(query)
    counts = parse_and_store(data, region_id)
    return region_id, tier, area, counts
