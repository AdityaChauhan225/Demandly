# Hosting Guide for Demandly

Demandly is configured to deploy directly to modern cloud Platforms-as-a-Service (**Render**, **Railway**, or **Fly.io**) straight from your GitHub repository: [`https://github.com/AdityaChauhan225/Demandly`](https://github.com/AdityaChauhan225/Demandly).

The application runs as a **unified full-stack Docker service** that serves both the compiled **React 19 + deck.gl analytics dashboard** and the **FastAPI geospatial backend** on a single public port.

---

## Deployment Modes

Demandly can run in two ways on cloud platforms:

| Mode | Database | Cache | Cost | Setup Effort | Best For |
|---|---|---|---|---|---|
| **Zero-Config Standalone** | Bundled SQLite (`geodemand.db` pre-seeded with 1M events) | In-memory FakeRedis | **100% Free** | **1-Click** | Demos, portfolios, quick testing |
| **Full Production Stack** | Managed PostgreSQL 16 | Managed Redis 7 | Free/Starter tier | 2-Clicks | Production ingestion, high throughput |

---

## Option 1: Deploy on Render (Recommended — Free Tier)

Render can deploy the application automatically using the repository's `render.yaml` Blueprint or as an individual Web Service.

### Method A: 1-Click Blueprint (Easiest)

1. **Push the latest changes to GitHub**:
   ```bash
   git add .
   git commit -m "Configure cloud hosting for Render and Railway"
   git push origin main
   ```
2. Open [dashboard.render.com](https://dashboard.render.com/) and log in with your GitHub account.
3. Click the **"New +"** button in the top navigation bar and select **"Blueprint"**.
4. Select your repository: `AdityaChauhan225/Demandly`.
5. Render will automatically detect [`render.yaml`](./render.yaml).
6. Click **"Apply"**.
7. Render will build the multi-stage Docker container and give you a public URL (e.g. `https://demandly.onrender.com`).

---

### Method B: Manual Web Service on Render

If you prefer to configure it manually:

1. In the Render Dashboard, click **"New +"** → **"Web Service"**.
2. Connect your repository: `AdityaChauhan225/Demandly`.
3. Fill in the service details:
   - **Name:** `demandly`
   - **Language / Runtime:** `Docker`
   - **Region:** Choose closest to your users (e.g., `Oregon (US West)` or `Frankfurt (EU Central)`)
   - **Branch:** `main`
   - **Instance Type:** `Free` (or `Starter`)
4. Under **Advanced** / **Environment Variables**, add:
   - `ALLOWED_ORIGIN`: `*`
   - `PRIVACY_K`: `5`
   - `PRIVACY_EPSILON`: `1.0`
   - `PRIVACY_SALT`: *(Click generate or enter a random string)*
   - `CACHE_TTL_SECONDS`: `300`
5. Click **"Deploy Web Service"**.

> [!NOTE]
> On Render's Free tier, services spin down after 15 minutes of inactivity. When a new request arrives, it may take ~30–50 seconds for the initial cold start, after which responses are fast and cached.

---

## Option 2: Deploy on Railway (Ultra Fast)

Railway provides sub-minute Docker deployments with optional 1-click Postgres and Redis plugins.

1. Go to [railway.app](https://railway.app/) and sign in with GitHub.
2. Click **"+ New Project"** → **"Deploy from GitHub repo"**.
3. Select `AdityaChauhan225/Demandly`.
4. Railway will detect [`railway.json`](./railway.json) and the [`Dockerfile`](./Dockerfile).
5. Click **"Deploy Now"**.
6. Once deployed:
   - Go to your service's **Settings** tab → **Networking** → **Generate Domain** (gives you a public `*.up.railway.app` URL).
7. *(Optional: Add Full Postgres + Redis Stack)*:
   - In the same Railway canvas, click **"+ New"** → **"Database"** → **"Add PostgreSQL"**.
   - Click **"+ New"** → **"Database"** → **"Add Redis"**.
   - In your `demandly` service settings, reference the environment variables:
     - Set `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
     - Set `REDIS_URL` = `${{Redis.REDIS_URL}}`
   - Railway will redeploy and switch from the SQLite/FakeRedis fallback to the dedicated PostgreSQL and Redis instances.

---

## Option 3: Deploy on Fly.io (CLI Container Hosting)

If you have the `flyctl` CLI installed:

1. In the project root, run:
   ```bash
   fly launch --name demandly --region ord
   ```
2. When prompted:
   - Select **Docker** (it detects `Dockerfile`).
   - Choose whether to attach a Postgres database or use SQLite.
3. Deploy:
   ```bash
   fly deploy
   ```

---

## Environment Variables Reference

| Variable | Default Value | Description |
|---|---|---|
| `PORT` | `8000` (dynamic on cloud) | Port for Uvicorn to bind to (automatically set by Render/Railway). |
| `DATABASE_URL` | *(SQLite fallback)* | PostgreSQL connection URI (`postgresql://user:pass@host:5432/dbname`). |
| `REDIS_URL` | *(FakeRedis fallback)* | Redis connection URI (`redis://host:6379/0`). |
| `ALLOWED_ORIGIN` | `*` | Allowed CORS origins for API requests. |
| `PRIVACY_K` | `5` | K-anonymity suppression threshold ($K \ge 5$). |
| `PRIVACY_EPSILON` | `1.0` | Laplace noise privacy budget ($\epsilon$). |
| `PRIVACY_SALT` | `demandly-production-salt` | Secret salt for deterministic DP Laplace noise generation. |
| `CACHE_TTL_SECONDS` | `300` | Redis / memory cache expiration window. |
| `MAX_CELLS` | `5000` | Maximum cells returned per query window. |
| `INGEST_API_KEY` | `demandly-key` | Bearer token required for `POST /api/v1/ingest/batch`. |

---

## Verifying Your Live Deployment

Once your service has deployed, check these URLs using your assigned public domain (e.g. `https://your-app.onrender.com`):

1. **Dashboard UI:**
   ```
   https://your-app.onrender.com/
   ```
   *Expected:* Loads the dark-mode interactive deck.gl map, time slider, category selector, and top zones ranking.

2. **Health Check:**
   ```
   https://your-app.onrender.com/health
   ```
   *Expected:* `{"status":"healthy","postgres":true,"redis":true,"backend_mode":"online"}`

3. **Metadata Endpoint:**
   ```
   https://your-app.onrender.com/api/v1/meta
   ```
   *Expected:* JSON containing categories (`cab`, `food`, `grocery`, `pharmacy`), total cell count, and privacy parameters.

4. **API Interactive Documentation:**
   ```
   https://your-app.onrender.com/docs
   ```
   *Expected:* FastAPI Swagger UI with all available endpoints.
