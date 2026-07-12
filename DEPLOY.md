# Deploying SmartStreet (free)

The backend is Python/FastAPI with real computation (NetworkX, Shapely), a SQLite
database, and live Overpass fetches that can exceed serverless time limits. That
does **not** fit Vercel's serverless functions. The frontend, however, is a static
SPA and is perfect for Vercel.

## Recommended (simplest, fully free): one Render service

The FastAPI app already serves the dashboard UI itself, so a single service is all
you need.

1. Push this repository to GitHub.
2. On [render.com](https://render.com) → **New → Blueprint** and select the repo.
   Render reads `render.yaml` + `Dockerfile` automatically.
3. Wait for the build; open the resulting `https://smartstreet-xxxx.onrender.com`.
   That URL is the full app — API **and** dashboard.

Notes:
- Free tier spins down after ~15 min idle (first request then takes ~30–50 s to wake).
- SQLite lives in `/tmp` and resets on redeploy/spin-down — fetched OSM data simply
  regenerates when you draw a bbox again. For permanent storage, attach a disk
  (paid) or point `SMARTSTREET_DB` at a mounted volume (Fly.io offers a free volume).

Other equivalent free hosts for the Docker image: **Railway**, **Fly.io**
(free volume = persistent SQLite), **Koyeb** (no cold start).

## Split deploy: frontend on Vercel + backend on Render

If you specifically want the UI on Vercel:

1. Deploy the backend to Render as above → note its URL.
2. Edit `frontend/vercel.json` and replace `YOUR-BACKEND-URL.onrender.com` with your
   Render URL. This proxies `/api/*` to the backend, so the app stays same-origin
   (no CORS, no other changes).
3. On [vercel.com](https://vercel.com) → **New Project** → import the repo, set
   **Root Directory = `frontend`**, framework preset **Other**, and deploy.

Alternative to the proxy: instead of editing `vercel.json`, set the backend URL in
`frontend/config.js` (`window.SMARTSTREET_API = "https://...";`). CORS is already
open on the backend.

## Local run

`start.bat` (Windows) or `python run.py` — see `README.md`.
