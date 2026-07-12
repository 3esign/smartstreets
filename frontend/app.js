/* SmartStreet dashboard — MapLibre + vanilla JS */
// API base: same-origin by default (local / single-service deploy).
// For a split deploy (frontend on Vercel), set window.SMARTSTREET_API in config.js.
const API = (window.SMARTSTREET_API || "").replace(/\/+$/, "");
let map, currentProject = null, currentRegion = null, drawing = false, drawPts = [];
let isMouseDown = false, dragStarted = false, startPt = null;
let streetsData = null, histChart = null, radarChart = null, compareChart = null;
let mapMode = null, currentScenario = "", editTargetId = null;

const RASTER_STYLES = {
  vector: {
    version: 8,
    sources: {
      osm: { type: "raster", tiles: ["https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png"], tileSize: 256, attribution: "© OpenStreetMap" },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  },
  satellite: {
    version: 8,
    sources: {
      sat: { type: "raster", tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
        tileSize: 256, attribution: "© Esri" },
    },
    layers: [{ id: "sat", type: "raster", source: "sat" }],
  },
};

const COLORS = ["#2ecc71", "#a3d94b", "#f1c40f", "#e67e22", "#e74c3c"]; // low→high
const HIGHWAY_COLORS = {
  motorway: "#e74c3c", trunk: "#e67e22", primary: "#f39c12", secondary: "#f1c40f",
  tertiary: "#9bd44b", residential: "#4da3ff", service: "#8595a5", living_street: "#7ee0c8",
};

// ---------- helpers ----------
const $ = (id) => document.getElementById(id);
function status(msg) { $("statusMsg").textContent = msg || ""; }
function spinner(on, text) { $("spinText").textContent = text || "Working…"; $("spinner").classList.toggle("hidden", !on); }
async function api(path, opts) {
  const r = await fetch(API + path, opts);
  if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "Request failed"); }
  return r.json();
}

// ---------- map init ----------
function initMap() {
  map = new maplibregl.Map({
    container: "map", style: RASTER_STYLES.vector,
    center: [14.5, 46.05], zoom: 12,
  });
  map.addControl(new maplibregl.NavigationControl(), "top-left");
  map.on("click", onMapClick);
  map.on("mousedown", onMapMouseDown);
  map.on("mousemove", onMapMouseMove);
  map.on("mouseup", onMapMouseUp);
  map.on("load", loadProjects);
}

$("basemap").addEventListener("change", (e) => {
  const wasRegion = currentRegion;
  map.setStyle(RASTER_STYLES[e.target.value]);
  map.once("styledata", () => { if (wasRegion) renderRegion(wasRegion, false); if (drawPts.length) drawBoxPreview(); });
});

