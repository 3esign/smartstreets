"""Multi-year agent-based urban evolution simulator.

Implements a mesoscopic land-use / transport interaction (LUTI) loop,
executed once per simulated year:

  1. Demographic growth      — exponential population growth, allocated to
                               zones by a logit model on accessibility
                               (Hansen 1959) and remaining floor capacity.
  2. Travel demand           — trip generation proportional to zone
                               population; destination choice by a
                               singly-constrained gravity model with
                               negative-exponential impedance (Wilson 1971).
  3. Mode choice             — multinomial logit over car / transit / bike /
                               walk generalized times (McFadden 1974).
  4. Car assignment          — iterative capacity-restrained assignment via
                               the Method of Successive Averages (Sheffi
                               1985) with BPR volume-delay functions
                               (Bureau of Public Roads 1964), approximating
                               Wardrop user equilibrium.
  5. Network evolution       — demand-responsive infrastructure rules
                               modelled on the empirically observed
                               "densification + exploration" processes of
                               street-network growth (Strano et al. 2012;
                               Barthelemy & Flammini 2008): capacity
                               upgrades on saturated links, new links where
                               spatial detours and demand are high, optional
                               pedestrianization of calm POI-rich streets.
  6. Environmental outputs   — COPERT-style average-speed CO2 factors and
                               simplified CNOSSOS-EU (2015/996) noise levels
                               (see analytics.py), Hansen accessibility,
                               congestion and network statistics.

A sample of individual agents (households' trips) is drawn each year from
the OD/mode distribution and their space-time trajectories are stored for
front-end animation. Full references: docs/METHODOLOGY.md.
"""

import json
import math
import random
import threading
import traceback

import numpy as np

from . import analytics, database as db

try:
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import dijkstra as _sp_dijkstra
    HAVE_SCIPY = True
except Exception:                                             # pragma: no cover
    HAVE_SCIPY = False

# ---------------------------------------------------------------------------
# Parameters (all overridable through the API)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "name": "Simulation",
    "years": 20,                  # horizon
    "pop_growth_pct": 1.2,        # % per year (negative allowed = shrinkage)
    "car_ownership_growth_pct": 0.5,  # % change of car preference per year
    "transit_invest": 0.3,        # 0..1: service improvement effort per year
    "bike_invest": 0.3,           # 0..1: cycling network comfort growth
    "road_budget": 2.0,           # lane-km equivalents per year
    "pedestrianization": True,    # allow converting calm streets
    "trip_rate": 2.3,             # motorised+active trips / person / day
    "peak_share": 0.10,           # share of daily trips in the peak hour
    "gravity_beta": 0.08,         # 1/min impedance (mean trip ~15 min)
    "vot_coef": -0.055,           # utility per minute (logit scale)
    "petrol_share": 0.6,          # fleet mix for CO2
    "msa_iters": 4,               # assignment iterations
    "agents_sample": 800,         # animated agents per year
    "max_zones": 64,
    "seed": 42,
}

MODE_SPEEDS = {"walk": 1.34, "bike": 4.2}      # m/s (Bohannon 1997; ~15 km/h)
DAY_EXPANSION = 10.0                            # peak hour ~10 % of daily flow

_cancel_flags = {}
_threads = {}


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------
def start_run(project_id, region_id, params):
    p = {**DEFAULTS, **{k: v for k, v in (params or {}).items() if v is not None}}
    p["years"] = int(max(1, min(50, p["years"])))
    with db.cursor() as cur:
        cur.execute("INSERT INTO sim_runs(project_id,region_id,name,params,status) "
                    "VALUES(?,?,?,?,'queued')",
                    (project_id, region_id, p.get("name") or "Simulation", db.j(p)))
        run_id = cur.lastrowid
    t = threading.Thread(target=_run_safe, args=(run_id, region_id, p), daemon=True)
    _threads[run_id] = t
    t.start()
    return run_id


def cancel_run(run_id):
    _cancel_flags[run_id] = True


def get_run(run_id):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM sim_runs WHERE id=?", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        run = dict(row)
        cur.execute("SELECT year FROM sim_years WHERE run_id=? ORDER BY year", (run_id,))
        run["years_done"] = [r["year"] for r in cur.fetchall()]
    run["params"] = db.unj(run["params"], {})
    return run


