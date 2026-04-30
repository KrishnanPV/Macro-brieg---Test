# Macro Brief

Oxford Economics KPI data, a **multi-country Dashboard** with streaming AI insights per KPI, and an automated **Country Brief** (metrics ribbon, themed sections, inline charts, optional deep analysis with Perplexity news). Workspaces persist country/KPI selections and brief settings in SQLite.

### Using this README after you pull the branch

Follow **Setup from scratch** below in order. You need **Python 3.10+**, **Node 18+**, a filled-in **`.env`** (copy from **`.env.example`**), and a **`data/`** folder before **`python launch.py`**. The rest of this file is reference: how the app is structured, credentials, quick API list, and where files live on disk.

### In plain terms: what this repo is for

You run **one backend** (Python) and **one frontend** (the website). Everything in `backend/` and `frontend/src/` is there to support **Landing**, **Dashboard**, **Country Brief**, **workspaces**, and **API keys / data fetching**. Nothing else is required for that.

**Already removed (not needed for the app):** old `lab/` scripts, long internal docs under `docs/`, unused images, extra npm packages (TipTap, React Flow, Dagre), and database definitions for removed features (notebook, flashcards, graph, etc.).

**Still here on purpose:** A small SQL cleanup when you **delete a workspace**, so an older `macrobrief.db` file does not leave orphan rows that could block deletes. That is not a separate feature—it only supports workspace delete.

---

## Architecture

```
 Browser (React + Vite)              FastAPI backend
 ┌─────────────────────────┐         ┌──────────────────────────────┐
 │ WorkspaceShell          │         │ backend/app.py               │
 │ ├─ Landing              │ REST /  │ ├─ routers/data.py           │ → Knoema (Oxford EAP)
 │ ├─ Country Brief        │ NDJSON  │ ├─ routers/insights.py       │ → OpenAI
 │ └─ Dashboard            │────────▶│ ├─ routers/workspace.py      │ → SQLite
 │                         │         │ ├─ routers/costs.py          │
 └─────────────────────────┘         │ └─ country_brief/router.py │ → brief pipeline
         │                             └──────────────────────────────┘
         └── Zustand stores (workspace, data, countryBrief)
```

### Routes (frontend)

| View | Path | Purpose |
|------|------|---------|
| **Landing** | `/` | Choose Country Brief or Dashboard |
| **Country Brief** | `/country-brief` | Generate/regenerate brief; section refine sidebar |
| **Dashboard** | `/dashboard` | Multi-country KPI charts; streaming insights |

### Backend layout

```
backend/
  app.py                 # FastAPI app, CORS, lifespan
  config.py              # .env settings
  routers/
    data.py              # KPIs, fetch, refetch
    insights.py          # POST .../insights/kpi, .../country, .../cross-country
    workspace.py         # /api/workspaces CRUD
    costs.py             # usage / costs
  country_brief/         # generate (NDJSON), refine, FDI benchmark helpers
  services/              # knoema, derived_facts, triage, agent, news_client, metrics_ribbon, …
  models/                # schemas, db (SQLAlchemy), kpi_registry
  prompts/system.py      # dashboard insight prompts
```

### Frontend layout

