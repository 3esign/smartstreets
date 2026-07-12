"""End-to-end verification of the SmartStreet backend on a synthetic grid city.

Run from the repo root (venv active):  python tests/test_synthetic.py
No network access needed — builds a 13x13 street grid, runs the full
analytics stack, isochrone save/load, and a 5-year simulation.
"""
import json
import math
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["SMARTSTREET_DB"] = os.path.join(tempfile.gettempdir(), "smartstreet_test.db")
if os.path.exists(os.environ["SMARTSTREET_DB"]):
    os.remove(os.environ["SMARTSTREET_DB"])

from backend import database as db, analytics, isochrones, simulation  # noqa: E402

db.init_db()
rng = random.Random(7)

LON0, LAT0 = 20.50, 43.14
DLAT = 140 / 110540.0
DLON = 140 / (111320.0 * math.cos(math.radians(LAT0)))
N = 13

with db.cursor() as cur:
    cur.execute("INSERT INTO regions(name,bbox) VALUES('TestCity',?)",
                (db.j([LON0, LAT0, LON0 + N * DLON, LAT0 + N * DLAT]),))
    region_id = cur.lastrowid
    cur.execute("INSERT INTO projects(name,region_id,bbox) VALUES('Test',?, '[]')",
                (region_id,))
    project_id = cur.lastrowid


def nid(i, j):
    return 1000 + i * N + j


nodes = {}
with db.cursor() as cur:
    for i in range(N):
        for j in range(N):
            lon, lat = LON0 + i * DLON, LAT0 + j * DLAT
            nodes[nid(i, j)] = (lon, lat)
            cur.execute("INSERT INTO network_nodes(id,region_id,lon,lat,degree) "
                        "VALUES(?,?,?,?,4)", (nid(i, j), region_id, lon, lat))
    edge_rows = []
    for i in range(N):
        for j in range(N):
            if i < N - 1:
                hw = "primary" if j == 6 else ("secondary" if j == 2 else "residential")
                ms = 60 if hw == "primary" else (50 if hw == "secondary" else 30)
                a, b = nid(i, j), nid(i + 1, j)
                geom = [list(nodes[a]), list(nodes[b])]
                edge_rows.append((None, region_id, a, b, hw, f"H{i}-{j}",
                                  2 if hw != "residential" else 1,
                                  0, ms, "asphalt", None, 140.0, db.j(geom)))
            if j < N - 1:
                if i == 8 and 3 <= j <= 8:      # gap -> detour candidates
                    continue
                hw = "tertiary" if i == 4 else "residential"
                ms = 50 if hw == "tertiary" else 30
                a, b = nid(i, j), nid(i, j + 1)
                geom = [list(nodes[a]), list(nodes[b])]
                edge_rows.append((None, region_id, a, b, hw, f"V{i}-{j}", 1,
                                  0, ms, None, None, 140.0, db.j(geom)))
    cur.executemany(
        "INSERT INTO street_edges(osm_id,region_id,source_node,target_node,highway,"
        "name,lanes,oneway,maxspeed,surface,width,length,geom) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        edge_rows)
    for k in range(80):
        lon = LON0 + (N / 2 + rng.gauss(0, 2.2)) * DLON
        lat = LAT0 + (N / 2 + rng.gauss(0, 2.2)) * DLAT
        cur.execute("INSERT INTO points_of_interest(osm_id,region_id,category,name,lon,lat) "
                    "VALUES(?,?,?,?,?,?)", (k, region_id, "shop", f"P{k}", lon, lat))
    for k in range(220):
        ci, cj = rng.uniform(0, N - 1), rng.uniform(0, N - 1)
        lon, lat = LON0 + ci * DLON, LAT0 + cj * DLAT
        d = 12 / 110540.0
        geom = [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d],
                [lon - d, lat + d], [lon - d, lat - d]]
        cur.execute("INSERT INTO building_footprints(osm_id,region_id,building_type,levels,height,geom) "
                    "VALUES(?,?,?,?,?,?)",
                    (k, region_id, "residential", rng.randint(1, 6), None, db.j(geom)))
    for k in range(30):
        i = rng.randrange(N - 1); j = rng.randrange(N)
        a, b = nid(i, j), nid(i + 1, j)
        geom = [list(nodes[a]), list(nodes[b])]
        cur.execute("INSERT INTO pedestrian_edges(osm_id,region_id,type,surface,lit,geom) "
                    "VALUES(?,?,?,?,?,?)", (k, region_id, "footway", "paved", k % 2, db.j(geom)))
        cur.execute("INSERT INTO cycling_edges(osm_id,region_id,type,surface,oneway,geom) "
                    "VALUES(?,?,?,?,0,?)",
                    (k, region_id, "cycle_lane" if k % 3 else "cycle_track",
                     "asphalt", db.j(geom)))
    for k in range(6):
        cur.execute("INSERT INTO transit_stops(osm_id,region_id,name,mode,lon,lat) "
                    "VALUES(?,?,?,?,?,?)",
                    (k, region_id, f"S{k}", "bus_stop",
                     LON0 + rng.uniform(0, N) * DLON, LAT0 + rng.uniform(0, N) * DLAT))