def list_runs(project_id):
    with db.cursor() as cur:
        cur.execute("SELECT id,name,status,progress,created_at,params FROM sim_runs "
                    "WHERE project_id=? ORDER BY id DESC", (project_id,))
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        r["params"] = db.unj(r["params"], {})
    return rows


def delete_run(run_id):
    cancel_run(run_id)
    with db.cursor() as cur:
        cur.execute("DELETE FROM sim_runs WHERE id=?", (run_id,))


def get_year(run_id, year):
    with db.cursor() as cur:
        cur.execute("SELECT metrics,deltas,voc FROM sim_years WHERE run_id=? AND year=?",
                    (run_id, year))
        row = cur.fetchone()
    if not row:
        return None
    return {"year": year, "metrics": db.unj(row["metrics"], {}),
            "deltas": db.unj(row["deltas"], []), "voc": db.unj(row["voc"], {})}


def get_agents(run_id, year):
    with db.cursor() as cur:
        cur.execute("SELECT agents FROM sim_agents WHERE run_id=? AND year=?",
                    (run_id, year))
        row = cur.fetchone()
    return db.unj(row["agents"], []) if row else []


def get_series(run_id):
    with db.cursor() as cur:
        cur.execute("SELECT year,metrics FROM sim_years WHERE run_id=? ORDER BY year",
                    (run_id,))
        return [{"year": r["year"], **db.unj(r["metrics"], {})} for r in cur.fetchall()]


def _set_status(run_id, status=None, progress=None, message=None):
    sets, vals = [], []
    if status is not None:
        sets.append("status=?"); vals.append(status)
    if progress is not None:
        sets.append("progress=?"); vals.append(round(progress, 3))
    if message is not None:
        sets.append("message=?"); vals.append(message[:500])
    if not sets:
        return
    vals.append(run_id)
    with db.cursor() as cur:
        cur.execute(f"UPDATE sim_runs SET {','.join(sets)} WHERE id=?", vals)


def _run_safe(run_id, region_id, p):
    try:
        _set_status(run_id, status="running", progress=0.0, message="Preparing model…")
        _simulate(run_id, region_id, p)
        if _cancel_flags.pop(run_id, False):
            _set_status(run_id, status="error", message="Cancelled")
        else:
            _set_status(run_id, status="done", progress=1.0, message="Complete")
    except Exception as exc:                                   # pragma: no cover
        traceback.print_exc()
        _set_status(run_id, status="error", message=f"{type(exc).__name__}: {exc}")
    finally:
        _threads.pop(run_id, None)