```
frontend/src/
  App.jsx                  # Routes: Landing, Dashboard, Country Brief
  WorkspaceShell.jsx       # Nav, workspaces, sync to API
  stores/                  # workspaceStore, dataStore, countryBriefStore
  views/Landing/           # Mode picker
  views/Dashboard/         # KpiCard, charts, insight tabs
  views/CountryBrief/      # Brief document, InlineChartBlock, sidebar refine
  components/ui/         # InsightSections, InsightTabs, …
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm

## Setup from scratch

1. **Clone** the repo and open a terminal at the project root. If you need this trimmed branch explicitly:

   ```bash
   git checkout trimmed-codebase
   ```

2. **Python virtual environment** (recommended):

   ```bash
   python -m venv .venv
   ```

   Activate it:

   - **Windows (PowerShell):** `.\.venv\Scripts\Activate.ps1`
   - **macOS / Linux:** `source .venv/bin/activate`

3. **Install backend dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Install frontend dependencies:**

   ```bash
   cd frontend && npm install && cd ..
   ```

5. **Environment variables** — copy the template and add your own keys (nothing secret ships in git):

   ```bash
   cp .env.example .env
   ```

   Windows **cmd**: `copy .env.example .env` — **PowerShell**: `Copy-Item .env.example .env`

   Edit `.env`. See **Credentials** below and inline comments in [`.env.example`](.env.example).

6. **Database directory** — default SQLite path is `./data/macrobrief.db`. Create the folder once so the file can be created:

   ```bash
   mkdir -p data
   ```

   On Windows PowerShell: `New-Item -ItemType Directory -Force data`

7. **Run** (starts API on **8000**, then Vite dev server, usually **5173**):

   ```bash
   python launch.py
   ```

   Open **http://localhost:5173**. Stop with **Ctrl+C**.

   Optional: `python launch.py --debug` (extra test-report toggles where implemented).

**Manual split** (two terminals):  
`python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000`  
and `cd frontend && npm run dev`

## Credentials (`.env`)

All variables are listed in [`.env.example`](.env.example). You **must** supply your own values there (or in the environment); the repo does not include secrets.

| Variable | Purpose |
|----------|---------|
| `EAP_HOST`, `EAP_APP_ID`, `EAP_APP_SECRET` | Oxford Economics EAP / Knoema |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` (optional), `OPENAI_MODEL` | LLM |
| `NEWSCATCHER_API_KEY` | News context for dashboard insights |
| `PERPLEXITY_API_KEY`, `PERPLEXITY_URL` (optional), `PERPLEXITY_MODEL` (optional) | Country Brief deep analysis |
| `DATABASE_URL` | Default: `sqlite+aiosqlite:///./data/macrobrief.db` |
| `LAST_ACTUAL_YEAR` | Optional; default `2025` |
| `MACROBRIEF_DEBUG` | Set to `1` for optional debug behavior |
| `BENCHMARK_USE_LLM` | Set to `1` to use GPT for FDI benchmark peers (default is deterministic) |

**If something fails:** confirm the venv is active, `pip` and `npm` installs finished without errors, `.env` has real keys for EAP + OpenAI + Newscatcher (Perplexity only needed for Country Brief deep mode), ports **8000** and **5173** are free, and you ran commands from the **repository root** (same folder as `launch.py`).

**Optional — static frontend build:** `cd frontend && npm run build` writes `frontend/dist/` for hosting behind a real server; you must configure API URL / proxy for your deployment.

---

## Using the app

1. **Country Brief** — pick country, years, optional focus; **Generate**. Charts use cached KPI series; **Demographics** uses KPI **9** (population) when that series was fetched (include KPI 9 in **manual** KPI mode).

2. **Dashboard** — pick countries and KPIs, fetch data, open per-KPI insights (streaming).

3. **Workspaces** — create/switch workspaces; selections sync to the backend.

---

## API (implemented)

### Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kpis` | KPI definitions |
| POST | `/api/fetch` | Fetch series |
| POST | `/api/fetch-kpi` | Single KPI refetch |

### Insights

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/insights/kpi` | Streaming insight for one KPI |
| POST | `/api/insights/kpi/country` | Same, series filtered to one country |
| POST | `/api/insights/kpi/cross-country` | Cross-country comparison |

### Country Brief

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/country-brief/generate` | NDJSON stream |
| POST | `/api/country-brief/refine` | Section refinement |
| … | (see OpenAPI) | FDI benchmark slice, debug test report, KPI catalog |

### Workspaces

| Method | Path | Description |
|--------|------|-------------|
| POST / GET | `/api/workspaces` | Create / list |
| GET / PATCH / DELETE | `/api/workspaces/{ws_id}` | Read / update / delete |

### Costs

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/costs` | Usage log (if enabled) |

---

## Persistence

- **`data/macrobrief.db`** — saved **workspaces** (countries, KPIs, brief settings). Created when you use the app.
- **`data/cost_log.db`** — optional **LLM usage** log.

Both live under **`data/`** (usually gitignored). If your database was created long ago, extra empty tables might still exist inside the file; they are ignored by the app and cleaned up when you delete a workspace.

## Repository layout (root)

| Path | Role |
|------|------|
| [`launch.py`](launch.py) | Starts API (port 8000) then Vite dev server |
| [`backend/`](backend/) | FastAPI app — routers, country brief pipeline, services, models |
| [`frontend/`](frontend/) | React UI — `npm run dev` / `npm run build` |
| [`data/`](data/) | Runtime SQLite databases (gitignored); do not delete while using saved workspaces |
| [`requirements.txt`](requirements.txt) | Python dependencies |
| [`.env.example`](.env.example) | Template for local `.env` (copy to `.env`, add keys) |

There is no `lab/` folder in this repo (optional scratch scripts were removed). **`docs/`** was removed; use this README + source for behavior.
