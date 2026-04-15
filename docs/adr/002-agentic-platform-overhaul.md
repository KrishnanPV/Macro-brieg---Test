# ADR-002: Agentic Research Platform — Architectural Overhaul

**Status:** Accepted

**Date:** 2026-04-06

**Authors:** Johann Sylvester, AI Assistant

---

## Context

The Macrobrief tool began as a single-page KPI Explorer: a monolithic `main_api.py` (2146 lines) serving data and insights, and a monolithic `App.jsx` (~960 lines) rendering charts with a sidebar. No persistence, no routing, no workspace concept.

The goal is to transform this into a multi-module research workspace — a "personal research intelligence platform" — where analysts can explore macro data, converse with an AI agent, build knowledge graphs, compose briefs, generate flash cards, export to PowerPoint, and ingest custom context. All state must be persisted per-workspace.

This ADR documents the key architectural decisions made during the overhaul.

---

## Decision Records

### DR-1: Backend Architecture — Monolith vs. Modular Package

**Options:**

| Option | Description |
|--------|-------------|
| (a) | Keep `main_api.py` and add new endpoints to it |
| (b) | Split into a `backend/` package with routers, services, and models |
| (c) | Microservices — separate FastAPI apps per domain |

**Chosen:** **(b)** — Modular package with `backend/app.py` as the entry point.

**Rationale:** The monolith was already at 2146 lines and would grow to 5000+ with workspace/graph/flashcard endpoints. Microservices add deployment complexity (multiple ports, service discovery) that is not justified for a single-analyst local tool. A modular package gets the separation-of-concerns benefits while keeping deployment trivial (`uvicorn backend.app:app`).

**Structure adopted:**
- `routers/` — one file per API domain (data, insights, workspace, graph, flashcards, export)
- `services/` — business logic decoupled from HTTP (knoema_client, news_client, agent, derived_facts, export_engine)
- `models/` — Pydantic schemas, SQLAlchemy models, KPI registry
- `prompts/` — system prompts and prompt assembly (separated from business logic)
- `config.py` — centralized `.env` loading

**Consequences:**
- `main_api.py` is retained for reference but no longer used
- `launch.py` updated to point to `backend.app:app`
- All imports use `backend.` prefix — the project root must be on `PYTHONPATH` (handled by running from project root)

---

### DR-2: Persistence — SQLite + SQLAlchemy (Async)

**Options:**

| Option | Description |
|--------|-------------|
| (a) | No persistence — keep everything in memory |
| (b) | JSON files on disk |
| (c) | SQLite via SQLAlchemy (sync) |
| (d) | SQLite via SQLAlchemy (async with aiosqlite) |
| (e) | PostgreSQL |

**Chosen:** **(d)** — SQLite via async SQLAlchemy with `aiosqlite`.

**Discarded:**
- **(a)** Status quo — unacceptable for a workspace-based tool; all work lost on restart.
- **(b)** JSON files — no query capability, no referential integrity, difficult to manage concurrent writes.
- **(c)** Sync SQLAlchemy — blocks the event loop during DB operations, degrading streaming performance for concurrent requests.
- **(e)** PostgreSQL — adds external dependency and configuration; overkill for single-analyst local use.

**Rationale:** SQLite is zero-config (single file, auto-created), sufficient for single-analyst throughput, and provides real SQL with transactions and referential integrity. Async via `aiosqlite` ensures DB operations don't block the event loop during streaming AI responses. SQLAlchemy provides ORM benefits (type safety, relationship management, migration path).

**Consequences:**
- Database file at `data/macrobrief.db` (gitignored)
- Tables created automatically on startup via `Base.metadata.create_all` in the lifespan handler
- No formal migration tool for V1 — schema changes require DB deletion and recreation
- SQLAlchemy's `metadata` attribute conflicts with user-facing `metadata` properties on models — resolved by using `cell_meta`, `node_meta`, `edge_meta` as property names

---

### DR-3: Frontend Architecture — Multi-View Workspace

**Options:**