# ---------------------------------------------------------------------------
# Model state
# ---------------------------------------------------------------------------
class Net:
    """Mutable directed network state (grows over the years)."""

    def __init__(self, region_id):
        G, nodes, edges = analytics.build_street_graph(region_id)
        self.node_ids = list(nodes.keys())
        self.idx = {nid: i for i, nid in enumerate(self.node_ids)}
        self.lon = np.array([nodes[n][0] for n in self.node_ids])
        self.lat = np.array([nodes[n][1] for n in self.node_ids])
        self.n = len(self.node_ids)
        lat0 = float(np.mean(self.lat)) if self.n else 45.0
        self.mlon = 111320.0 * math.cos(math.radians(lat0))   # m per deg lon
        self.mlat = 110540.0

        # directed edge arrays
        self.eu, self.ev, self.length, self.t0 = [], [], [], []
        self.cap, self.eid, self.lanes, self.hw = [], [], [], []
        self.geom = {}                                        # eid -> coords
        self.closed_car = set()                               # pedestrianized
        for e in edges:
            if e.get("_closed"):
                continue
            s, t = e["source_node"], e["target_node"]
            if s not in self.idx or t not in self.idx:
                continue
            speed = e["maxspeed"] or analytics.DEFAULT_MAXSPEED.get(
                analytics._hwbase(e["highway"]), 40)
            cap = analytics.CAPACITY.get(analytics._hwbase(e["highway"]), 500)
            ln = e["lanes"] or (2 if analytics._hwbase(e["highway"]) in
                                ("motorway", "trunk", "primary") else 1)
            length = e["length"] or 1.0
            self._add_dir(s, t, length, speed, cap, e["id"], ln, e["highway"])
            if not e["oneway"]:
                self._add_dir(t, s, length, speed, cap, e["id"], ln, e["highway"])
        with db.cursor() as cur:
            cur.execute("SELECT id,geom FROM street_edges WHERE region_id=?", (region_id,))
            for r in cur.fetchall():
                self.geom[r["id"]] = db.unj(r["geom"], [])
        self._np()
        self.new_eid = -1

    def _add_dir(self, s, t, length, speed, cap, eid, lanes, hw):
        self.eu.append(self.idx[s]); self.ev.append(self.idx[t])
        self.length.append(length)
        self.t0.append(length / max(speed * 1000 / 3600, 1.0))
        self.cap.append(float(cap)); self.eid.append(eid)
        self.lanes.append(int(lanes)); self.hw.append(hw or "residential")

    def _np(self):
        self.eu = np.asarray(self.eu, dtype=np.int32)
        self.ev = np.asarray(self.ev, dtype=np.int32)
        self.length = np.asarray(self.length, dtype=np.float64)
        self.t0 = np.asarray(self.t0, dtype=np.float64)
        self.cap = np.asarray(self.cap, dtype=np.float64)
        self.eid = np.asarray(self.eid, dtype=np.int64)
        self.lanes = np.asarray(self.lanes, dtype=np.int32)

    def add_link(self, i, j, speed, cap, lanes, hw):
        """Insert a new two-way link between node indices i and j."""
        self.new_eid -= 1
        eid = self.new_eid
        dx = (self.lon[j] - self.lon[i]) * self.mlon
        dy = (self.lat[j] - self.lat[i]) * self.mlat
        length = float(math.hypot(dx, dy))
        t0 = length / max(speed * 1000 / 3600, 1.0)
        for (a, b) in ((i, j), (j, i)):
            self.eu = np.append(self.eu, np.int32(a))
            self.ev = np.append(self.ev, np.int32(b))
            self.length = np.append(self.length, length)
            self.t0 = np.append(self.t0, t0)
            self.cap = np.append(self.cap, float(cap))
            self.eid = np.append(self.eid, np.int64(eid))
            self.lanes = np.append(self.lanes, np.int32(lanes))
            self.hw.append(hw)
        self.geom[eid] = [[float(self.lon[i]), float(self.lat[i])],
                          [float(self.lon[j]), float(self.lat[j])]]
        return eid, length

    def upgrade(self, mask_eid):
        """Add one lane to every directed edge with given edge id."""
        sel = self.eid == mask_eid
        add = self.cap[sel] / np.maximum(self.lanes[sel], 1)
        self.cap[sel] += add
        self.lanes[sel] += 1

    def pedestrianize(self, mask_eid):
        self.closed_car.add(int(mask_eid))

    def car_mask(self):
        if not self.closed_car:
            return np.ones(len(self.eid), dtype=bool)
        return ~np.isin(self.eid, list(self.closed_car))


def _sssp(net, weights, sources, mask=None):
    """Shortest paths from many sources. Returns (dist, pred) arrays
    [len(sources) x n]. Uses scipy when available."""
    w = weights.copy()
    if mask is not None:
        w = np.where(mask, w, np.inf)
    if HAVE_SCIPY:
        finite = np.isfinite(w)
        m = csr_matrix((w[finite], (net.eu[finite], net.ev[finite])),
                       shape=(net.n, net.n))
        dist, pred = _sp_dijkstra(m, directed=True, indices=sources,
                                  return_predecessors=True)
        return dist, pred
    # pure-python fallback (small regions)
    import heapq
    D = np.full((len(sources), net.n), np.inf)
    P = np.full((len(sources), net.n), -9999, dtype=np.int32)
    adj = {}
    for k in range(len(net.eu)):
        if mask is not None and not mask[k]:
            continue
        adj.setdefault(int(net.eu[k]), []).append((int(net.ev[k]), float(weights[k])))
    for si, s in enumerate(sources):
        dist = D[si]; pred = P[si]
        dist[s] = 0.0
        pq = [(0.0, int(s))]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for v, wuv in adj.get(u, ()):
                nd = d + wuv
                if nd < dist[v]:
                    dist[v] = nd; pred[v] = u
                    heapq.heappush(pq, (nd, v))
    return D, P


def _trace(pred_row, src, dst):
    """Node index path src->dst from a predecessor row (or None)."""
    if pred_row[dst] < 0 and dst != src:
        return None
    path, cur, guard = [dst], dst, 0
    while cur != src:
        cur = int(pred_row[cur])
        if cur < 0 or guard > 100000:
            return None
        path.append(cur); guard += 1
    path.reverse()
    return path


