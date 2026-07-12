# SmartStreet — Step-by-step deployment (free)

You'll do two things: (1) push the code to GitHub, (2) launch it on Render's free
tier. Render runs the whole app (API **and** dashboard) as one service, so there's
nothing else to wire up. Takes ~10 minutes.

> Everything is already prepared in this folder: `Dockerfile`, `render.yaml`,
> `.gitignore`, and the app itself. You just push and click.

---

## Part 1 — Push the code to GitHub

### 1.1 Check git is installed
Open a terminal in this folder and run:

```bat
git --version
```

- If you see a version number, continue.
- If not, install Git from https://git-scm.com/download/win (accept all defaults),
  close and reopen the terminal, then continue. (Or use **GitHub Desktop** — see 1.5.)

### 1.2 Create the local repository
In the terminal, **in this folder** (`D:\Projekti\SmartStreet`):

```bat
cd /d D:\Projekti\SmartStreet
git init
git add .
git commit -m "SmartStreet initial commit"
git branch -M main
```

### 1.3 Create an empty repo on GitHub
1. Go to https://github.com/new
2. Repository name: `smartstreet`
3. Leave it **empty** — do NOT add a README, .gitignore, or license.
4. Click **Create repository**.
5. Copy the URL shown (looks like `https://github.com/YOURNAME/smartstreet.git`).

### 1.4 Push
Replace the URL with yours:

```bat
git remote add origin https://github.com/YOURNAME/smartstreet.git
git push -u origin main
```

If prompted to sign in, a browser window will open — authorize it. Done.

### 1.5 (Alternative, no commands) GitHub Desktop
1. Install from https://desktop.github.com
2. **File → Add local repository →** choose `D:\Projekti\SmartStreet`.
3. When it offers to create a repository here, click **create a repository**, then
   **Publish repository** (untick "Keep this code private" if you want it public).

---

## Part 2 — Launch on Render (free)

1. Go to https://render.com and **Sign in with GitHub** (easiest).
2. Click **New +** (top right) → **Blueprint**.
3. Under "Connect a repository", pick your **smartstreet** repo. (If Render asks for
   GitHub permission, approve it for this repo.)
4. Render detects `render.yaml`. Click **Apply** / **Create Services**.
5. Wait for the build to finish (~3–5 minutes; watch the log until "Live").
6. Click the service, then open its URL: `https://smartstreet-xxxx.onrender.com`.
   **That URL is your live app** — search a city, draw a bbox, everything works.

### Good to know
- **Free tier sleeps** after ~15 min of no traffic. The next visit takes ~40 s to
  wake up, then it's fast again. That's normal for free hosting.
- The database lives in `/tmp` and resets on each redeploy/sleep — your fetched OSM
  data just regenerates when you draw a bbox again. (For permanent storage, use
  Fly.io with a free volume, or add a Render disk on a paid plan.)

---

## Part 3 (optional) — Put the UI on Vercel

Only do this if you specifically want the frontend on Vercel. The Render URL from
Part 2 is already a complete, shareable app.

1. Open `frontend/vercel.json` and replace `YOUR-BACKEND-URL.onrender.com` with your
   real Render URL (from Part 2). Commit & push:
   ```bat
   git add frontend/vercel.json && git commit -m "point vercel at backend" && git push
   ```
2. Go to https://vercel.com → **Add New… → Project** → import the `smartstreet` repo.
3. Set **Root Directory** to `frontend`, Framework Preset **Other**, click **Deploy**.
4. Open the Vercel URL — the dashboard loads and calls your Render backend.

---

## Troubleshooting

- **`git push` rejected / auth error** → make sure the GitHub repo is empty (Part 1.3)
  and you're signed in. Re-run the push.
- **Render build fails on `pip install`** → open the log; it's almost always a network
  blip — click **Manual Deploy → Clear build cache & deploy**.
- **App loads but map is blank** → you likely haven't fetched data yet: search a city
  or draw a bounding box, then click Fetch.
- **"Application error" right after deploy** → give it another 30–60 s; the free
  instance may still be starting.
- **Overpass timeout when fetching** → the bbox is too large; keep the first fetch to a
  neighborhood or city-center (well under the 50 km² cap).
