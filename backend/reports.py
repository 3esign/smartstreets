"""Report + export generation: CSV and self-contained printable HTML."""

import csv
import io
import datetime

from . import database as db


def street_csv(region_id):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["edge_id", "name", "highway", "length_m", "oneway", "maxspeed",
                "betweenness", "closeness", "modeled_flow", "co2_emissions",
                "noise_db", "street_iq", "completeness"])
    with db.cursor() as cur:
        cur.execute(
            "SELECT e.id,e.name,e.highway,e.length,e.oneway,e.maxspeed,"
            "a.betweenness,a.closeness,a.modeled_flow,a.co2_emissions,a.noise_db,"
            "a.street_iq,a.completeness FROM street_edges e "
            "LEFT JOIN street_analytics a ON a.edge_id=e.id WHERE e.region_id=?",
            (region_id,))
        for r in cur.fetchall():
            w.writerow([r["id"], r["name"], r["highway"], round(r["length"] or 0, 1),
                        r["oneway"], r["maxspeed"], _r(r["betweenness"]), _r(r["closeness"]),
                        _r(r["modeled_flow"]), _r(r["co2_emissions"]), _r(r["noise_db"]),
                        _r(r["street_iq"]), _r(r["completeness"])])
    return buf.getvalue()


def _r(v, n=4):
    return round(v, n) if isinstance(v, float) else v


def _stats(region_id):
    with db.cursor() as cur:
        s = {}
        for label, table in [("Street edges", "street_edges"), ("Intersections", "network_nodes"),
                             ("Pedestrian paths", "pedestrian_edges"), ("Cycling edges", "cycling_edges"),
                             ("Transit routes", "transit_routes"), ("Transit stops", "transit_stops"),
                             ("POIs", "points_of_interest"), ("Buildings", "building_footprints")]:
            cur.execute(f"SELECT COUNT(*) c FROM {table} WHERE region_id=?", (region_id,))
            s[label] = cur.fetchone()["c"]
        cur.execute("SELECT COALESCE(SUM(length),0) l FROM street_edges WHERE region_id=?", (region_id,))
        s["Total road length (km)"] = round((cur.fetchone()["l"] or 0) / 1000.0, 2)
        cur.execute("SELECT AVG(street_iq) iq,AVG(co2_emissions) co2,AVG(noise_db) noise,"
                    "AVG(completeness) comp FROM street_analytics WHERE edge_id IN "
                    "(SELECT id FROM street_edges WHERE region_id=?)", (region_id,))
        a = cur.fetchone()
        s["Avg StreetIQ"] = _r(a["iq"], 3)
        s["Avg CO2 (g/edge)"] = _r(a["co2"], 1)
        s["Avg noise (dB)"] = _r(a["noise"], 1)
        s["Data completeness"] = f"{round((a['comp'] or 0) * 100)}%"
    return s


def _top_edges(region_id, metric, n=10, asc=False):
    order = "ASC" if asc else "DESC"
    with db.cursor() as cur:
        cur.execute(
            f"SELECT e.name,e.highway,a.{metric} v FROM street_edges e "
            f"JOIN street_analytics a ON a.edge_id=e.id WHERE e.region_id=? AND a.{metric} IS NOT NULL "
            f"ORDER BY a.{metric} {order} LIMIT ?", (region_id, n))
        return [(r["name"] or "(unnamed)", r["highway"], _r(r["v"], 3)) for r in cur.fetchall()]


def html_report(region_id, project_name="SmartStreet Project"):
    stats = _stats(region_id)
    bottlenecks = _top_edges(region_id, "street_iq", 10)
    worst_co2 = _top_edges(region_id, "co2_emissions", 10)
    with db.cursor() as cur:
        cur.execute("SELECT category,COUNT(*) c,AVG(impact_score) s FROM actionable_decisions "
                    "WHERE region_id=? GROUP BY category", (region_id,))
        decisions = [(r["category"], r["c"], _r(r["s"], 2)) for r in cur.fetchall()]

    def table(rows, headers):
        head = "".join(f"<th>{h}</th>" for h in headers)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    stat_rows = "".join(f"<tr><td>{k}</td><td class='v'>{v}</td></tr>" for k, v in stats.items())
    dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{project_name} — Report</title>
<style>
 @page {{ size: A4; margin: 18mm; }}
 body {{ font-family: system-ui, Arial, sans-serif; color: #1a2733; max-width: 800px; margin: 0 auto; padding: 24px; }}
 h1 {{ color: #2d7fd6; margin-bottom: 4px; }} h2 {{ color: #2d7fd6; border-bottom: 2px solid #e2e8f0; padding-bottom: 4px; margin-top: 28px; }}
 .sub {{ color: #64748b; margin-top: 0; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }}
 th, td {{ border: 1px solid #e2e8f0; padding: 6px 9px; text-align: left; }}
 th {{ background: #f1f5f9; }} td.v {{ text-align: right; font-weight: 600; }}
 .foot {{ margin-top: 32px; color: #94a3b8; font-size: 11px; border-top: 1px solid #e2e8f0; padding-top: 8px; }}
 @media print {{ .noprint {{ display: none; }} }}
 .btn {{ background: #2d7fd6; color: #fff; border: none; padding: 8px 14px; border-radius: 6px; cursor: pointer; }}
</style></head><body>
<button class="btn noprint" onclick="window.print()">Print / Save as PDF</button>
<h1>Network Intelligence Report</h1>
<p class="sub">{project_name} — generated {dt}</p>
<h2>1. Region Summary</h2>
<table><tbody>{stat_rows}</tbody></table>
<h2>2. Top Critical Streets (StreetIQ)</h2>
{table(bottlenecks, ["Street", "Class", "StreetIQ"])}
<h2>3. Highest CO₂ Streets</h2>
{table(worst_co2, ["Street", "Class", "CO₂"])}
<h2>4. Optimization Recommendations</h2>
{table(decisions, ["Category", "Count", "Avg impact"]) if decisions else "<p class='sub'>Run the optimization engine to populate recommendations.</p>"}
<div class="foot">SmartStreet — open-data street & road intelligence. Modeled flows are relative
screening indicators, not calibrated forecasts.</div>
</body></html>"""
