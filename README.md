# Macro Brief — Agentic Research Platform

A multi-module research workspace for macroeconomic analysis. Analysts select an economy and time range, then the platform fetches Oxford Economics KPI data, scores indicator notability, pulls real-time news context, and generates executive-ready country briefs — or lets users explore data freely on a multi-country dashboard with per-KPI AI insights. The workspace also provides an agentic notebook, a knowledge graph, a news lab, and a brief builder with PowerPoint export, all persisted per-workspace in SQLite.

---

## Architecture

```
 Browser (React 19 + Vite)                    FastAPI backend (modular)
 ┌─────────────────────────────┐               ┌───────────────────────────────┐
 │  WorkspaceShell             │               │  backend/app.py               │
 │  ├─ Landing (mode picker)   │               │  ├─ routers/data.py           │──▸ Knoema (Oxford EAP)
 │  ├─ Country Brief (doc)     │───REST+NDJSON─│  ├─ routers/country_brief.py  │──▸ KPI triage + LLM
 │  ├─ Dashboard (KPI cards)   │               │  ├─ routers/insights.py       │──▸ OpenAI (chat + tools)
 │  ├─ Notebook (scratchpad)   │               │  ├─ routers/workspace.py      │──▸ SQLite (via SQLAlchemy)
 │  ├─ Knowledge Graph         │               │  ├─ routers/graph.py          │
 │  ├─ News Lab                │               │  └─ routers/export.py         │──▸ python-pptx
 │  └─ Brief Builder           │◂──────────────│                               │
 └─────────────────────────────┘               └───────────────────────────────┘
         Zustand (3 stores)                            SQLite DB
         React Router (7 routes)                     data/macrobrief.db
         React Flow (graph)
         McKinsey-themed palette
```

### Module overview

| View | Route | Purpose |
|------|-------|---------|
| **Landing** | `/` | Mode selector — choose *Country Brief* (single economy, all KPIs) or *Dashboard* (multi-country, user-picked KPIs) |
| **Country Brief** | `/country-brief` | Automated executive narrative: metrics ribbon, executive summary, themed sections with inline charts, forward outlook, section-level AI refinement via sidebar chat |
| **Dashboard** | `/dashboard` | Country/KPI selector with region grouping, area/line/bar charts (drag-to-zoom, clickable legend), per-KPI streaming AI insights with single-country, cross-country, and per-country tabs, insight caching, grid/stack layout toggle |
| **Notebook** | `/notebook` | NotebookLM-style scratchpad with markdown, AI chat (agentic tool-calling with workspace context injection), data, insight, and source cells. Context injection via document uploads |
| **Knowledge Graph** | `/graph` | React Flow canvas with custom node types (KPI Movement, Event, Policy, Insight) and edge types (caused by, correlated with, led to, sourced from). Auto-build from KPI data. Persisted per workspace |
| **News Lab** | `/news` | Article feed powered by the Newscatcher scoring pipeline — country filter, scored/ranked results, error banners, auto-load on workspace change |
| **Brief Builder** | `/briefs` | Template-based brief composition (Country Overview, Comparative Analysis, Thematic Deep-Dive). Section editor with bullet management. PPT, Markdown, and JSON export |

### Backend package structure

```
backend/
  app.py                     # FastAPI app factory, CORS, lifespan (DB init + migration)
  config.py                  # Settings from .env (EAP, OpenAI, Newscatcher, DATABASE_URL)
  routers/
    data.py                  # GET /api/kpis, POST /api/fetch, POST /api/fetch-kpi
    insights.py              # POST /api/insights, /insights/kpi, /insights/kpi/country,
                             #   /insights/kpi/cross-country, /agent/chat, /news/lab
    workspace.py             # CRUD: workspaces (with country_brief state), notebook cells,
                             #   context documents
    graph.py                 # CRUD: knowledge graph nodes/edges + POST .../auto-build
    export.py                # CRUD: briefs + GET .../export/{pptx|markdown|json}
    country_brief.py         # POST /api/country-brief/generate (NDJSON streaming),
                             #   POST /api/country-brief/refine
  services/
    knoema_client.py         # Oxford EAP / Knoema data fetching
    news_client.py           # Newscatcher fetching + scoring pipeline
    agent.py                 # Agentic AI: tool-calling loop, streaming, insight generation,
                             #   single-country / cross-country prompt builders
    derived_facts.py         # CAGR, inflection points, trend segments
    kpi_triage.py            # Deterministic notability scoring (threshold, min/max notable)
    metrics_ribbon.py        # Headline metrics from latest-vs-prior data (not LLM-generated)
    export_engine.py         # python-pptx and Markdown generation
  models/
    schemas.py               # Pydantic request/response models (all endpoints, including
                             #   SingleCountryKpiInsightRequest, CrossCountryInsightRequest,
                             #   CountryBriefGenerateRequest, CountryBriefRefineRequest)
    db.py                    # SQLAlchemy async models + engine (SQLite + aiosqlite),
                             #   auto-migration for schema evolution
    kpi_registry.py          # KpiSpec, InsightLens, KpiNewsQuery, country lookups
  prompts/
    system.py                # System prompt, lens assembly, per-request task instructions,
                             #   cross-country addendum, analyst-grade prompting rules
    brief_prompts.py         # Country Brief document prompt with marker contract,
                             #   thematic section menu, synthesis rules
```