// ---------- bbox drawing ----------
$("newProjectBtn").addEventListener("click", startDraw);
$("cancelDraw").addEventListener("click", cancelDraw);
function startDraw() {
  drawing = true; drawPts = [];
  isMouseDown = false; dragStarted = false; startPt = null;
  if (map && map.dragPan) map.dragPan.disable();
  $("drawHint").classList.remove("hidden");
  $("areaReadout").textContent = "";
  map.getCanvas().style.cursor = "crosshair";
}
function cancelDraw() {
  drawing = false; drawPts = [];
  isMouseDown = false; dragStarted = false; startPt = null;
  if (map && map.dragPan) map.dragPan.enable();
  $("drawHint").classList.add("hidden");
  map.getCanvas().style.cursor = "";
  removeLayer("bbox-fill"); removeLayer("bbox-line"); removeSource("bbox");
}
function onMapMouseDown(e) {
  if (!drawing) return;
  isMouseDown = true;
  dragStarted = false;
  startPt = e.lngLat;
}
function onMapMouseMove(e) {
  if (!drawing) return;
  if (isMouseDown) {
    dragStarted = true;
    drawPts = [[startPt.lng, startPt.lat], [e.lngLat.lng, e.lngLat.lat]];
    drawBoxPreview();
    const area = bboxAreaKm2(bboxFromPts());
    $("areaReadout").textContent = ` Live: ${area.toFixed(2)} km²`;
  } else if (drawPts.length === 1) {
    drawBoxPreview([e.lngLat.lng, e.lngLat.lat]);
    const a = drawPts[0];
    const b = [e.lngLat.lng, e.lngLat.lat];
    const area = bboxAreaKm2([Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])]);
    $("areaReadout").textContent = ` Live: ${area.toFixed(2)} km²`;
  }
}
function onMapMouseUp(e) {
  if (!drawing || !isMouseDown) return;
  isMouseDown = false;
  if (dragStarted) {
    drawPts = [[startPt.lng, startPt.lat], [e.lngLat.lng, e.lngLat.lat]];
    drawBoxPreview();
    finishDraw();
  }
}
function onMapClick(e) {
  if (drawing) {
    if (dragStarted) return;
    drawPts.push([e.lngLat.lng, e.lngLat.lat]);
    if (drawPts.length === 1) {
      // Draw single point representation or wait for move
    } else if (drawPts.length === 2) {
      drawBoxPreview();
      finishDraw();
    }
    return;
  }
  if (mapMode === "iso") { runIsochrone(e.lngLat); return; }
  // edit mode handled by the streets-line click handler (needs feature)
}
function bboxFromPts() {
  const [a, b] = drawPts;
  return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
}
function drawBoxPreview(tempPt = null) {
  let pts = [...drawPts];
  if (tempPt) pts.push(tempPt);
  if (pts.length < 2) return;
  
  const [a, b] = pts;
  const w = Math.min(a[0], b[0]);
  const s = Math.min(a[1], b[1]);
  const e = Math.max(a[0], b[0]);
  const n = Math.max(a[1], b[1]);

  const poly = { type: "Feature", geometry: { type: "Polygon", coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]] } };
  if (map.getSource("bbox")) map.getSource("bbox").setData(poly);
  else {
    map.addSource("bbox", { type: "geojson", data: poly });
    map.addLayer({ id: "bbox-fill", type: "fill", source: "bbox", paint: { "fill-color": "#4da3ff", "fill-opacity": 0.12 } });
    map.addLayer({ id: "bbox-line", type: "line", source: "bbox", paint: { "line-color": "#4da3ff", "line-width": 2 } });
  }
}
function finishDraw() {
  drawing = false;
  isMouseDown = false; dragStarted = false; startPt = null;
  if (map && map.dragPan) map.dragPan.enable();
  map.getCanvas().style.cursor = "";
  const area = bboxAreaKm2(bboxFromPts());
  $("areaReadout").textContent = ` ${area.toFixed(2)} km²`;
  $("modalArea").textContent = `Bounding box area: ${area.toFixed(2)} km² (tier ${tierFor(area)})`;
  $("projInput").value = "";
  $("modal").classList.remove("hidden");
}
function bboxAreaKm2([w, s, e, n]) {
  const mid = (s + n) / 2 * Math.PI / 180;
  return Math.abs((n - s) * 110.574) * Math.abs((e - w) * 111.320 * Math.cos(mid));
}
function tierFor(a) { return a <= 5 ? "A" : a <= 15 ? "B" : "C"; }

// ---------- create project ----------
$("modalCancel").addEventListener("click", () => { $("modal").classList.add("hidden"); cancelDraw(); });
$("modalCreate").addEventListener("click", createProject);
async function createProject() {
  const name = $("projInput").value.trim() || "Untitled";
  const bbox = bboxFromPts();
  $("modal").classList.add("hidden");
  spinner(true, "Fetching OSM data & computing analytics…");
  try {
    const res = await api("/api/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, bbox }),
    });
    cancelDraw();
    await loadProjects();
    await loadProject(res.project_id);
    status(`Created "${name}" — ${res.counts.streets} streets, ${res.counts.nodes} nodes`);
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
}

// ---------- projects list ----------
async function loadProjects() {
  const projects = await api("/api/projects");
  const list = $("projectList");
  list.innerHTML = projects.length ? "" : '<div class="muted">No projects yet.</div>';
  projects.forEach((p) => {
    const el = document.createElement("div");
    el.className = "proj-item" + (currentProject && currentProject.id === p.id ? " active" : "");
    el.innerHTML = `<div><div>${p.name}</div><div class="meta">tier ${p.detail_tier} · #${p.id}</div></div>
      <span class="del" title="Delete">✕</span>`;
    el.addEventListener("click", (ev) => { if (ev.target.classList.contains("del")) return; loadProject(p.id); });
    el.querySelector(".del").addEventListener("click", (ev) => { ev.stopPropagation(); deleteProject(p.id, p.name); });
    list.appendChild(el);
  });
}
async function deleteProject(id, name) {
  if (!confirm(`Delete project "${name}"?`)) return;
  await api(`/api/projects/${id}`, { method: "DELETE" });
  if (currentProject && currentProject.id === id) { currentProject = null; currentRegion = null; }
  await loadProjects();
}

