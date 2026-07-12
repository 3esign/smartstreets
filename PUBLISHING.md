# Publishing SmartStreet — release guide (v2: simulator + revised methodology)

How to publish this version, whether it's your first deploy or an update to an
existing one. Beginner walkthrough for GitHub/Render: `DEPLOY_STEPS.md`.
Platform background: `DEPLOY.md`.

---

## 1 · Pre-publish checklist (5 min, local)

Run in `D:\Projekti\SmartStreet` with the venv active:

```bat
.venv\Scripts\activate
pip install -r requirements.txt        REM pulls the new scipy dependency
python tests\test_synthetic.py         REM must end with: ALL TESTS PASSED
python run.py                          REM manual smoke test, then Ctrl+C
```

Manual smoke test in the browser (http://localhost:8000):

1. Load or create a small project (tier A bbox).
2. Click **Recompute StreetIQ** once — populates the new v/c + congested-speed
   columns for projects created before this version.
3. Color streets by **Congestion (v/c, BPR)** and **Noise (dB, CNOSSOS-EU)**.
4. Basemap → **None (blank)** — geometry renders on a dark background.
5. Isochrone: compute → **💾 Save** → reload from the Isochrones panel → ✕ delete.
6. **▶ Run simulation** (defaults) — progress bar fills, timeline appears,
   agents animate when you press ▶, charts populate, **⬇ CSV** downloads.
7. Top bar **Methodology** opens the cited methodology modal.

Do **not** commit your local database — `.gitignore` already excludes
`smartstreet.db*`. Nothing else in the repo is secret; there are no API keys.

## 2 · What changed operationally in this version

- **New dependency `scipy`** — already in `requirements.txt`; Docker/Render
  installs it automatically. First build is ~1–2 min slower.
- **Database migrates itself.** On startup `init_db()` creates the new tables
  (`isochrone_saves`, `sim_runs`, `sim_years`, `sim_agents`) and adds the new
  `street_analytics` columns (`voc`, `congested_speed`) to an existing DB. No
  manual migration steps, no data loss.
- **Old projects need one click of "Recompute StreetIQ"** to fill the new
  metrics (values also change: CO₂/noise now use COPERT / CNOSSOS-EU models).
- **Simulations run as background threads inside the web process.** Keep a
  single uvicorn worker (the provided Dockerfile/`run.py` already do). Do not
  add `--workers N` — SQLite + in-process runs assume one process.
- **Persistence now matters more.** Saved isochrones and simulation runs live
  in SQLite. On Render's free tier the DB is in `/tmp` and is wiped on
  redeploy/spin-down. Fine for demos; for keeping results see §5.

## 3 · Publish (single service — recommended)

Already deployed once (a Render service exists):

```bat
cd /d D:\Projekti\SmartStreet
git add -A
git commit -m "v2: multi-year agent simulator, CNOSSOS/COPERT/BPR methodology, isochrone saves, blank basemap"
git push
```

Render auto-builds and redeploys the blueprint on push. Watch the deploy log
until "Live", then run the smoke test (§6) against your public URL.

First-time deploy: follow `DEPLOY_STEPS.md` (GitHub push → Render → New →
Blueprint → select repo). `render.yaml` + `Dockerfile` do the rest.

## 4 · Publish (split: Vercel frontend + Render backend)

Only if you use the split setup:

1. Push as in §3 — the Render backend updates itself.
2. `frontend/vercel.json` must point at *your* backend URL (it currently
   proxies to `https://smartstreet-g0wa.onrender.com`). Update if that's not
   your service.
3. Vercel redeploys the frontend automatically on push (Root Directory =
   `frontend`). The new files (`sim.js`, updated `index.html`/`style.css`)
   ship with it — no extra configuration.

## 5 · Optional: keep data across restarts

Pick one when saved isochrones / simulation history should survive:

- **Render paid disk**: attach a disk (e.g. mount `/data`) and set env var
  `SMARTSTREET_DB=/data/smartstreet.db`.
- **Fly.io free volume**: `fly launch` with the same Dockerfile, create a
  volume, mount it, set `SMARTSTREET_DB` to the mount path.
- **Any VPS/Docker host**: `docker run -p 8000:8000 -v ss_data:/data
  -e SMARTSTREET_DB=/data/smartstreet.db <image>`.

Also note: free-tier spin-down (~15 min idle) kills an in-flight simulation
thread. Runs complete in seconds-to-minutes, so in practice: start a run, keep
the tab open until the progress bar finishes. Re-running is cheap.

## 6 · Post-publish smoke test (public URL)

1. `https://<your-app>/api/health` → `{"status":"ok"}`.
2. First request after idle may take 30–50 s (free-tier cold start) — normal.
3. Create a small tier-A project (Overpass fetch works from Render).
4. Run a short simulation (10 years) end-to-end; export CSV.
5. Open the report (Export → report) and the Methodology modal.

## 7 · Rollback

Render keeps previous deploys: service → **Deploys** → pick the last good one
→ **Rollback**. Or `git revert <commit> && git push`. The DB schema is
backward-compatible (new tables/columns are additive), so rolling back the
code is safe.

## 8 · Announcing / citing

The scientific basis is documented in `docs/METHODOLOGY.md` (equations,
parameters, ~35 references, assumptions & limitations). When publishing
results derived from the tool, cite that document and note that flows are
betweenness-based estimates and simulations are scenario explorations, not
forecasts — the same caveats stated in-app.