# ---------------------------------------------------------------------------
# Zoning & land use
# ---------------------------------------------------------------------------
def _build_zones(net, region_id, max_zones, rng):
    cell_m = 350.0
    keys, key_of = {}, np.empty(net.n, dtype=np.int32)
    for i in range(net.n):
        k = (int(net.lon[i] * net.mlon / cell_m), int(net.lat[i] * net.mlat / cell_m))
        if k not in keys:
            keys[k] = len(keys)
        key_of[i] = keys[k]
    # keep the most populated cells as zones, merge the rest into nearest
    counts = np.bincount(key_of)
    order = np.argsort(-counts)
    kept = list(order[:max_zones])
    zone_of_key = {int(k): zi for zi, k in enumerate(kept)}
    # zone centroid node = node closest to zone mean
    zone_nodes, zone_members = [], [[] for _ in kept]
    for i in range(net.n):
        zk = int(key_of[i])
        if zk in zone_of_key:
            zone_members[zone_of_key[zk]].append(i)
    # nodes in dropped cells -> nearest kept zone by coordinates
    if len(kept) < len(counts):
        cx = np.array([np.mean(net.lon[m]) if m else 0 for m in zone_members])
        cy = np.array([np.mean(net.lat[m]) if m else 0 for m in zone_members])
        for i in range(net.n):
            if int(key_of[i]) not in zone_of_key:
                d = (cx - net.lon[i]) ** 2 + (cy - net.lat[i]) ** 2
                zone_members[int(np.argmin(d))].append(i)
    for m in zone_members:
        mlon, mlat = np.mean(net.lon[m]), np.mean(net.lat[m])
        d = (net.lon[m] - mlon) ** 2 + (net.lat[m] - mlat) ** 2
        zone_nodes.append(int(m[int(np.argmin(d))]))

    # land use per zone: floor area & POIs
    nz = len(zone_nodes)
    floor = np.full(nz, 10.0)
    pois = np.full(nz, 0.5)
    zx = np.array([net.lon[zn] for zn in zone_nodes])
    zy = np.array([net.lat[zn] for zn in zone_nodes])

    def nearest_zone(lon, lat):
        return int(np.argmin((zx - lon) ** 2 + (zy - lat) ** 2))

    with db.cursor() as cur:
        cur.execute("SELECT levels,height,geom FROM building_footprints WHERE region_id=?",
                    (region_id,))
        for r in cur.fetchall():
            coords = db.unj(r["geom"], [])
            if not coords:
                continue
            lon = sum(c[0] for c in coords) / len(coords)
            lat = sum(c[1] for c in coords) / len(coords)
            # shoelace footprint area (m^2)
            a = 0.0
            for k in range(len(coords) - 1):
                x1, y1 = coords[k]; x2, y2 = coords[k + 1]
                a += (x1 * net.mlon) * (y2 * net.mlat) - (x2 * net.mlon) * (y1 * net.mlat)
            area = abs(a) / 2.0
            levels = r["levels"] or (max(1, round((r["height"] or 3) / 3)))
            floor[nearest_zone(lon, lat)] += min(area, 20000) * min(levels, 12)
        cur.execute("SELECT lon,lat FROM points_of_interest WHERE region_id=? "
                    "AND lon IS NOT NULL", (region_id,))
        for r in cur.fetchall():
            pois[nearest_zone(r["lon"], r["lat"])] += 1.0
        cur.execute("SELECT COUNT(*) c FROM transit_stops WHERE region_id=?", (region_id,))
        transit_stops = cur.fetchone()["c"]

    members_count = np.array([len(m) for m in zone_members], dtype=float)
    return {
        "nodes": np.array(zone_nodes, dtype=np.int64),
        "floor": floor, "pois": pois, "members": members_count,
        "transit": transit_stops >= 3,
    }