// ---------- load & render a project ----------
async function loadProject(id) {
  spinner(true, "Loading project…");
  try {
    const proj = await api(`/api/projects/${id}`);
    currentProject = proj; currentRegion = proj.region_id;
    $("projectLabel").textContent = proj.name;
    const wel = $("welcome"); if (wel) wel.classList.add("hidden");
    if (proj.layer_state) applyLayerState(proj.layer_state);
    await renderRegion(proj.region_id, true);
    updateStats(proj.stats);
    await loadHistogram();
    loadRadar(proj.stats);
    await loadScenarios();
    await loadDecisions();
    await loadProjects();
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
}

function applyLayerState(s) {
  const map = { streets: "ly_streets", pedestrian: "ly_pedestrian", cycling: "ly_cycling",
    transit: "ly_transit", pois: "ly_pois", buildings: "ly_buildings" };
  Object.entries(map).forEach(([k, id]) => { if (s[k] !== undefined) $(id).checked = !!s[k]; });
}

const LAYER_IDS = ["buildings-fill", "streets-line", "ped-line", "cyc-line",
  "transit-line", "tstops-pt", "pois-pt"];
function removeLayer(id) { if (map.getLayer(id)) map.removeLayer(id); }
function removeSource(id) { if (map.getSource(id)) map.removeSource(id); }

async function renderRegion(regionId, fit) {
  LAYER_IDS.forEach(removeLayer);
  ["buildings", "streets", "ped", "cyc", "transit", "tstops", "pois"].forEach(removeSource);

  const slot = $("timeSlot").value;
  const [streets, ped, cyc, transit, tstops, pois, buildings] = await Promise.all([
    api(`/api/regions/${regionId}/layers/streets?time_slot=${slot}`),
    api(`/api/regions/${regionId}/layers/pedestrian`),
    api(`/api/regions/${regionId}/layers/cycling`),
    api(`/api/regions/${regionId}/layers/transit`),
    api(`/api/regions/${regionId}/layers/transit_stops`),
    api(`/api/regions/${regionId}/layers/pois`),
    api(`/api/regions/${regionId}/layers/buildings`),
  ]);
  streetsData = streets;

  map.addSource("buildings", { type: "geojson", data: buildings });
  map.addLayer({ id: "buildings-fill", type: "fill", source: "buildings",
    paint: { "fill-color": "#3a4a5c", "fill-opacity": 0.5, "fill-outline-color": "#4a5a6c" } });

  map.addSource("transit", { type: "geojson", data: transit });
  map.addLayer({ id: "transit-line", type: "line", source: "transit",
    paint: { "line-color": ["match", ["get", "mode"], "tram", "#e74c3c", "subway", "#9b59b6",
      "train", "#16a085", "light_rail", "#16a085", "#3498db"], "line-width": 2, "line-opacity": 0.85 } });

  map.addSource("ped", { type: "geojson", data: ped });
  map.addLayer({ id: "ped-line", type: "line", source: "ped",
    paint: { "line-color": ["interpolate", ["linear"], ["coalesce", ["get", "walkability"], 0.5],
      0, "#e74c3c", 0.5, "#f1c40f", 1, "#2ecc71"],
      "line-width": 1.6, "line-dasharray": [2, 2], "line-opacity": 0.8 } });

  map.addSource("cyc", { type: "geojson", data: cyc });
  map.addLayer({ id: "cyc-line", type: "line", source: "cyc",
    paint: { "line-color": ["match", ["get", "lts"], 1, "#2ecc71", 2, "#a3d94b",
      3, "#e67e22", 4, "#e74c3c", "#b07ee0"],
      "line-width": 1.8, "line-dasharray": [1, 1.5], "line-opacity": 0.9 } });

  map.addSource("streets", { type: "geojson", data: streets });
  map.addLayer({ id: "streets-line", type: "line", source: "streets",
    paint: { "line-color": "#4da3ff", "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 16, 3.5] } });

  map.addSource("tstops", { type: "geojson", data: tstops });
  map.addLayer({ id: "tstops-pt", type: "circle", source: "tstops",
    paint: { "circle-radius": 3.5, "circle-color": "#3498db", "circle-stroke-color": "#fff", "circle-stroke-width": 1 } });

  map.addSource("pois", { type: "geojson", data: pois });
  map.addLayer({ id: "pois-pt", type: "circle", source: "pois",
    paint: { "circle-radius": 3, "circle-color": ["match", ["get", "category"],
      "school", "#f1c40f", "hospital", "#e74c3c", "pharmacy", "#2ecc71", "park", "#27ae60",
      "restaurant", "#e67e22", "cafe", "#d35400", "shop", "#9b59b6", "#95a5a6"],
      "circle-stroke-color": "#000", "circle-stroke-width": 0.5 } });

  applyColorBy();
  applyLayerVisibility();
  bindPopups();

  if (fit && streets.features.length) {
    const b = new maplibregl.LngLatBounds();
    streets.features.forEach((f) => f.geometry.coordinates.forEach((c) => b.extend(c)));
    if (!b.isEmpty()) map.fitBounds(b, { padding: 40 });
  }
}

// ---------- color by metric ----------
$("colorBy").addEventListener("change", () => { applyColorBy(); });
function applyColorBy() {
  if (!map.getLayer("streets-line") || !streetsData) return;
  const metric = $("colorBy").value;
  if (metric === "highway") {
    map.setPaintProperty("streets-line", "line-color",
      ["match", ["get", "highway"], ...Object.entries(HIGHWAY_COLORS).flat(), "#4da3ff"]);
    renderLegend("highway");
    return;
  }
  const vals = streetsData.features.map((f) => f.properties[metric]).filter((v) => v != null);
  if (!vals.length) { map.setPaintProperty("streets-line", "line-color", "#4da3ff"); renderLegend(null); return; }
  const sorted = [...vals].sort((a, b) => a - b);
  const q = (p) => sorted[Math.floor(p * (sorted.length - 1))];
  const stops = [q(0.1), q(0.3), q(0.5), q(0.7), q(0.9)];
  // dedupe monotonic
  for (let i = 1; i < stops.length; i++) if (stops[i] <= stops[i - 1]) stops[i] = stops[i - 1] + 1e-6;
  const expr = ["interpolate", ["linear"], ["coalesce", ["get", metric], stops[0]]];
  stops.forEach((s, i) => expr.push(s, COLORS[i]));
  map.setPaintProperty("streets-line", "line-color", expr);
  renderLegend(metric, stops);
}
function renderLegend(metric, stops) {
  const el = $("legend");
  if (!metric) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  if (metric === "highway") {
    el.innerHTML = '<div class="title">Road class</div>' +
      Object.entries(HIGHWAY_COLORS).map(([k, c]) => `<div class="row"><span class="sw" style="background:${c}"></span>${k}</div>`).join("");
    return;
  }
  const labels = ["low", "", "mid", "", "high"];
  el.innerHTML = `<div class="title">${metric.replace(/_/g, " ")}</div>` +
    COLORS.map((c, i) => `<div class="row"><span class="sw" style="background:${c}"></span>${stops ? stops[i].toFixed(2) : labels[i]}</div>`).join("");
}

// ---------- layer visibility ----------
const VIS = { ly_streets: "streets-line", ly_pedestrian: "ped-line", ly_cycling: "cyc-line",
  ly_transit: ["transit-line"], ly_transit_stops: "tstops-pt", ly_pois: "pois-pt", ly_buildings: "buildings-fill" };
Object.keys(VIS).forEach((id) => $(id).addEventListener("change", () => { applyLayerVisibility(); saveLayerState(); }));
function applyLayerVisibility() {
  Object.entries(VIS).forEach(([chk, layers]) => {
    const vis = $(chk).checked ? "visible" : "none";
    (Array.isArray(layers) ? layers : [layers]).forEach((l) => { if (map.getLayer(l)) map.setLayoutProperty(l, "visibility", vis); });
  });
}
async function saveLayerState() {
  if (!currentProject) return;
  const s = { streets: $("ly_streets").checked, pedestrian: $("ly_pedestrian").checked,
    cycling: $("ly_cycling").checked, transit: $("ly_transit").checked,
    pois: $("ly_pois").checked, buildings: $("ly_buildings").checked };
  api(`/api/projects/${currentProject.id}/layers`, { method: "PUT",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ layer_state: s }) }).catch(() => {});
}

// ---------- popups ----------
function bindPopups() {
  const popup = new maplibregl.Popup({ closeButton: false });
  const bind = (layer, fmt) => {
    map.on("click", layer, (e) => {
      const p = e.features[0].properties;
      if (layer === "streets-line" && mapMode === "edit") { openEditModal(p); return; }
      popup.setLngLat(e.lngLat).setHTML(fmt(p)).addTo(map);
    });
    map.on("mouseenter", layer, () => map.getCanvas().style.cursor = "pointer");
    map.on("mouseleave", layer, () => map.getCanvas().style.cursor = "");
  };
  bind("streets-line", (p) => `<b>${p.name || "Unnamed street"}</b><br>class: ${p.highway}<br>
    length: ${p.length} m · ${p.oneway == 1 ? "one-way" : "two-way"}<br>
    StreetIQ: ${fmt(p.street_iq)} · betweenness: ${fmt(p.betweenness)}<br>
    CO₂: ${fmt(p.co2_emissions)} · noise: ${fmt(p.noise_db)} dB · quality: ${p.completeness != null ? Math.round(p.completeness * 100) + "%" : "—"}`);
  bind("pois-pt", (p) => `<b>${p.name || p.category}</b><br>${p.category}`);
  bind("tstops-pt", (p) => `<b>${p.name || "Stop"}</b><br>${p.mode}`);
  bind("transit-line", (p) => `<b>${p.name || "Route"}</b><br>${p.mode}`);
}
function fmt(v) { return v == null ? "—" : (typeof v === "number" ? v.toFixed(2) : v); }

// ---------- stats + histogram ----------
function updateStats(s) {
  if (!s) return;
  const cards = [
    ["Road length", (s.road_km ?? "—") + " km"], ["Intersections", s.nodes ?? "—"],
    ["Avg StreetIQ", s.avg_street_iq ?? "—"], ["One-way %", (s.oneway_pct ?? "—") + "%"],
    ["Walkability", s.avg_walkability ?? "—"], ["Bikeability", s.avg_bikeability ?? "—"],
    ["Avg noise", (s.avg_noise ?? "—") + " dB"], ["Data quality", (s.data_quality_pct ?? "—") + "%"],
    ["Transit stops", s.transit_stops ?? "—"], ["POIs", s.pois ?? "—"],
  ];
  $("statCards").innerHTML = cards.map(([l, v]) => `<div class="stat-card"><div class="v">${v}</div><div class="l">${l}</div></div>`).join("");
  $("sb_edges").textContent = "Edges: " + (s.streets ?? "—");
  $("sb_nodes").textContent = "Nodes: " + (s.nodes ?? "—");
  $("sb_transit").textContent = "Transit: " + (s.transit_routes ?? "—");
  $("sb_pois").textContent = "POIs: " + (s.pois ?? "—");
  $("sb_area").textContent = "Road: " + (s.road_km ?? "—") + " km";
  $("sb_tier").textContent = "Tier: " + (currentProject?.detail_tier ?? "—");
}
async function loadHistogram() {
  if (!currentRegion) return;
  const metric = $("colorBy").value === "highway" ? "street_iq" : $("colorBy").value;
  const h = await api(`/api/regions/${currentRegion}/histogram?metric=${metric}`);
  const labels = h.bins.slice(0, -1).map((b) => b.toFixed(2));
  if (histChart) histChart.destroy();
  histChart = new Chart($("histChart"), {
    type: "bar",
    data: { labels, datasets: [{ label: metric, data: h.counts, backgroundColor: "#4da3ff" }] },
    options: { plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#8595a5", maxTicksLimit: 6 }, grid: { display: false } },
        y: { ticks: { color: "#8595a5" }, grid: { color: "#2b3b4d" } } } },
  });
}
$("colorBy").addEventListener("change", loadHistogram);

// ---------- weights / recompute ----------
document.querySelectorAll(".slider input").forEach((inp) => {
  inp.addEventListener("input", () => { inp.nextElementSibling.textContent = (+inp.value).toFixed(2); });
});
$("recomputeBtn").addEventListener("click", async () => {
  if (!currentProject) { alert("Load a project first."); return; }
  spinner(true, "Recomputing StreetIQ…");
  try {
    const weights = { centrality: +$("w_centrality").value, flow: +$("w_flow").value,
      emissions: +$("w_emissions").value, noise: +$("w_noise").value };
    await api(`/api/projects/${currentProject.id}/analytics`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(weights) });
    await renderRegion(currentRegion, false);
    const proj = await api(`/api/projects/${currentProject.id}`);
    updateStats(proj.stats);
    await loadHistogram();
    loadRadar(proj.stats);
    status("StreetIQ recomputed.");
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
});

// ---------- welcome overlay ----------
const welSearch = document.getElementById("welcomeSearch");
if (welSearch) welSearch.addEventListener("click", () => { document.getElementById("welcome").classList.add("hidden"); $("citySearch").focus(); });
const welDraw = document.getElementById("welcomeDraw");
if (welDraw) welDraw.addEventListener("click", () => { document.getElementById("welcome").classList.add("hidden"); startDraw(); });

// ---------- time of day ----------
$("timeSlot").addEventListener("change", async () => {
  if (!currentRegion) return;
  await renderRegion(currentRegion, false);
  await loadHistogram();
});

// ---------- export menu ----------
$("exportBtn").addEventListener("click", (e) => {
  e.stopPropagation(); $("exportMenu").classList.toggle("hidden");
});
document.addEventListener("click", () => $("exportMenu").classList.add("hidden"));
$("exportMenu").addEventListener("click", (e) => {
  const kind = e.target.dataset.export;
  if (!kind || !currentRegion) { if (!currentRegion) alert("Load a project first."); return; }
  const base = `/api/regions/${currentRegion}`;
  if (kind === "report") window.open(`${base}/report?name=${encodeURIComponent(currentProject?.name || "SmartStreet")}`, "_blank");
  if (kind === "csv") window.open(`${base}/export/streets.csv`, "_blank");
  if (kind === "geojson") window.open(`${base}/export/streets.geojson`, "_blank");
});

// ---------- isochrones ----------
$("toolIso").addEventListener("click", () => setMapMode(mapMode === "iso" ? null : "iso"));
$("toolEdit").addEventListener("click", () => {
  if (!currentScenario) { alert("Create/select a scenario first (Scenario sandbox)."); return; }
  setMapMode(mapMode === "edit" ? null : "edit");
});
function setMapMode(mode) {
  mapMode = mode;
  $("toolIso").classList.toggle("active", mode === "iso");
  $("toolEdit").classList.toggle("active", mode === "edit");
  map.getCanvas().style.cursor = mode ? "crosshair" : "";
  const hint = $("toolHint");
  if (mode === "iso") { hint.textContent = "Click a point to compute reachability."; hint.classList.remove("hidden"); }
  else if (mode === "edit") { hint.textContent = "Click a street to edit it in the active scenario."; hint.classList.remove("hidden"); }
  else hint.classList.add("hidden");
}
async function runIsochrone(lngLat) {
  if (!currentRegion) return;
  spinner(true, "Computing isochrone…");
  try {
    const mode = $("isoMode").value;
    const res = await api(`/api/regions/${currentRegion}/isochrone`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lon: lngLat.lng, lat: lngLat.lat, mode, minutes: [5, 10, 15] }),
    });
    renderIsochrone(res);
    status(`Isochrone (${mode}): ${res.bands.map((b) => b.minutes + "min").join(", ")}`);
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
}
function renderIsochrone(res) {
  removeLayer("iso-fill"); removeLayer("iso-line"); removeSource("iso");
  const colors = { 15: "#4da3ff33", 10: "#4da3ff55", 5: "#4da3ff88" };
  const feats = res.bands.map((b) => ({
    type: "Feature", properties: { minutes: b.minutes },
    geometry: { type: "Polygon", coordinates: [b.coords] },
  }));
  const origin = { type: "Feature", geometry: { type: "Point", coordinates: res.origin }, properties: {} };
  map.addSource("iso", { type: "geojson", data: { type: "FeatureCollection", features: feats } });
  map.addLayer({ id: "iso-fill", type: "fill", source: "iso",
    paint: { "fill-color": ["match", ["get", "minutes"], 5, "#2ecc71", 10, "#f1c40f", 15, "#e67e22", "#4da3ff"],
      "fill-opacity": 0.25 } }, "streets-line");
  map.addLayer({ id: "iso-line", type: "line", source: "iso",
    paint: { "line-color": "#4da3ff", "line-width": 1 } });
}