### Frontend structure

```
frontend/src/
  App.jsx                    # BrowserRouter, 7 routes under WorkspaceShell
  WorkspaceShell.jsx         # Layout: McKinsey-themed nav, workspace selector with
                             #   inline delete, debounced workspace sync, store hydration
  index.css                  # Tailwind @theme with mck-* palette tokens
  lib/colors.js              # MCK, SERIES_COLORS, CARD_ACCENT constants
  stores/
    workspaceStore.js        # Workspace CRUD, active workspace state
    dataStore.js             # KPI data, country/KPI selections, insight cache, hydration
    countryBriefStore.js     # Country Brief state, NDJSON streaming, block parsing
  components/ui/
    InsightSections.jsx      # Markdown-ish rendering with Summary/Key Findings/Implications
                             #   structure and full-body fallback
    InsightTabs.jsx          # Per-country + cross-country insight tabs with streaming
    ClipboardCopyButton.jsx  # Copy-to-clipboard utility
  views/
    Landing/Landing.jsx                        # Mode picker (Country Brief vs Dashboard)
    Dashboard/Dashboard.jsx                    # Sidebar, summary bar, grid toggle
    Dashboard/KpiCard.jsx                      # Area/line/bar charts, drag-zoom, legend
                                               #   toggle, insight cache, multi-tab insights
    CountryBrief/CountryBrief.jsx              # Brief document shell, generate/regenerate
    CountryBrief/BriefSidebar.jsx              # Section discussion + streaming refinement
    CountryBrief/blocks/MetricsRibbon.jsx      # Headline KPI ribbon (semantic green/red)
    CountryBrief/blocks/ExecSummaryBlock.jsx   # Executive summary card
    CountryBrief/blocks/NarrativeBlock.jsx     # Themed narrative section
    CountryBrief/blocks/InlineChartBlock.jsx   # [CHART:kpi_id] inline time-series
    CountryBrief/blocks/OutlookBlock.jsx       # Forward outlook card
    CountryBrief/blocks/SectionDivider.jsx     # Visual divider
    CountryBrief/blocks/TriagePanel.jsx        # Collapsible KPI notability panel
    Notebook/Notebook.jsx                      # Cell-based scratchpad
    Notebook/cells/AICell.jsx                  # Agent chat with NDJSON buffering
    KnowledgeGraph/KnowledgeGraph.jsx          # React Flow canvas + auto-build
    NewsLab/NewsLab.jsx                        # Newscatcher-powered article feed
    BriefBuilder/BriefBuilder.jsx              # Template-based brief editor + export
```

---

## Prerequisites

- **Python 3.10+** with a virtual environment
- **Node.js 18+** and npm

## Credentials

All credentials are read from `.env` at server startup — nothing is entered from the browser:

| Variable | Purpose |
|----------|---------|
| `EAP_HOST` | Oxford Economics EAP hostname |
| `EAP_APP_ID` | Knoema application ID |
| `EAP_APP_SECRET` | Knoema application secret |
| `OPENAI_API_KEY` | OpenAI (or compatible) API key |
| `OPENAI_BASE_URL` | Optional custom base URL for OpenAI-compatible providers |
| `OPENAI_MODEL` | Model name (default: `gpt-4o-mini`) |
| `NEWSCATCHER_API_KEY` | Newscatcher v3 API key |
| `DATABASE_URL` | SQLAlchemy connection string (default: `sqlite+aiosqlite:///./data/macrobrief.db`) |

## Running locally

### Option A: Single command (recommended)

```bash
# From the workspace root
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
cd frontend && npm install && cd ..

python launch.py
```

`launch.py` starts the FastAPI backend on port 8000, polls `GET /api/kpis` until it returns 200 (up to 90 s), then starts the Vite dev server. Both processes are stopped together with Ctrl+C.

### Option B: Separate terminals

**Terminal 1 — Backend:**

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser. The Vite dev server proxies `/api/*` to the backend on port 8000.

## Using the app

1. Open **http://localhost:5173** — the **Landing** page presents two modes.