# ---------------------------------------------------------------------------
# Main yearly loop
# ---------------------------------------------------------------------------
def _simulate(run_id, region_id, p):
    rng = random.Random(p["seed"])
    nprng = np.random.default_rng(p["seed"])
    net = Net(region_id)
    if net.n < 10 or len(net.eid) < 10:
        raise RuntimeError("Region network too small to simulate.")

    zones = _build_zones(net, region_id, int(p["max_zones"]), rng)
    Z = len(zones["nodes"])
    zsrc = zones["nodes"]

    # initial population: ~1 person / 35 m2 of residential floor space
    floor_total = float(np.sum(zones["floor"]))
    pop0 = p.get("start_population") or max(2000.0, floor_total / 35.0 * 0.6)
    pop = zones["floor"] / max(floor_total, 1.0) * pop0
    attraction = zones["pois"] * 40.0 + zones["floor"] / 200.0 + 1.0
    zone_cap = pop * 3.0 + zones["floor"] / 20.0 + 50.0       # soft capacity

    asc = {"car": 0.0, "transit": -0.7 if zones["transit"] else -99.0,
           "bike": -1.2, "walk": 0.0}
    beta = p["gravity_beta"]; vot = p["vot_coef"]
    invest_total = new_km = up_lanekm = ped_km = 0.0
    edge_flow = np.zeros(len(net.eid))
    acc_z = np.ones(Z)

    for y in range(int(p["years"])):
        if _cancel_flags.get(run_id):
            return
        _set_status(run_id, progress=y / p["years"],
                    message=f"Simulating year {y + 1}/{int(p['years'])}…")

        # -- 1. demographics --------------------------------------------------
        growth = pop.sum() * (p["pop_growth_pct"] / 100.0)
        if abs(growth) > 0:
            attr_loc = np.log(np.maximum(acc_z, 1e-6)) + \
                np.log(np.maximum(zone_cap - pop, 1.0) / zone_cap)
            w = np.exp(attr_loc - attr_loc.max())
            share = w / w.sum()
            pop = np.maximum(pop + growth * share, 0.0)
        population = float(pop.sum())

        # -- travel times (car network with current congestion) --------------
        cmask = net.car_mask()
        if len(edge_flow) != len(net.eid):   # network grew last year
            edge_flow = np.pad(edge_flow, (0, len(net.eid) - len(edge_flow)))
        voc_prev = np.divide(edge_flow, net.cap, out=np.zeros_like(edge_flow),
                             where=net.cap > 0)
        w_time = net.t0 * (1 + analytics.BPR_ALPHA * voc_prev ** analytics.BPR_BETA)
        dist_t, _ = _sssp(net, w_time, zsrc, cmask)            # seconds
        dist_len, pred_len = _sssp(net, net.length, zsrc, None)  # metres, all modes
        tt_car = dist_t[:, zsrc] / 60.0                        # min, ZxZ
        dd = dist_len[:, zsrc]                                 # metres, ZxZ
        tt_walk = dd / MODE_SPEEDS["walk"] / 60.0
        bike_speedup = 1.0 + 0.02 * p["bike_invest"] * y
        tt_bike = dd / (MODE_SPEEDS["bike"] * bike_speedup) / 60.0
        wait = max(3.0, 9.0 - 0.25 * p["transit_invest"] * y)
        tt_transit = tt_car * 1.35 + wait

        big = ~np.isfinite(tt_car)
        for m in (tt_car, tt_walk, tt_bike, tt_transit):
            m[~np.isfinite(m)] = 999.0

        # -- 2. gravity distribution -----------------------------------------
        P_i = pop * p["trip_rate"] * p["peak_share"]
        imp = np.exp(-beta * np.minimum(tt_car, tt_walk))
        np.fill_diagonal(imp, np.exp(-beta * 3.0))
        A_j = attraction / attraction.sum()
        T = P_i[:, None] * (A_j[None, :] * imp) / \
            np.maximum((A_j[None, :] * imp).sum(axis=1, keepdims=True), 1e-9)

        # -- 3. mode choice ----------------------------------------------------
        asc_car_y = asc["car"] + 0.01 * p["car_ownership_growth_pct"] * y
        asc_tr_y = asc["transit"] + 0.06 * p["transit_invest"] * y
        asc_bk_y = asc["bike"] + 0.05 * p["bike_invest"] * y
        U = {
            "car": asc_car_y + vot * tt_car,
            "transit": asc_tr_y + vot * tt_transit,
            "bike": asc_bk_y + vot * np.minimum(tt_bike, 120),
            "walk": asc["walk"] + vot * np.minimum(tt_walk, 180),
        }
        expU = {m: np.exp(np.clip(u, -30, 30)) for m, u in U.items()}
        denom = sum(expU.values())
        Tm = {m: T * expU[m] / denom for m in expU}
        shares = {m: float(Tm[m].sum() / max(T.sum(), 1e-9)) for m in Tm}

        # -- 4. car assignment (MSA over BPR) ---------------------------------
        Tcar = Tm["car"]
        edge_flow = np.zeros(len(net.eid))
        for it in range(int(p["msa_iters"])):
            w_it = net.t0 * (1 + analytics.BPR_ALPHA *
                             np.divide(edge_flow, net.cap,
                                       out=np.zeros_like(edge_flow),
                                       where=net.cap > 0) ** analytics.BPR_BETA)
            d_it, p_it = _sssp(net, w_it, zsrc, cmask)
            aon = np.zeros(len(net.eid))
            pair_index = _edge_lookup(net)
            for zi in range(Z):
                row = p_it[zi]
                for zj in range(Z):
                    t = Tcar[zi, zj]
                    if t < 0.5 or zi == zj:
                        continue
                    path = _trace(row, int(zsrc[zi]), int(zsrc[zj]))
                    if not path:
                        continue
                    for a, b in zip(path[:-1], path[1:]):
                        k = pair_index.get((a, b))
                        if k is not None:
                            aon[k] += t
            edge_flow = aon if it == 0 else edge_flow + (aon - edge_flow) / (it + 1)

        voc = np.divide(edge_flow, net.cap, out=np.zeros_like(edge_flow),
                        where=net.cap > 0)
        w_fin = net.t0 * (1 + analytics.BPR_ALPHA * voc ** analytics.BPR_BETA)
        v_cong = np.maximum(5.0, (net.length / np.maximum(w_fin, 0.1)) * 3.6)

        # -- 6. indicators -----------------------------------------------------
        vkt = float(np.sum(edge_flow * net.length) / 1000.0)
        vht = float(np.sum(edge_flow * w_fin) / 3600.0)
        co2_kgh = float(np.sum([analytics.co2_gpkm(v_cong[k], p["petrol_share"]) *
                                net.length[k] / 1000.0 * edge_flow[k] / 1000.0
                                for k in range(len(edge_flow)) if edge_flow[k] > 0]))
        # per-edge aggregates (both directions)
        agg_flow, agg_v, agg_len = {}, {}, {}
        for k in range(len(net.eid)):
            e = int(net.eid[k])
            agg_flow[e] = agg_flow.get(e, 0.0) + float(edge_flow[k])
            agg_v[e] = max(agg_v.get(e, 0.0), float(v_cong[k]))
            agg_len[e] = float(net.length[k])
        noise_high_km = sum(l for e, l in agg_len.items()
                            if agg_flow.get(e, 0) > 5 and
                            analytics.noise_db_at_10m(agg_flow[e], agg_v[e]) > 65) / 1000.0
        congested_km = float(np.sum(net.length[voc > 0.9]) / 1000.0) / 2.0
        acc_z = (np.exp(-beta * np.minimum(tt_car, tt_transit)) *
                 attraction[None, :]).sum(axis=1)
        accessibility = float(np.mean(acc_z) / max(attraction.sum(), 1e-9))
        trip_min = float(np.sum(T * np.minimum.reduce(
            [tt_car, tt_transit, tt_bike, tt_walk])) / max(T.sum(), 1e-9))
        network_km = float(np.sum(net.length) / 2000.0)

        # sample agents on THIS year's network (before it evolves)
        agents = _sample_agents(net, zones, Tm, dist_len, pred_len, w_fin,
                                p, nprng)

        # -- 5. network evolution ---------------------------------------------
        deltas = []
        budget = float(p["road_budget"])
        # 5a. capacity upgrades (densification response)
        agg_voc = {}
        for k in range(len(net.eid)):
            e = int(net.eid[k])
            agg_voc[e] = max(agg_voc.get(e, 0.0), float(voc[k]))
        saturated = sorted([e for e, v in agg_voc.items() if v > 1.0 and
                            e not in net.closed_car],
                           key=lambda e: -agg_voc[e] * agg_flow.get(e, 0))
        for e in saturated:
            cost = agg_len[e] / 1000.0 * 0.7
            if cost > budget * 0.6:
                continue
            net.upgrade(e)
            budget -= cost
            up_lanekm += agg_len[e] / 1000.0
            invest_total += cost
            deltas.append({"a": "up", "id": e, "geom": net.geom.get(e),
                           "note": f"lane added (v/c was {agg_voc[e]:.2f})"})
            if budget <= 0.2 or len([d for d in deltas if d['a'] == 'up']) >= 4:
                break
        # 5b. new links (exploration): close in space, far on network
        cand = _link_candidates(net, dist_len, zsrc, nprng)
        for (i, j, eucl, ratio) in cand:
            cost = eucl / 1000.0 * 3.0
            if cost > budget:
                continue
            eid, ln = net.add_link(i, j, 40, 900, 1, "tertiary")
            budget -= cost
            new_km += ln / 1000.0
            invest_total += cost
            deltas.append({"a": "new", "id": eid, "geom": net.geom[eid],
                           "note": f"new link {ln:.0f} m (detour was x{ratio:.1f})"})
            if budget <= 0.3 or len([d for d in deltas if d['a'] == 'new']) >= 3:
                break
        # 5c. pedestrianization of calm, POI-rich streets
        if p["pedestrianization"]:
            calm = [e for e, v in agg_voc.items()
                    if v < 0.25 and e > 0 and e not in net.closed_car and
                    agg_len[e] < 400]
            rng.shuffle(calm)
            for e in calm[:2]:
                if _near_pois(net, region_id, e) < 3:
                    continue
                net.pedestrianize(e)
                ped_km += agg_len[e] / 1000.0
                deltas.append({"a": "ped", "id": e, "geom": net.geom.get(e),
                               "note": "pedestrianized (calm, POI-rich)"})

        metrics = {
            "population": round(population),
            "trips_peak": round(float(T.sum())),
            "share_car": round(shares["car"], 4),
            "share_transit": round(shares["transit"], 4),
            "share_bike": round(shares["bike"], 4),
            "share_walk": round(shares["walk"], 4),
            "vkt": round(vkt, 1), "vht": round(vht, 1),
            "avg_speed": round(vkt / vht, 1) if vht > 0 else None,
            "mean_voc": round(float(np.mean(voc[edge_flow > 0])) if
                              (edge_flow > 0).any() else 0.0, 3),
            "congested_km": round(congested_km, 2),
            "co2_t_day": round(co2_kgh * DAY_EXPANSION / 1000.0, 2),
            "noise_high_km": round(noise_high_km, 2),
            "accessibility": round(accessibility, 4),
            "avg_trip_min": round(trip_min, 1),
            "network_km": round(network_km, 2),
            "new_links_km": round(new_km, 2),
            "upgraded_lane_km": round(up_lanekm, 2),
            "pedestrianized_km": round(ped_km, 2),
            "invest_spent": round(invest_total, 2),
        }
        voc_out = {str(e): round(v, 2) for e, v in agg_voc.items() if v >= 0.35}
        with db.cursor() as cur:
            cur.execute("INSERT OR REPLACE INTO sim_years(run_id,year,metrics,deltas,voc) "
                        "VALUES(?,?,?,?,?)",
                        (run_id, y, db.j(metrics), db.j(deltas), db.j(voc_out)))
            cur.execute("INSERT OR REPLACE INTO sim_agents(run_id,year,agents) "
                        "VALUES(?,?,?)", (run_id, y, db.j(agents)))