// ---------- optimization ----------
$("optSignals").addEventListener("click", () => runOptimize("signals"));
$("optConnectivity").addEventListener("click", () => runOptimize("connectivity"));
$("optDirection").addEventListener("click", () => runOptimize("direction"));
$("showDecisions").addEventListener("change", () => {
  const vis = $("showDecisions").checked ? "visible" : "none";
  ["dec-signal", "dec-line"].forEach((l) => { if (map.getLayer(l)) map.setLayoutProperty(l, "visibility", vis); });
});
async function runOptimize(kind) {
  if (!currentRegion) { alert("Load a project first."); return; }
  const labels = { signals: "signal placement", connectivity: "connectivity gaps", direction: "direction solver" };
  spinner(true, `Running ${labels[kind]}…`);
  try {
    const res = await api(`/api/regions/${currentRegion}/optimize/${kind}`, { method: "POST" });
    status(`${labels[kind]}: ${res.count} recommendations`);
    await loadDecisions();
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
}
async function loadDecisions() {
  if (!currentRegion) return;
  const decisions = await api(`/api/regions/${currentRegion}/decisions`);
  renderDecisions(decisions);
  renderRecCards(decisions);
}
function renderDecisions(decisions) {
  removeLayer("dec-signal"); removeLayer("dec-line"); removeSource("dec-pt"); removeSource("dec-ln");
  const pts = decisions.filter((d) => d.geom && d.geom.type === "Point");
  const lns = decisions.filter((d) => d.geom && d.geom.type === "LineString");
  map.addSource("dec-pt", { type: "geojson", data: { type: "FeatureCollection",
    features: pts.map((d) => ({ type: "Feature", geometry: d.geom, properties: { id: d.id, cat: d.category } })) } });
  map.addLayer({ id: "dec-signal", type: "circle", source: "dec-pt",
    paint: { "circle-radius": 7, "circle-color": "#ff5252", "circle-opacity": 0.85,
      "circle-stroke-color": "#fff", "circle-stroke-width": 1.5 } });
  map.addSource("dec-ln", { type: "geojson", data: { type: "FeatureCollection",
    features: lns.map((d) => ({ type: "Feature", geometry: d.geom, properties: { id: d.id, cat: d.category } })) } });
  map.addLayer({ id: "dec-line", type: "line", source: "dec-ln",
    paint: { "line-color": ["match", ["get", "cat"], "new_link", "#f1c40f", "direction_change", "#2ecc71", "#ff5252"],
      "line-width": 4, "line-opacity": 0.85, "line-dasharray": [2, 1] } });
  const vis = $("showDecisions").checked ? "visible" : "none";
  ["dec-signal", "dec-line"].forEach((l) => map.setLayoutProperty(l, "visibility", vis));
}
function renderRecCards(decisions) {
  const box = $("optResults");
  if (!decisions.length) { box.innerHTML = '<div class="muted">No recommendations yet. Run an optimizer above.</div>'; return; }
  const catLabel = { signalization: "Signal", new_link: "New link", direction_change: "One-way" };
  box.innerHTML = decisions.slice(0, 30).map((d) => `
    <div class="rec-card" data-geom='${JSON.stringify(d.geom)}'>
      <div class="rc-head"><span>${catLabel[d.category] || d.category}</span>
        <span class="conf ${d.confidence}">${d.confidence}</span></div>
      <div class="rc-body">${d.rationale || ""}</div>
    </div>`).join("");
  [...box.children].forEach((el) => el.addEventListener("click", () => {
    const g = JSON.parse(el.dataset.geom);
    const c = g.type === "Point" ? g.coordinates : g.coordinates[0];
    map.flyTo({ center: c, zoom: 16 });
  }));
}

// ---------- scenarios ----------
$("newScenario").addEventListener("click", async () => {
  if (!currentProject) { alert("Load a project first."); return; }
  const name = prompt("Scenario name:", "Scenario " + new Date().toLocaleTimeString());
  if (!name) return;
  const res = await api("/api/scenarios", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project_id: currentProject.id, region_id: currentRegion, name }) });
  await loadScenarios();
  $("scenarioSel").value = String(res.scenario_id);
  currentScenario = String(res.scenario_id);
  refreshOverrides([]);
});
$("scenarioSel").addEventListener("change", async () => {
  currentScenario = $("scenarioSel").value;
  if (mapMode === "edit" && !currentScenario) setMapMode(null);
  await loadScenarios();
});
async function loadScenarios() {
  if (!currentProject) return;
  const scs = await api(`/api/projects/${currentProject.id}/scenarios`);
  const sel = $("scenarioSel");
  const prev = currentScenario;
  sel.innerHTML = '<option value="">Baseline (no scenario)</option>' +
    scs.map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
  if (prev && scs.some((s) => String(s.id) === prev)) sel.value = prev;
  currentScenario = sel.value;
  const active = scs.find((s) => String(s.id) === currentScenario);
  refreshOverrides(active ? active.overrides.filter((o) => o.active) : []);
}
function refreshOverrides(overrides) {
  const box = $("scenarioOverrides");
  if (!currentScenario) { box.innerHTML = "No active scenario. Create one to edit roads."; return; }
  if (!overrides.length) { box.innerHTML = "No edits yet. Use ✎ Edit roads to modify streets."; return; }
  box.innerHTML = overrides.map((o) => `<div class="ov-item">#${o.sequence_number} ${o.action_type}
    → edge ${o.target_id} ${JSON.stringify(o.attribute_overrides)}</div>`).join("");
}
function openEditModal(p) {
  editTargetId = p.id;
  $("editTarget").textContent = `${p.name || "Unnamed"} (${p.highway}, edge ${p.id})`;
  $("editModal").classList.remove("hidden");
}
$("editCancel").addEventListener("click", () => $("editModal").classList.add("hidden"));
document.querySelectorAll("#editModal [data-edit]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const kind = btn.dataset.edit;
    let action = "attribute_change", attrs = {};
    if (kind === "closure") action = "closure";
    else if (kind === "direction_change") { action = "direction_change"; attrs = { oneway: 1 }; }
    else if (kind === "speed30") attrs = { maxspeed: 30 };
    else if (kind === "speed50") attrs = { maxspeed: 50 };
    $("editModal").classList.add("hidden");
    await api(`/api/scenarios/${currentScenario}/overrides`, { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_id: editTargetId, action_type: action, attribute_overrides: attrs }) });
    await loadScenarios();
    status("Edit added to scenario. Click Compare to see impact.");
  });
});
$("undoBtn").addEventListener("click", async () => {
  if (!currentScenario) return;
  await api(`/api/scenarios/${currentScenario}/undo`, { method: "POST" });
  await loadScenarios();
});
$("redoBtn").addEventListener("click", async () => {
  if (!currentScenario) return;
  await api(`/api/scenarios/${currentScenario}/redo`, { method: "POST" });
  await loadScenarios();
});
$("compareBtn").addEventListener("click", async () => {
  if (!currentScenario) { alert("Select a scenario first."); return; }
  spinner(true, "Comparing scenario to baseline…");
  try {
    const res = await api(`/api/scenarios/${currentScenario}/compare`);
    renderCompare(res.metrics);
    status("Scenario compared to baseline.");
  } catch (err) { alert("Error: " + err.message); }
  finally { spinner(false); }
});
function renderCompare(metrics) {
  const labels = { total_travel_time: "Travel time", total_co2: "CO₂", oneway_pct: "One-way %", reachability: "Reachability" };
  const keys = Object.keys(metrics);
  const data = keys.map((k) => metrics[k].delta_pct);
  if (compareChart) compareChart.destroy();
  compareChart = new Chart($("compareChart"), {
    type: "bar",
    data: { labels: keys.map((k) => labels[k] || k),
      datasets: [{ label: "Δ % vs baseline", data,
        backgroundColor: data.map((v) => v <= 0 ? "#2ecc71" : "#e74c3c") }] },
    options: { plugins: { legend: { display: false }, title: { display: true, text: "Δ % vs baseline", color: "#8595a5" } },
      scales: { x: { ticks: { color: "#8595a5", font: { size: 9 } }, grid: { display: false } },
        y: { ticks: { color: "#8595a5" }, grid: { color: "#2b3b4d" } } } },
  });
}