2. **Country Brief** — select an economy and date range, optionally provide an analyst focus (themes to emphasize), then click **Generate**. The server fetches all KPI data, scores notability, pulls Newscatcher news for the most notable indicators, and streams an NDJSON pipeline that the UI parses into a block-based document:
   - **Metrics Ribbon** — headline figures with semantic arrows (green/red respects KPI polarity), computed deterministically from data rather than by the LLM.
   - **Executive Summary** — synthesized overview paragraph.
   - **Themed Sections** — Growth & Output, Inflation & Prices, Labour Market, External Sector, Fiscal Position, Monetary Policy, Financial Markets (unused sections are omitted by the model).
   - **Inline Charts** — `[CHART:kpi_id]` markers render mini time-series from cached data.
   - **Forward Outlook** — forward-looking assessment.
   - **Section Refinement** — click any section in the sidebar to discuss it with the AI and stream a revised version, grounded in the original data.

3. **Dashboard** — select countries (grouped by region) and KPIs (with search and select-all), choose stack or grid layout, and click **Load / Refresh Data** to fetch time-series from Oxford Economics.
   - **Charts** — default area chart with drag-to-zoom and clickable legend; line and bar alternatives available.
   - **Insights** — single country: streaming AI insight panel. Multiple countries: tabbed interface with per-country tabs (`/insights/kpi/country`), a cross-country comparison tab (`/insights/kpi/cross-country`), and per-tab copy/regenerate. Insights are cached per-session and persist across tab switches.

4. **Workspace** — use the workspace selector (top-right) to create or delete workspaces. Workspaces persist notebook cells, graph nodes, briefs, country/KPI selections, and Country Brief configuration (country, year range, focus). Selections sync to the backend with debounced PATCH requests.

5. **Notebook** — add markdown notes, AI chat cells (with agentic tool-calling that receives workspace context: selected countries, KPIs, and recent data points), or data cells. Upload context documents in the sidebar to give the AI additional source material. NDJSON responses are buffered across chunk boundaries for robust streaming.

6. **Knowledge Graph** — add KPI Movement, Event, Policy, or Insight nodes. Draw edges between them. Drag to reposition; positions persist. **Auto-build from data** generates KPI Movement nodes and correlated-with edges from loaded KPI results and derived facts.

7. **News Lab** — select a KPI and the backend runs `compute_derived_facts`, `fetch_news_for_kpi`, and `synthesize_news_context` via the Newscatcher scoring pipeline. Articles are returned scored and ranked, filterable by country, with clear messages for missing API keys or empty results.

8. **Brief Builder** — create briefs from templates, edit sections, export to PowerPoint, Markdown, or JSON.

## API endpoints

### Data

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/kpis` | List available KPI definitions |
| POST | `/api/fetch` | Fetch time-series for countries × KPIs |
| POST | `/api/fetch-kpi` | Fetch a single KPI (supports frequency toggle) |

### Insights

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/insights` | General streaming insight |
| POST | `/api/insights/kpi` | Per-KPI streaming insight (single or multi-country) |
| POST | `/api/insights/kpi/country` | Single-country KPI insight (filters series to one country) |
| POST | `/api/insights/kpi/cross-country` | Cross-country comparative insight |
| POST | `/api/agent/chat` | Agentic notebook chat with tool-calling |
| POST | `/api/news/lab` | Newscatcher-powered article scoring for News Lab |

### Country Brief

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/country-brief/generate` | Full brief generation (NDJSON streaming) |
| POST | `/api/country-brief/refine` | Section-scoped streaming refinement |

### Workspaces

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/workspaces` | Create workspace |
| GET | `/api/workspaces` | List workspaces |
| GET | `/api/workspaces/{ws_id}` | Get workspace |
| PATCH | `/api/workspaces/{ws_id}` | Update workspace (countries, KPIs, country_brief) |
| DELETE | `/api/workspaces/{ws_id}` | Delete workspace |
| GET/POST | `/api/workspaces/{ws_id}/cells` | List / create notebook cells |
| PATCH/DELETE | `/api/workspaces/{ws_id}/cells/{cell_id}` | Update / delete cell |
| GET/POST | `/api/workspaces/{ws_id}/documents` | List / upload context documents |
| DELETE | `/api/workspaces/{ws_id}/documents/{doc_id}` | Delete document |

### Knowledge Graph

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/api/workspaces/{ws_id}/graph/nodes` | List / create nodes |
| PATCH/DELETE | `/api/workspaces/{ws_id}/graph/nodes/{node_id}` | Update / delete node |
| GET/POST | `/api/workspaces/{ws_id}/graph/edges` | List / create edges |
| DELETE | `/api/workspaces/{ws_id}/graph/edges/{edge_id}` | Delete edge |
| POST | `/api/workspaces/{ws_id}/graph/auto-build` | Auto-generate nodes/edges from KPI data |

### Briefs (export)

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/api/workspaces/{ws_id}/briefs` | List / create briefs |
| GET/PATCH/DELETE | `/api/workspaces/{ws_id}/briefs/{brief_id}` | Read / update / delete |
| GET | `/api/workspaces/{ws_id}/briefs/{brief_id}/export/{fmt}` | Export (pptx, markdown, json) |

