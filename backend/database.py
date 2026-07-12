"""SQLite database layer for SmartStreet.

Uses the Python stdlib sqlite3 (no SpatiaLite dependency for zero-friction
local setup). Geometries are stored as JSON coordinate arrays; spatial math is
done in-process with Shapely / NetworkX. This mirrors the ARCHITECTURE.md
3-tier schema in a simplified, fully-runnable form.
"""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get(
    "SMARTSTREET_DB",
    os.path.join(os.path.dirname(__file__), "..", "smartstreet.db"),
)
DB_PATH = os.path.abspath(DB_PATH)

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    """One connection per thread (FastAPI runs handlers across a threadpool)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # WAL is faster but unsupported on some network/FUSE filesystems; fall back.
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            conn.execute("PRAGMA journal_mode=DELETE;")
        conn.execute("PRAGMA foreign_keys=ON;")
        _local.conn = conn
    return conn


@contextmanager
def cursor():
    conn = get_conn()
    cur = conn.cursor()
    try:
        yield cur
        conn.commit()
    finally:
        cur.close()


SCHEMA = """
-- Tier 1: raw
CREATE TABLE IF NOT EXISTS regions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    bbox TEXT NOT NULL,               -- JSON [w,s,e,n]
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    center_lat REAL, center_lon REAL, zoom_level REAL,
    bbox TEXT,                        -- JSON [w,s,e,n]
    layer_state TEXT DEFAULT '{}',    -- JSON
    detail_tier TEXT DEFAULT 'A',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS network_nodes (
    id INTEGER PRIMARY KEY,           -- OSM node id
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    lon REAL NOT NULL, lat REAL NOT NULL,
    degree INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_nodes_region ON network_nodes(region_id);

CREATE TABLE IF NOT EXISTS street_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    source_node INTEGER, target_node INTEGER,
    highway TEXT, name TEXT,
    lanes INTEGER, oneway INTEGER DEFAULT 0,
    maxspeed INTEGER, surface TEXT, width REAL, length REAL,
    geom TEXT NOT NULL                -- JSON [[lon,lat],...]
);
CREATE INDEX IF NOT EXISTS idx_edges_region ON street_edges(region_id);

CREATE TABLE IF NOT EXISTS pedestrian_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    type TEXT, surface TEXT, lit INTEGER, geom TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ped_region ON pedestrian_edges(region_id);

CREATE TABLE IF NOT EXISTS cycling_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    type TEXT, surface TEXT, oneway INTEGER DEFAULT 0, geom TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cyc_region ON cycling_edges(region_id);

CREATE TABLE IF NOT EXISTS transit_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    name TEXT, mode TEXT, operator TEXT, geom TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_troute_region ON transit_routes(region_id);

CREATE TABLE IF NOT EXISTS transit_stops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    name TEXT, mode TEXT, lon REAL, lat REAL
);
CREATE INDEX IF NOT EXISTS idx_tstop_region ON transit_stops(region_id);

CREATE TABLE IF NOT EXISTS points_of_interest (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    category TEXT, name TEXT, lon REAL, lat REAL
);
CREATE INDEX IF NOT EXISTS idx_poi_region ON points_of_interest(region_id);

CREATE TABLE IF NOT EXISTS building_footprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    osm_id INTEGER, region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    building_type TEXT, levels INTEGER, height REAL, geom TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bld_region ON building_footprints(region_id);

-- Tier 2: analytics (per edge)
CREATE TABLE IF NOT EXISTS street_analytics (
    edge_id INTEGER PRIMARY KEY REFERENCES street_edges(id) ON DELETE CASCADE,
    betweenness REAL, closeness REAL,
    modeled_flow REAL, co2_emissions REAL, noise_db REAL,
    street_iq REAL,
    completeness REAL           -- data quality 0..1
);

CREATE TABLE IF NOT EXISTS pedestrian_analytics (
    edge_id INTEGER PRIMARY KEY REFERENCES pedestrian_edges(id) ON DELETE CASCADE,
    walkability REAL, safety REAL, connectivity REAL
);

CREATE TABLE IF NOT EXISTS cycling_analytics (
    edge_id INTEGER PRIMARY KEY REFERENCES cycling_edges(id) ON DELETE CASCADE,
    lts INTEGER, bikeability REAL
);

-- Tier 2: isochrones
CREATE TABLE IF NOT EXISTS isochrone_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    mode TEXT, travel_minutes INTEGER,
    origin_lon REAL, origin_lat REAL,
    geom TEXT NOT NULL,          -- JSON polygon coords
    reachable_nodes INTEGER
);

-- Named, user-saved isochrones (bands stored together as one save)
CREATE TABLE IF NOT EXISTS isochrone_saves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    mode TEXT,
    origin_lon REAL, origin_lat REAL,
    bands TEXT NOT NULL,         -- JSON [{minutes, reachable_nodes, coords}]
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_isosave_region ON isochrone_saves(region_id);

-- Tier 3: multi-year agent simulation
CREATE TABLE IF NOT EXISTS sim_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    name TEXT,
    params TEXT NOT NULL,        -- JSON simulation parameters
    status TEXT DEFAULT 'queued',-- queued|running|done|error
    progress REAL DEFAULT 0,     -- 0..1
    message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_simrun_project ON sim_runs(project_id);

CREATE TABLE IF NOT EXISTS sim_years (
    run_id INTEGER REFERENCES sim_runs(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    metrics TEXT NOT NULL,       -- JSON aggregate indicators for the year
    deltas TEXT,                 -- JSON network changes made this year
    voc TEXT,                    -- JSON {edge_id: v/c} for congested edges
    PRIMARY KEY (run_id, year)
);

CREATE TABLE IF NOT EXISTS sim_agents (
    run_id INTEGER REFERENCES sim_runs(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    agents TEXT NOT NULL,        -- JSON sampled agent trajectories
    PRIMARY KEY (run_id, year)
);

-- Tier 3: scenarios & decisions
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scenario_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER REFERENCES scenarios(id) ON DELETE CASCADE,
    sequence_number INTEGER NOT NULL,
    target_id INTEGER,                  -- street_edges.id
    action_type TEXT,                   -- 'closure','direction_change','attribute_change'
    attribute_overrides TEXT,           -- JSON
    active INTEGER DEFAULT 1            -- for undo/redo
);

CREATE TABLE IF NOT EXISTS actionable_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
    category TEXT,                      -- 'signalization','new_link','direction_change'
    geom TEXT,                          -- JSON (point or line)
    impact_score REAL,
    confidence TEXT,
    rationale TEXT,
    props TEXT                          -- JSON extra fields
);
"""


def _migrate(conn):
    """Add columns introduced after the first release to existing databases."""
    migrations = [
        ("street_analytics", "completeness", "REAL"),
        ("street_analytics", "voc", "REAL"),              # volume/capacity ratio
        ("street_analytics", "congested_speed", "REAL"),  # km/h after BPR delay
    ]
    for table, col, coltype in migrations:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if cols and col not in cols:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except sqlite3.OperationalError:
                pass


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


# ---- small helpers -------------------------------------------------------

def j(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def unj(text, default=None):
    if text is None:
        return default
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default