| Option | Description |
|--------|-------------|
| (a) | Tab-based layout within a single React component |
| (b) | React Router with a shared shell and nested routes |
| (c) | Separate SPAs per feature |

**Chosen:** **(b)** — React Router with `WorkspaceShell` as the layout route.

**Rationale:** URL-based routing enables deep linking, browser history navigation, and clean separation between views. The `WorkspaceShell` provides consistent navigation and workspace selection across all views. Zustand stores persist state across route transitions without prop drilling.

**Route structure:**
- `/` — Dashboard (KPI Explorer)
- `/notebook` — Research Notebook
- `/graph` — Knowledge Graph
- `/news` — News Lab
- `/briefs` — Brief Builder
- `/flashcards` — Flash Cards

**Consequences:**
- Vite needs `historyApiFallback` for client-side routing in dev mode
- State that spans views (workspace context, selected countries/KPIs) lives in Zustand stores, not component state
- The original `App.jsx` (960 lines) was decomposed into ~15 component files across 6 view directories

---

### DR-4: State Management — Zustand

**Options:**

| Option | Description |
|--------|-------------|
| (a) | React Context + useReducer |
| (b) | Zustand |
| (c) | Redux Toolkit |
| (d) | Jotai / Recoil |

**Chosen:** **(b)** — Zustand.

**Rationale:** Minimal boilerplate (~10 lines to define a store), no providers/wrappers needed, excellent React 19 compatibility, built-in `devtools` middleware, and supports persistence out of the box. Redux Toolkit adds unnecessary ceremony for this scale. Context + useReducer forces re-renders on the entire subtree.

**Stores created:**
- `workspaceStore.js` — workspace CRUD, active workspace selection
- `dataStore.js` — KPI catalog, country/KPI selection, fetched results, time range

---

### DR-5: Knowledge Graph — React Flow

**Options:**

| Option | Description |
|--------|-------------|
| (a) | D3.js force-directed graph |
| (b) | vis.js Network |
| (c) | React Flow (`@xyflow/react`) |
| (d) | Cytoscape.js |

**Chosen:** **(c)** — React Flow.

**Rationale:** Native React component model — custom nodes are just React components with Tailwind styling that match the rest of the UI. Built-in support for handles (connection points), edge drawing, controls, minimap, and background patterns. Dagre layout integration available for tree/DAG arrangement. Active maintenance and large community.

**Node types implemented:**
- `KpiMovementNode` — blue, trend arrow icon
- `EventNode` — red, lightning icon
- `PolicyNode` — green, shield icon
- `InsightNode` — purple, lightbulb icon

**Edge types:** caused_by (solid blue), correlated_with (dashed amber, animated), led_to (solid green), sourced_from (solid gray).

---

### DR-6: Agentic AI — OpenAI Function Calling with Streaming

**Options:**

| Option | Description |
|--------|-------------|
| (a) | Keep single-prompt streaming (V1 approach) |
| (b) | OpenAI function calling with a multi-step tool loop |
| (c) | LangChain / LangGraph agent framework |
| (d) | Custom agent loop with raw OpenAI API |

**Chosen:** **(d)** — Custom agent loop using OpenAI's native function calling, combined with **(a)** for backward-compatible insight endpoints.

**Discarded:**
- **(c)** LangChain — heavy dependency, opinionated abstractions, version churn. The tool-calling loop is ~80 lines of straightforward code; a framework adds indirection without proportionate benefit.

**Rationale:** Direct use of OpenAI's `tools` parameter keeps the agent transparent, debuggable, and framework-free. The streaming loop collects tool call fragments, executes tools, appends results to the conversation, and loops until the model produces a final text response. Maximum 5 iterations prevents runaway loops.

**Tools available to the agent:**
- `fetch_kpi_data` — pull data from Oxford/Knoema
- `search_news` — search Newscatcher via the existing scoring pipeline
- `compute_statistics` — run derived facts computation
- `create_graph_node` — add to the knowledge graph
- `create_flash_card` — generate a flash card

**Streaming protocol:** NDJSON (newline-delimited JSON) with chunk types: `text`, `tool_call`, `tool_result`, `done`, `error`. The frontend renders tool call indicators (tool name + spinner) before the final response streams.