print("== analytics ==")
summary = analytics.compute_all(region_id)
st = summary["street"]
assert st["edges"] > 300, st
assert 30 <= st["avg_noise"] <= 90, st
assert 0 <= st["avg_voc"] <= 2, st
assert st["avg_co2"] >= 0
assert 0 <= st["avg_street_iq"] <= 1
assert summary["pedestrian"]["edges"] == 30
assert summary["cycling"]["edges"] == 30
print(json.dumps(st, indent=1))

with db.cursor() as cur:
    cur.execute("SELECT COUNT(*) c FROM street_analytics WHERE voc IS NOT NULL")
    assert cur.fetchone()["c"] > 300
    cur.execute("SELECT MIN(lts) a, MAX(lts) b FROM cycling_analytics")
    r = cur.fetchone(); assert 1 <= r["a"] <= r["b"] <= 4, dict(r)

print("== isochrones ==")
iso = isochrones.compute_isochrone(region_id, LON0 + 6 * DLON, LAT0 + 6 * DLAT, "walk")
assert iso["bands"], "no isochrone bands"
with db.cursor() as cur:      # compute must NOT auto-persist
    cur.execute("SELECT COUNT(*) c FROM isochrone_results")
    assert cur.fetchone()["c"] == 0
sid = isochrones.save(region_id, "Centre walk", "walk", iso["origin"], iso["bands"])
assert isochrones.list_saved(region_id)[0]["name"] == "Centre walk"
full = isochrones.get_saved(sid)
assert full["bands"] and full["origin"]
isochrones.delete_saved(sid)
assert isochrones.list_saved(region_id) == []
print(f"bands={[b['minutes'] for b in iso['bands']]} save/load/delete OK")

print("== simulation ==")
print("scipy:", simulation.HAVE_SCIPY)
params = {**simulation.DEFAULTS, "years": 5, "agents_sample": 200, "msa_iters": 3,
          "max_zones": 30, "road_budget": 3.0, "pop_growth_pct": 2.0}
with db.cursor() as cur:
    cur.execute("INSERT INTO sim_runs(project_id,region_id,name,params,status) "
                "VALUES(?,?,?,?,'running')", (project_id, region_id, "test", db.j(params)))
    run_id = cur.lastrowid
simulation._simulate(run_id, region_id, params)

series = simulation.get_series(run_id)
assert len(series) == 5, f"expected 5 years, got {len(series)}"
for row in series:
    s = row["share_car"] + row["share_transit"] + row["share_bike"] + row["share_walk"]
    assert abs(s - 1) < 0.02, f"mode shares sum {s}"
    assert row["vkt"] >= 0 and row["co2_t_day"] >= 0 and row["population"] > 0
    for v in row.values():
        assert v is None or not (isinstance(v, float) and math.isnan(v)), row
assert series[-1]["population"] > series[0]["population"]
y0 = simulation.get_year(run_id, 0)
assert "metrics" in y0 and isinstance(y0["deltas"], list)
agents = simulation.get_agents(run_id, 0)
assert len(agents) > 50, f"only {len(agents)} agents"
a = agents[0]
assert a["m"] in ("car", "transit", "bike", "walk") and len(a["p"]) == len(a["t"]) >= 2
assert all(a["t"][k] <= a["t"][k + 1] for k in range(len(a["t"]) - 1))
deltas_total = sum(len(simulation.get_year(run_id, y)["deltas"]) for y in range(5))
print(f"years=5 agents(y0)={len(agents)} deltas_total={deltas_total}")
print("\nALL TESTS PASSED")