// ---------- radar ----------
function loadRadar(s) {
  if (!s) return;
  const vals = [
    Math.min(1, (s.avg_street_iq ?? 0)),
    s.avg_walkability ?? 0,
    s.avg_bikeability ?? 0,
    (s.data_quality_pct ?? 0) / 100,
    Math.min(1, (s.road_km ?? 0) / 50),
    Math.min(1, (s.transit_stops ?? 0) / 50),
  ];
  if (radarChart) radarChart.destroy();
  radarChart = new Chart($("radarChart"), {
    type: "radar",
    data: { labels: ["StreetIQ", "Walk", "Bike", "Data", "Road", "Transit"],
      datasets: [{ data: vals, backgroundColor: "#4da3ff33", borderColor: "#4da3ff", pointBackgroundColor: "#4da3ff" }] },
    options: { plugins: { legend: { display: false } },
      scales: { r: { min: 0, max: 1, ticks: { display: false }, grid: { color: "#2b3b4d" },
        angleLines: { color: "#2b3b4d" }, pointLabels: { color: "#8595a5", font: { size: 9 } } } } },
  });
}

// ---------- city / place search ----------
let searchTimer = null, searchResults = [], activeIdx = -1;
const searchInput = $("citySearch"), resultsBox = $("searchResults");

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = searchInput.value.trim();
  if (q.length < 2) { hideResults(); return; }
  searchTimer = setTimeout(() => runSearch(q), 350);
});
searchInput.addEventListener("keydown", (e) => {
  if (resultsBox.classList.contains("hidden")) return;
  if (e.key === "ArrowDown") { e.preventDefault(); activeIdx = Math.min(activeIdx + 1, searchResults.length - 1); highlight(); }
  else if (e.key === "ArrowUp") { e.preventDefault(); activeIdx = Math.max(activeIdx - 1, 0); highlight(); }
  else if (e.key === "Enter") { e.preventDefault(); if (activeIdx >= 0) selectPlace(searchResults[activeIdx]); }
  else if (e.key === "Escape") { hideResults(); }
});
document.addEventListener("click", (e) => { if (!e.target.closest(".search-wrap")) hideResults(); });