**Backward compatibility:** The existing `/api/insights` and `/api/insights/kpi` endpoints are preserved unchanged — they use the same prompt assembly and streaming but without the tool-calling loop. The new `/api/agent/chat` endpoint enables the full agentic pipeline.

---

### DR-7: Flash Cards — SM-2 Spaced Repetition

**Options:**

| Option | Description |
|--------|-------------|
| (a) | Simple random review |
| (b) | Leitner box system |
| (c) | SM-2 algorithm (SuperMemo 2) |
| (d) | FSRS (Free Spaced Repetition Scheduler) |

**Chosen:** **(c)** — SM-2.

**Rationale:** SM-2 is the algorithm behind Anki, the most widely used spaced repetition tool. It's simple to implement (~20 lines), well-understood, and sufficient for the use case. FSRS is newer and potentially better but adds complexity and is less familiar to users. The SM-2 parameters (ease factor, interval, repetitions) are stored per card and updated after each review.

**Review ratings:** 0-5 quality scale, mapped to UI buttons: Again (1), Hard (3), Good (4), Easy (5).

---

### DR-8: Export — python-pptx for PowerPoint

**Options:**

| Option | Description |
|--------|-------------|
| (a) | python-pptx (pure Python) |
| (b) | Google Slides API |
| (c) | LibreOffice headless conversion |
| (d) | Client-side JS PPTX generation |

**Chosen:** **(a)** — python-pptx.

**Rationale:** Mature library, full control over slide layout, no external service dependency. Runs entirely server-side. Briefs are structured as sections with titles, text, and bullet points — a natural fit for slide generation.

**Export formats supported:** PPTX (binary download), Markdown (text), JSON (raw brief data).

**Deferred:** PDF export (requires `weasyprint` or `xhtml2pdf`, which have system-level dependencies). Chart image embedding (requires server-side Matplotlib rendering).

---

## Migration Notes

### From V1 to V2

- The original `main_api.py` is retained for reference but is **not loaded or imported** by the new stack.
- `launch.py` now starts `backend.app:app` instead of `main_api:app`.
- `requirements.txt` replaces `requirements-web.txt` with additional dependencies: `sqlalchemy`, `aiosqlite`, `python-pptx`, `openai`.
- The `.env` file is unchanged — all existing variables are read by `backend/config.py`.
- Frontend dependencies were added via npm: `react-router-dom`, `zustand`, `@xyflow/react`, `@tiptap/react`, `@tiptap/starter-kit`, `lucide-react`, `dagre`.
- The monolithic `App.jsx` has been replaced by a router-based setup — the original content is now in `views/Dashboard/Dashboard.jsx` and `views/Dashboard/KpiCard.jsx`.

### Data

- No data migration needed — V1 had no persistence.
- SQLite database is created on first run at `data/macrobrief.db`.
- Database file is gitignored.

---

## Deferred / Future Work

| Item | Description |
|------|-------------|
| TipTap rich text | Replace plain `<textarea>` in notebook markdown cells with full TipTap editor (slash commands, markdown shortcuts) |
| Dagre auto-layout | Add button to auto-arrange knowledge graph nodes using dagre algorithm |
| Timeline overlay | Position graph nodes chronologically on a horizontal time axis |
| AI graph seeding | When insights are generated, have the agent auto-extract entities and relationships into the knowledge graph |
| News article persistence | Store scored articles in SQLite so the News Lab has content between sessions |
| Brief AI polish | Endpoint where the agent refines/restructures a draft brief |
| PDF export | Add `weasyprint` or `xhtml2pdf` for PDF generation |
| Chart image embedding | Server-side Matplotlib rendering for embedding charts in PPT/PDF exports |
| Context document chunking | Split large uploaded documents into overlapping chunks for better AI retrieval |
| Drag-and-drop brief composition | Drag insight cells, chart snapshots from notebook into brief sections |
| Code splitting | Dynamic `import()` for view-level code splitting to reduce initial bundle size |
