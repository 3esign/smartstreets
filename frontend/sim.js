/* SmartStreet — multi-year simulation UI: timeline, agent animation,
   network-evolution overlay, congestion view, trend charts.
   Loads after app.js and shares its top-level bindings (map, api, $ …). */

(function () {
  "use strict";

  const MODE_COLORS = { car: "#ff6b57", transit: "#38b6ff", bike: "#2ecc71", walk: "#f1c40f" };
  const DELTA_COLORS = { new: "#ffd54d", up: "#ff9f43", ped: "#7ee0c8" };
  const DAY_START = 5.5 * 3600, DAY_END = 22.5 * 3600;

  let activeRun = null;          // {id, name, status, years_done: [...]}
  let curYear = 0;
  let yearCache = {}, agentCache = {}, seriesCache = [];
  let pollTimer = null, yearAutoTimer = null;
  let playing = false, clock = 7.5 * 3600, speed = 300, rafId = null, lastTs = null;
  let modeChart = null, kpiChart = null;
  let agentsFC = { type: "FeatureCollection", features: [] };

  // ---------- run management ----------
  async function runSimulation() {
    if (!currentProject) { alert("Load a project first."); return; }
    const params = {
      name: `${currentProject.name} · ${new Date().toLocaleTimeString()}`,
      years: +$("sim_years").value,
      pop_growth_pct: +$("sim_growth").value,
      road_budget: +$("sim_budget").value,
      transit_invest: +$("sim_transit").value,
      bike_invest: +$("sim_bike").value,
      car_ownership_growth_pct: +$("sim_car").value,
      pedestrianization: $("sim_ped").checked,
    };
    try {
      const res = await api(`/api/projects/${currentProject.id}/simulations`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });
      status("Simulation started…");
      $("simProgress").classList.remove("hidden");
      await loadRunList();
      watchRun(res.run_id, true);
    } catch (err) { alert("Error: " + err.message); }
  }

  function watchRun(runId, autoActivate) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const run = await api(`/api/simulations/${runId}`);
        const pct = Math.round((run.progress || 0) * 100);
        $("simProgressBar").style.width = pct + "%";
        $("simProgressText").textContent = run.status === "running"
          ? `${run.message || "Running"} ${pct}%` : (run.message || run.status);
        if (run.years_done.length) {
          if (autoActivate && !activeRun) activateRun(run);
          if (activeRun && activeRun.id === run.id) {
            activeRun = run;
            $("simYearSlider").max = run.years_done.length - 1;
            refreshCharts(run.id).catch(console.error);
          }
        }
        if (run.status === "done" || run.status === "error") {
          clearInterval(pollTimer); pollTimer = null;
          $("simProgress").classList.toggle("hidden", run.status === "done");
          if (run.status === "error") $("simProgressText").textContent = "Error: " + (run.message || "failed");
          await loadRunList();
          if (activeRun && activeRun.id === run.id) {
            activeRun = run;
            $("simYearSlider").max = Math.max(run.years_done.length - 1, 0);
            refreshCharts(run.id).catch(console.error);
          }
          status(run.status === "done" ? "Simulation complete." : "Simulation failed.");
        }
      } catch (err) { console.error(err); }
    }, 1500);
  }

  async function loadRunList() {
    const box = $("simRunList");
    if (!currentProject) { box.innerHTML = '<div class="muted">Load a project first.</div>'; return; }
    try {
      const runs = await api(`/api/projects/${currentProject.id}/simulations`);
      box.innerHTML = runs.length ? "" : '<div class="muted">No simulations yet.</div>';
      runs.forEach((r) => {
        const el = document.createElement("div");
        el.className = "proj-item" + (activeRun && activeRun.id === r.id ? " active" : "");
        const chip = r.status === "done" ? "✓" : r.status === "running" ? "⏳" : r.status === "error" ? "⚠" : "…";
        el.innerHTML = `<div><div>${r.name || "Run " + r.id}</div>
          <div class="meta">${chip} ${r.status} · ${r.params.years || "?"} yrs</div></div>
          <span class="del" title="Delete">✕</span>`;
        el.onclick = async (ev) => {
          if (ev.target.className === "del") return;
          const run = await api(`/api/simulations/${r.id}`);
          activateRun(run);
          if (run.status === "running") { $("simProgress").classList.remove("hidden"); watchRun(run.id, false); }
        };
        el.querySelector(".del").onclick = async (ev) => {
          ev.stopPropagation();
          if (!confirm("Delete this simulation run?")) return;
          await api(`/api/simulations/${r.id}`, { method: "DELETE" });
          if (activeRun && activeRun.id === r.id) closeSim();
          loadRunList().catch(console.error);
        };
        box.appendChild(el);
      });
    } catch (err) { console.error(err); }
  }

  function activateRun(run) {
    activeRun = run;
    yearCache = {}; agentCache = {}; seriesCache = [];
    curYear = 0;
    $("simBar").classList.remove("hidden");
    $("simYearSlider").max = Math.max(run.years_done.length - 1, 0);
    $("simYearSlider").value = 0;
    ensureLayers();
    selectYear(0).catch(console.error);
    refreshCharts(run.id).catch(console.error);
    loadRunList().catch(console.error);
    if (!rafId) rafId = requestAnimationFrame(tick);
  }

  function closeSim() {
    activeRun = null; playing = false;
    $("simBar").classList.add("hidden");
    stopYearAutoplay();
    ["sim-agents-glow", "sim-agents-pt", "sim-delta-line"].forEach((l) => { if (map.getLayer(l)) map.removeLayer(l); });
    ["sim-agents", "sim-delta"].forEach((s) => { if (map.getSource(s)) map.removeSource(s); });
    if ($("simShowCong").checked) { $("simShowCong").checked = false; applyColorBy(); }
  }

  // ---------- map layers ----------
  let deltaPopupBound = false;
  function ensureLayers() {
    if (!deltaPopupBound) {
      deltaPopupBound = true;
      map.on("click", "sim-delta-line", (e) => {
        const p = e.features[0].properties;
        const label = { new: "New link", up: "Capacity upgrade", ped: "Pedestrianized" }[p.a] || p.a;
        new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat)
          .setHTML(`<b>${label}</b> (year ${p.year})<br>${p.note}`).addTo(map);
      });
    }
    if (!map.getSource("sim-delta")) {
      map.addSource("sim-delta", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "sim-delta-line", type: "line", source: "sim-delta",
        paint: {
          "line-color": ["match", ["get", "a"], "new", DELTA_COLORS.new, "up", DELTA_COLORS.up, "ped", DELTA_COLORS.ped, "#fff"],
          "line-width": ["case", ["get", "current"], 5, 3],
          "line-opacity": ["case", ["get", "current"], 0.95, 0.55],
          "line-dasharray": [1.4, 0.8],
        },
      });
    }
    if (!map.getSource("sim-agents")) {
      map.addSource("sim-agents", { type: "geojson", data: agentsFC });
      map.addLayer({
        id: "sim-agents-glow", type: "circle", source: "sim-agents",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 5, 16, 11],
          "circle-color": ["match", ["get", "m"], "car", MODE_COLORS.car, "transit", MODE_COLORS.transit, "bike", MODE_COLORS.bike, MODE_COLORS.walk],
          "circle-blur": 1.2, "circle-opacity": 0.35,
        },
      });
      map.addLayer({
        id: "sim-agents-pt", type: "circle", source: "sim-agents",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 11, 2.2, 16, 4.6],
          "circle-color": ["match", ["get", "m"], "car", MODE_COLORS.car, "transit", MODE_COLORS.transit, "bike", MODE_COLORS.bike, MODE_COLORS.walk],
          "circle-stroke-color": "#0b1420", "circle-stroke-width": 0.6,
        },
      });
    }
    applyAgentVisibility();
    applyDeltaVisibility();
  }

  function onStyleReload() {
    if (!activeRun) return;
    ensureLayers();
    renderDeltas();
    if ($("simShowCong").checked) applyCongestion();
  }

  // ---------- year handling ----------
  async function fetchYear(y) {
    if (!yearCache[y]) yearCache[y] = await api(`/api/simulations/${activeRun.id}/years/${y}`);
    return yearCache[y];
  }
  async function fetchAgents(y) {
    if (!agentCache[y]) {
      const res = await api(`/api/simulations/${activeRun.id}/years/${y}/agents`);
      agentCache[y] = (res.agents || []).map((a) => ({ ...a, end: a.t.length ? a.t[a.t.length - 1] : 0 }));
    }
    return agentCache[y];
  }

  async function selectYear(y) {
    if (!activeRun) return;
    curYear = y;
    $("simYearLabel").textContent = y;
    $("simYearSlider").value = y;
    try {
      const data = await fetchYear(y);
      await fetchAgents(y);
      updateKpis(data.metrics);
      renderDeltas();
      if ($("simShowCong").checked) applyCongestion();
    } catch (err) { console.error(err); }
  }

  function updateKpis(m) {
    if (!m) return;
    $("simKpiPop").textContent = `👥 ${Number(m.population).toLocaleString()}`;
    $("simKpiCar").textContent = `🚗 ${(m.share_car * 100).toFixed(0)} % car`;
    $("simKpiCo2").textContent = `CO₂ ${m.co2_t_day} t/d`;
    $("simKpiCong").textContent = `⛔ ${m.congested_km} km jammed`;
    const y0 = yearCache[0] && yearCache[0].metrics;
    const d = y0 && y0.accessibility ? ((m.accessibility - y0.accessibility) / y0.accessibility * 100) : 0;
    $("simKpiAcc").textContent = `♿ access ${d >= 0 ? "+" : ""}${d.toFixed(1)} %`;
  }

  function renderDeltas() {
    if (!map.getSource("sim-delta")) return;
    const feats = [];
    for (let y = 0; y <= curYear; y++) {
      const d = yearCache[y];
      if (!d || !d.deltas) continue;
      d.deltas.forEach((del) => {
        if (!del.geom || del.geom.length < 2) return;
        feats.push({
          type: "Feature",
          geometry: { type: "LineString", coordinates: del.geom },
          properties: { a: del.a, current: y === curYear, note: del.note || "", year: y },
        });
      });
    }
    map.getSource("sim-delta").setData({ type: "FeatureCollection", features: feats });
  }

  function applyCongestion() {
    if (!map.getLayer("streets-line") || !yearCache[curYear]) return;
    const voc = yearCache[curYear].voc || {};
    const expr = ["match", ["get", "id"]];
    let n = 0;
    for (const [id, v] of Object.entries(voc)) {
      const c = v >= 1.0 ? "#e74c3c" : v >= 0.8 ? "#e67e22" : v >= 0.6 ? "#f1c40f" : "#a3d94b";
      expr.push(+id, c); n++;
    }
    expr.push("#39506b");
    map.setPaintProperty("streets-line", "line-color", n ? expr : "#39506b");
    renderLegend(null);
  }

  // ---------- agent animation ----------
  function fmtClock(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
  }

  function positionAt(agent, t) {
    const rel = t - agent.d;
    if (rel < 0 || rel > agent.end || agent.p.length < 2) return null;
    const times = agent.t;
    let lo = 0, hi = times.length - 1;
    while (lo < hi - 1) {
      const mid = (lo + hi) >> 1;
      if (times[mid] <= rel) lo = mid; else hi = mid;
    }
    const t0 = times[lo], t1 = times[hi];
    const f = t1 > t0 ? (rel - t0) / (t1 - t0) : 0;
    const p0 = agent.p[lo], p1 = agent.p[hi];
    return [p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f];
  }

  function tick(ts) {
    rafId = requestAnimationFrame(tick);
    if (!activeRun) return;
    const dt = lastTs ? (ts - lastTs) / 1000 : 0;
    lastTs = ts;
    if (playing) {
      clock += dt * speed;
      if (clock > DAY_END) clock = DAY_START;
      $("simClock").textContent = fmtClock(clock);
    }
    if (!$("simShowAgents").checked || !map.getSource("sim-agents")) return;
    const agents = agentCache[curYear];
    if (!agents) return;
    const feats = [];
    for (const a of agents) {
      const pos = positionAt(a, clock);
      if (pos) feats.push({ type: "Feature", geometry: { type: "Point", coordinates: pos }, properties: { m: a.m } });
    }
    agentsFC.features = feats;
    map.getSource("sim-agents").setData(agentsFC);
  }

  function applyAgentVisibility() {
    const vis = $("simShowAgents").checked ? "visible" : "none";
    ["sim-agents-glow", "sim-agents-pt"].forEach((l) => { if (map.getLayer(l)) map.setLayoutProperty(l, "visibility", vis); });
  }
  function applyDeltaVisibility() {
    const vis = $("simShowDeltas").checked ? "visible" : "none";
    if (map.getLayer("sim-delta-line")) map.setLayoutProperty("sim-delta-line", "visibility", vis);
  }

  // ---------- year autoplay ----------
  function stopYearAutoplay() {
    if (yearAutoTimer) { clearInterval(yearAutoTimer); yearAutoTimer = null; $("simPlayYearsBtn").classList.remove("active"); }
  }
  function toggleYearAutoplay() {
    if (yearAutoTimer) { stopYearAutoplay(); return; }
    $("simPlayYearsBtn").classList.add("active");
    yearAutoTimer = setInterval(() => {
      const max = +$("simYearSlider").max;
      if (curYear >= max) { stopYearAutoplay(); return; }
      selectYear(curYear + 1).catch(console.error);
    }, 1400);
  }

  // ---------- charts ----------
  async function refreshCharts(runId) {
    seriesCache = await api(`/api/simulations/${runId}/series`);
    if (!seriesCache.length) return;
    const years = seriesCache.map((r) => r.year);
    const ds = (key, color) => ({
      label: key, data: seriesCache.map((r) => (r[key] != null ? +(r[key] * 100).toFixed(1) : null)),
      borderColor: color, backgroundColor: color + "44", fill: true, pointRadius: 0, borderWidth: 1.6, tension: 0.3,
    });
    if (modeChart) modeChart.destroy();
    modeChart = new Chart($("simModeChart"), {
      type: "line",
      data: { labels: years, datasets: [
        ds("share_car", MODE_COLORS.car), ds("share_transit", MODE_COLORS.transit),
        ds("share_bike", MODE_COLORS.bike), ds("share_walk", MODE_COLORS.walk)] },
      options: {
        plugins: { legend: { labels: { color: "#8595a5", boxWidth: 8, font: { size: 9 } } },
          title: { display: true, text: "Mode shares (%)", color: "#8595a5", font: { size: 10 } } },
        scales: { x: { ticks: { color: "#8595a5", maxTicksLimit: 8 }, grid: { display: false } },
          y: { stacked: false, ticks: { color: "#8595a5" }, grid: { color: "#2b3b4d" } } },
        animation: false,
      },
    });
    drawKpiChart();
  }

  function drawKpiChart() {
    if (!seriesCache.length) return;
    const key = $("simKpiSel").value;
    const years = seriesCache.map((r) => r.year);
    if (kpiChart) kpiChart.destroy();
    kpiChart = new Chart($("simKpiChart"), {
      type: "line",
      data: { labels: years, datasets: [{
        label: key, data: seriesCache.map((r) => r[key]),
        borderColor: "#4da3ff", backgroundColor: "#4da3ff33", fill: true,
        pointRadius: 0, borderWidth: 1.8, tension: 0.3 }] },
      options: {
        plugins: { legend: { display: false },
          title: { display: true, text: $("simKpiSel").selectedOptions[0].text, color: "#8595a5", font: { size: 10 } } },
        scales: { x: { ticks: { color: "#8595a5", maxTicksLimit: 8 }, grid: { display: false } },
          y: { ticks: { color: "#8595a5" }, grid: { color: "#2b3b4d" } } },
        animation: false,
      },
    });
  }

  // ---------- wiring ----------
  $("simRunBtn").addEventListener("click", () => runSimulation().catch(console.error));
  $("simYearSlider").addEventListener("input", () => { stopYearAutoplay(); selectYear(+$("simYearSlider").value).catch(console.error); });
  $("simPlayYearsBtn").addEventListener("click", toggleYearAutoplay);
  $("simPlayBtn").addEventListener("click", () => {
    playing = !playing;
    $("simPlayBtn").textContent = playing ? "⏸" : "▶";
    $("simPlayBtn").classList.toggle("active", playing);
  });
  $("simSpeedSel").addEventListener("change", () => { speed = +$("simSpeedSel").value; });
  $("simShowAgents").addEventListener("change", applyAgentVisibility);
  $("simShowDeltas").addEventListener("change", applyDeltaVisibility);
  $("simShowCong").addEventListener("change", () => {
    if ($("simShowCong").checked) applyCongestion(); else applyColorBy();
  });
  $("simCloseBtn").addEventListener("click", closeSim);
  $("simKpiSel").addEventListener("change", drawKpiChart);
  $("simCsvBtn").addEventListener("click", () => { if (activeRun) window.open(`${API}/api/simulations/${activeRun.id}/export.csv`, "_blank"); });
  $("simJsonBtn").addEventListener("click", () => { if (activeRun) window.open(`${API}/api/simulations/${activeRun.id}/export.json`, "_blank"); });

  window.SimUI = {
    onProjectLoaded() { closeSim(); loadRunList().catch(console.error); },
    onStyleReload,
  };
})();