function hideResults() { resultsBox.classList.add("hidden"); activeIdx = -1; }
function highlight() {
  [...resultsBox.children].forEach((el, i) => el.classList.toggle("active", i === activeIdx));
}
async function runSearch(q) {
  resultsBox.classList.remove("hidden");
  resultsBox.innerHTML = '<div class="loading">Searching…</div>';
  try {
    searchResults = await api(`/api/geocode?q=${encodeURIComponent(q)}`);
  } catch (err) { resultsBox.innerHTML = `<div class="loading">${err.message}</div>`; return; }
  if (!searchResults.length) { resultsBox.innerHTML = '<div class="loading">No matches.</div>'; return; }
  activeIdx = -1;
  resultsBox.innerHTML = "";
  searchResults.forEach((r, i) => {
    const parts = (r.name || "").split(",");
    const primary = parts.slice(0, 2).join(",");
    const sub = parts.slice(2).join(",").trim();
    const el = document.createElement("div");
    el.className = "res";
    el.innerHTML = `<div>${primary}</div>${sub ? `<div class="sub">${sub}</div>` : ""}`;
    el.addEventListener("click", () => selectPlace(r));
    resultsBox.appendChild(el);
  });
}
function selectPlace(r) {
  hideResults();
  searchInput.value = (r.name || "").split(",").slice(0, 2).join(",");
  if (r.bbox) {
    const area = bboxAreaKm2(r.bbox);
    const [w, s, e, n] = r.bbox;
    map.fitBounds([[w, s], [e, n]], { padding: 40, maxZoom: 15 });
    if (area <= 50) {
      // small enough to fetch directly — pre-fill the draw box + open create dialog
      drawPts = [[w, s], [e, n]];
      drawBoxPreview();
      $("modalArea").textContent = `${r.name.split(",")[0]} — ${area.toFixed(1)} km² (tier ${tierFor(area)})`;
      $("projInput").value = r.name.split(",")[0];
      $("modal").classList.remove("hidden");
      status(`Found ${r.name.split(",")[0]} — confirm to fetch this area`);
    } else {
      status(`${r.name.split(",")[0]} is large (${area.toFixed(0)} km²). Zoom in and draw a box ≤ 50 km².`);
    }
  } else {
    map.flyTo({ center: [r.lon, r.lat], zoom: 14 });
    status(`Centered on ${r.name.split(",")[0]}. Draw a bounding box to fetch data.`);
  }
}

initMap();