def _edge_lookup(net):
    return {(int(net.eu[k]), int(net.ev[k])): k for k in range(len(net.eu))}


_poi_cache = {}


def _near_pois(net, region_id, eid):
    pts = _poi_cache.get(region_id)
    if pts is None:
        with db.cursor() as cur:
            cur.execute("SELECT lon,lat FROM points_of_interest WHERE region_id=? "
                        "AND lon IS NOT NULL", (region_id,))
            pts = [(r["lon"], r["lat"]) for r in cur.fetchall()]
        _poi_cache[region_id] = pts
    g = net.geom.get(eid) or []
    if not g:
        return 0
    mid = g[len(g) // 2]
    r2 = (150.0 / net.mlat) ** 2
    return sum(1 for (lo, la) in pts
               if (lo - mid[0]) ** 2 * (net.mlon / net.mlat) ** 2 +
               (la - mid[1]) ** 2 <= r2 * 4)


def _link_candidates(net, dist_len, zsrc, nprng, max_out=6):
    """Node pairs close in space but far on the network (detour ratio)."""
    n = net.n
    sample = nprng.choice(n, size=min(300, n), replace=False)
    out = []
    for i in sample[:150]:
        d2 = ((net.lon - net.lon[i]) * net.mlon) ** 2 + \
             ((net.lat - net.lat[i]) * net.mlat) ** 2
        near = np.where((d2 > 120 ** 2) & (d2 < 450 ** 2))[0]
        if not len(near):
            continue
        j = int(near[nprng.integers(len(near))])
        eucl = float(math.sqrt(d2[j]))
        # network distance upper bound via zone centroids
        bound = float(np.min(dist_len[:, i] + dist_len[:, j]))
        if not math.isfinite(bound):
            ratio = 9.9
        else:
            ratio = bound / max(eucl, 1.0)
        if ratio > 2.5:
            out.append((int(i), j, eucl, min(ratio, 9.9)))
    out.sort(key=lambda c: -c[3])
    return out[:max_out]


# ---------------------------------------------------------------------------
# Agent trajectory sampling for the animation layer
# ---------------------------------------------------------------------------
def _sample_agents(net, zones, Tm, dist_len, pred_len, w_car, p, nprng):
    zsrc = zones["nodes"]
    Z = len(zsrc)
    modes = ["car", "transit", "bike", "walk"]
    weights = np.array([max(Tm[m].sum(), 0.0) for m in modes])
    if weights.sum() <= 0:
        return []
    n_agents = int(p["agents_sample"])
    counts = nprng.multinomial(n_agents, weights / weights.sum())
    pair_index = _edge_lookup(net)
    agents = []
    for mi, mode in enumerate(modes):
        M = Tm[mode]
        flat = M.flatten()
        tot = flat.sum()
        if tot <= 0 or counts[mi] == 0:
            continue
        picks = nprng.choice(len(flat), size=counts[mi], p=flat / tot)
        for od in picks:
            zi, zj = divmod(int(od), Z)
            if zi == zj:
                continue
            path = _trace(pred_len[zi], int(zsrc[zi]), int(zsrc[zj]))
            if not path or len(path) < 2:
                continue
            coords, times = _path_geometry(net, path, mode, w_car, pair_index)
            if len(coords) < 2:
                continue
            dep = _departure_sec(nprng)
            agents.append({"m": mode, "d": int(dep),
                           "p": [[round(c[0], 5), round(c[1], 5)] for c in coords],
                           "t": [round(t, 1) for t in times]})
    return agents


def _departure_sec(nprng):
    r = nprng.random()
    if r < 0.5:
        h = nprng.normal(8.0, 0.75)          # morning peak
    elif r < 0.85:
        h = nprng.normal(17.2, 0.85)         # evening peak
    else:
        h = nprng.uniform(6.0, 21.5)
    return min(max(h, 5.5), 22.5) * 3600


def _path_geometry(net, path, mode, w_car, pair_index, max_pts=70):
    coords, times = [], []
    t_acc = 0.0
    bike_v, walk_v = MODE_SPEEDS["bike"], MODE_SPEEDS["walk"]
    for a, b in zip(path[:-1], path[1:]):
        k = pair_index.get((a, b))
        if k is None:
            k = pair_index.get((b, a))
        if k is not None and k >= len(w_car):
            k = None                       # edge newer than cost vector
        seg = net.geom.get(int(net.eid[k]), []) if k is not None else []
        if k is None or not seg:
            seg = [[float(net.lon[a]), float(net.lat[a])],
                   [float(net.lon[b]), float(net.lat[b])]]
        # orient segment
        pa = [float(net.lon[a]), float(net.lat[a])]
        if abs(seg[0][0] - pa[0]) + abs(seg[0][1] - pa[1]) > \
           abs(seg[-1][0] - pa[0]) + abs(seg[-1][1] - pa[1]):
            seg = seg[::-1]
        if k is not None:
            length = float(net.length[k])
            if mode == "car":
                dur = float(w_car[k])
            elif mode == "transit":
                dur = float(w_car[k]) * 1.35
            elif mode == "bike":
                dur = length / bike_v
            else:
                dur = length / walk_v
        else:
            length = 10.0; dur = 10.0
        seglen = [math.hypot((seg[i+1][0]-seg[i][0]) * net.mlon,
                             (seg[i+1][1]-seg[i][1]) * net.mlat)
                  for i in range(len(seg)-1)]
        stotal = sum(seglen) or 1.0
        if not coords:
            coords.append(seg[0]); times.append(t_acc)
        for i in range(1, len(seg)):
            t_acc += dur * (seglen[i-1] / stotal)
            coords.append(seg[i]); times.append(t_acc)
    # downsample keeping first/last
    if len(coords) > max_pts:
        idxs = np.linspace(0, len(coords) - 1, max_pts).astype(int)
        coords = [coords[i] for i in idxs]
        times = [times[i] for i in idxs]
    return coords, times