## Key dependencies

### Backend

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | API server |
| `knoema` | Oxford Economics EAP data access |
| `openai` | LLM chat completions + function calling |
| `sqlalchemy` + `aiosqlite` | Async SQLite persistence with auto-migration |
| `python-pptx` | PowerPoint export |
| `pandas` | Data manipulation and derived facts |
| `requests` | Newscatcher API calls |
| `python-dotenv` | Environment variable loading |

### Frontend

| Package | Purpose |
|---------|---------|
| `react` 19 + `vite` 8 | UI framework and build tool |
| `react-router-dom` | Client-side routing (7 routes) |
| `zustand` | Lightweight global state management (3 stores) |
| `@xyflow/react` | Knowledge graph canvas (React Flow) |
| `@tiptap/react` | Rich text editor (notebook cells) |
| `recharts` | Time-series charts (area, line, bar) |
| `lucide-react` | Icon library |
| `tailwindcss` 4 | Utility-first CSS with McKinsey-themed `@theme` |
| `@dagrejs/dagre` + `dagre` | Graph auto-layout |

## Data persistence

All workspace data is stored in `data/macrobrief.db` (SQLite, auto-created on first run, gitignored). The `init_db()` function creates all tables and runs lightweight migrations for schema evolution (e.g. adding `country_brief_json` to existing databases).

### Tables

- `workspaces` — named research projects with country/KPI selections and Country Brief configuration (`country_brief_json` stores country, year range, and analyst focus)
- `notebook_cells` — ordered cells per workspace (markdown, AI, data, insight, source)
- `context_documents` — uploaded text documents for AI context injection
- `graph_nodes` / `graph_edges` — knowledge graph per workspace
- `flashcard_decks` / `flashcards` — legacy tables retained for schema compatibility (Flash Cards feature removed from the UI and router)
- `briefs` — composed documents with section content

## Architecture Decision Records

The project maintains ADRs in `docs/adr/`:

| ADR | Title | Date | Summary |
|-----|-------|------|---------|
| 001 | Newscatcher Integration and News-Data Fusion | 2026-04-06 | Scoring pipeline, KPI-to-query mapping, news enrichment for insights |
| 002 | Agentic Research Platform — Architectural Overhaul | 2026-04-06 | Modular backend, SQLite persistence, workspace model, tool-calling agent |
| 003 | Country Brief Page and Automated Brief Generation | 2026-04-07 | Marker-based LLM contract, NDJSON pipeline, deterministic triage, block UI |

## Notes

- **KPI 10** (GDP contribution / NEA) is IMF-sourced and not available via Oxford EAP. It appears disabled in the KPI selector.
- **Flash Cards** — the feature has been removed from the UI and its router is no longer mounted, but the DB models and router module are retained. The flash card route and agent tool were dropped in favour of the Country Brief and graph auto-build features.
- The original monolithic `main_api.py` is retained for reference but is no longer used — `launch.py` now points to `backend.app:app`.
- **Insight prompting** has been extensively tightened: strict `## Summary / ## Key Findings / ## Implications` structure, temporal coverage mandates, named-policy and transmission-channel requirements, Newscatcher-preferred citation rules, and GOOD/BAD examples baked into the system prompt.
- **gpt-5 compatibility**: the backend handles the `temperature` parameter correctly for models that do not support it (gpt-5 and above).

## Changelog (since v0 — platform overhaul)

| Date | Commit | Change |
|------|--------|--------|
| Apr 6 | `1357b80` | Agentic research platform: modular backend, SQLite, workspace UI |
| Apr 7 | `7f34b0e` | KPI-driven graph auto-build, workspace–data sync, remove Flash Cards |
| Apr 7 | `fe84777` | Analyst-grade insight prompt engineering |
| Apr 7 | `abf5028` | Landing page, Country Brief view, single- vs cross-country insight APIs |
| Apr 7 | `821e31f` | McKinsey-themed palette, insight caching, drag-to-zoom charts, workspace country_brief state |
| Apr 7 | `46f1a3b` | Fix: workspace schema migration for legacy databases |
| Apr 7 | `5f8cb4b` | News Lab Newscatcher API, insight markdown fallback, robust NDJSON parse |
| Apr 7 | `cfa08d4` | Country Brief generation pipeline, block-based UI, metrics ribbon, sidebar refinement |
| Apr 7 | `9fc94f4` | ADR-003: Country Brief page and automated generation |
