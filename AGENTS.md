# Codebase Agent Index

This file documents the current project structure and the purpose of each file, organized folder-by-folder.

## `backend/country_brief`

- `backend/country_brief/__init__.py` - Package marker for the country brief module.
- `backend/country_brief/router.py` - FastAPI routes for country brief generation, refinement, and benchmark recomputation.
- `backend/country_brief/pipeline.py` - Main country brief orchestration pipeline and NDJSON event stream builder.
- `backend/country_brief/prompts.py` - Prompt assembly helpers for brief writing, benchmark logic, and refinement context.
- `backend/country_brief/brief_writer.py` - Streaming brief writer and parser for sectioned country brief markdown output.
- `backend/country_brief/benchmark_selector.py` - Benchmark-country selection logic (deterministic and optional LLM-assisted modes).
- `backend/country_brief/fdi_benchmark.py` - FDI benchmark payload shaping and time-slice utilities.
- `backend/country_brief/kpi_triage.py` - Country-brief KPI scoring and notability triage rules.
- `backend/country_brief/metrics_ribbon.py` - Metrics ribbon computation for summary KPI cards in brief output.
- `backend/country_brief/_test_report.json` - Local debug/test artifact used by country brief debug workflows.

### `backend/country_brief/composition`

- `backend/country_brief/composition/__init__.py` - Package marker for composition utilities.
- `backend/country_brief/composition/aggregated_insights.py` - Stage-driven aggregation/composition logic that builds thematic insight bundles for briefs.

### `backend/country_brief/tests`

- `backend/country_brief/tests/test_aggregated_insights.py` - Tests for aggregated insight composition behavior.

## `backend/dashboard`

- `backend/dashboard/__init__.py` - Package marker for dashboard-specific backend code.
- `backend/dashboard/router.py` - Dashboard insight API routes (`/api/dashboard/insights/*`).
- `backend/dashboard/schemas.py` - Pydantic request models for dashboard country and cross-country insight calls.
- `backend/dashboard/pipeline.py` - Dashboard orchestration that runs `insights_pipeline` stages and composes markdown/news payloads for the UI.

## `backend/insights_pipeline`

- `backend/insights_pipeline/__init__.py` - Package boundary declaration for reusable insight stages.
- `backend/insights_pipeline/BOUNDARIES.md` - Allowed/forbidden dependency contract for the pipeline package.

### `backend/insights_pipeline/prompts`

- `backend/insights_pipeline/prompts/manifest.yaml` - Prompt manifest and version metadata used by runtime loader.
- `backend/insights_pipeline/prompts/PROMPT_CHANGES.md` - Prompt change log and rationale history.
- `backend/insights_pipeline/prompts/system_base.md` - Base stage system behavior guidance.
- `backend/insights_pipeline/prompts/style_guide.md` - Style constraints for generated narrative output.
- `backend/insights_pipeline/prompts/per_kpi_context.md` - KPI-context instruction template for hypothesis generation.
- `backend/insights_pipeline/prompts/reasoning_playbook.md` - Reasoning checklist/playbook for stage outputs.
- `backend/insights_pipeline/prompts/causal_language_rules.md` - Causality phrasing and quality rules for insight text.

### `backend/insights_pipeline/runtime`

- `backend/insights_pipeline/runtime/__init__.py` - Runtime package marker.
- `backend/insights_pipeline/runtime/prompt_loader.py` - Prompt loading and manifest resolution helpers.

### `backend/insights_pipeline/stages`

- `backend/insights_pipeline/stages/__init__.py` - Stage package marker and exports.
- `backend/insights_pipeline/stages/common.py` - Shared model-call helpers, prompt loading, usage accounting, and constants.
- `backend/insights_pipeline/stages/signal_extractor.py` - Deterministic signal extraction plus model-assisted relevance triage.
- `backend/insights_pipeline/stages/hypotheses_generator.py` - Causal hypothesis generation from selected signals.
- `backend/insights_pipeline/stages/news_researcher.py` - Evidence collection via Perplexity/Sonar for hypothesis validation.
- `backend/insights_pipeline/stages/insights_generator.py` - Insight and prediction generation stage.
- `backend/insights_pipeline/stages/evaluator.py` - Quality evaluator stage that emits revision instructions.
- `backend/insights_pipeline/stages/brief_writer.py` - Reusable brief-writing stage for structured final markdown.

## `backend/services` (shared/global only)

- `backend/services/__init__.py` - Package marker for shared services.
- `backend/services/knoema_client.py` - Oxford Economics/Knoema data access client wrappers.
- `backend/services/news_client.py` - News fetch, ranking, normalization, and catalog shaping helpers.
- `backend/services/derived_facts.py` - Deterministic KPI-derived analytics used across modules.
- `backend/services/cost_tracker.py` - Usage and cost logging with pricing metadata and reporting queries.

## `backend/routers` (general-purpose routers)

- `backend/routers/__init__.py` - Package marker for shared routers.
- `backend/routers/data.py` - KPI catalog and KPI data fetch/refetch API endpoints.
- `backend/routers/workspace.py` - Workspace CRUD API endpoints and persistence bridge.
- `backend/routers/costs.py` - Cost log and usage summary API endpoints.

## `backend/models` (general-purpose models/schemas)

- `backend/models/__init__.py` - Package marker for models.
- `backend/models/db.py` - SQLAlchemy models/session setup and workspace persistence logic.
- `backend/models/schemas.py` - Shared API request/response schemas (data, workspace, country brief).
- `backend/models/kpi_registry.py` - KPI metadata registry and lookup helpers.
- `backend/models/insights.py` - Domain models for insight-related typed structures.

## `backend/tools` (supplementary/offline tooling)

### `backend/tools/reasoning_distillation`

- `backend/tools/reasoning_distillation/__init__.py` - Package marker for reasoning-distillation scripts.
- `backend/tools/reasoning_distillation/run_annotation.py` - Extracts report excerpts and writes structured annotation JSONL.
- `backend/tools/reasoning_distillation/synthesize_patterns.py` - Synthesizes a reasoning playbook from annotation rows.

### `backend/tools/reasoning_distillation/prompts`

- `backend/tools/reasoning_distillation/prompts/annotation_prompt_v1.md` - System prompt for excerpt annotation.
- `backend/tools/reasoning_distillation/prompts/pattern_synthesis_prompt_v1.md` - System prompt for reasoning pattern synthesis.

### `backend/tools/reasoning_distillation/annotations`

- `backend/tools/reasoning_distillation/annotations/imf_reasoning_units_v1.jsonl` - Distillation annotation dataset artifact.

### `backend/tools/reasoning_distillation/outputs`

- `backend/tools/reasoning_distillation/outputs/reasoning_playbook_v1.md` - Generated reasoning playbook artifact.

### `backend/tools/reasoning_distillation/corpus/imf_article_iv/raw`

- `backend/tools/reasoning_distillation/corpus/imf_article_iv/raw/.gitkeep` - Placeholder to keep the raw corpus directory in git.
- `backend/tools/reasoning_distillation/corpus/imf_article_iv/raw/*.pdf` - Raw IMF Article IV source PDFs used for extraction experiments.

### `backend/tools/reasoning_distillation/corpus/imf_article_iv/excerpts`

- `backend/tools/reasoning_distillation/corpus/imf_article_iv/excerpts/.gitkeep` - Placeholder to keep the excerpts directory in git.
- `backend/tools/reasoning_distillation/corpus/imf_article_iv/excerpts/*.txt` - Extracted text excerpts generated from raw IMF PDF inputs.

## `backend` root files

- `backend/__init__.py` - Backend package marker.
- `backend/app.py` - FastAPI app factory and router registration.
- `backend/config.py` - Environment-based configuration constants.

## `frontend`

- `frontend/.gitignore` - Frontend-specific ignore rules.
- `frontend/package.json` - Frontend dependency and script manifest.
- `frontend/package-lock.json` - Locked frontend dependency graph.
- `frontend/eslint.config.js` - ESLint configuration for frontend code.
- `frontend/vite.config.js` - Vite dev/build configuration.
- `frontend/index.html` - Frontend HTML entry template.
- `frontend/public/favicon.svg` - Browser favicon asset.

### `frontend/src`

- `frontend/src/main.jsx` - React bootstrap entrypoint.
- `frontend/src/App.jsx` - Route-level app composition.
- `frontend/src/WorkspaceShell.jsx` - Top-level workspace shell and app chrome.
- `frontend/src/index.css` - Global frontend styles.

### `frontend/src/stores`

- `frontend/src/stores/workspaceStore.js` - Workspace state/actions and API integration.
- `frontend/src/stores/dataStore.js` - Dashboard data selection/fetch/cache state.
- `frontend/src/stores/countryBriefStore.js` - Country brief generation and UI state.

### `frontend/src/components/ui`

- `frontend/src/components/ui/ChartFrequencyToggle.jsx` - Frequency toggle control reused by dashboard/brief.
- `frontend/src/components/ui/ClipboardCopyButton.jsx` - Reusable copy-to-clipboard button.
- `frontend/src/components/ui/InsightSections.jsx` - Markdown-to-section renderer for insight blocks.
- `frontend/src/components/ui/InsightTabs.jsx` - Tab component used by dashboard insight panes.
- `frontend/src/components/ui/SourceChip.jsx` - Inline source citation chip with hover/open behavior.
- `frontend/src/components/ui/SourcesDrawer.jsx` - Drawer listing all source citations for an insight.

### `frontend/src/lib`

- `frontend/src/lib/colors.js` - Shared color constants.
- `frontend/src/lib/formatNumbers.js` - Numeric formatting utilities for charts/text.
- `frontend/src/lib/interleaveSources.jsx` - Inline source-marker parsing/render helpers.

### `frontend/src/views/Landing`

- `frontend/src/views/Landing/Landing.jsx` - Landing page mode selector.

### `frontend/src/views/Dashboard`

- `frontend/src/views/Dashboard/Dashboard.jsx` - Dashboard page layout and KPI card orchestration.
- `frontend/src/views/Dashboard/KpiCard.jsx` - KPI chart card and dashboard insight request/render flow.

### `frontend/src/views/CountryBrief`

- `frontend/src/views/CountryBrief/CountryBrief.jsx` - Country brief page container and orchestration.
- `frontend/src/views/CountryBrief/BriefSidebar.jsx` - Country brief controls/settings sidebar.

### `frontend/src/views/CountryBrief/blocks`

- `frontend/src/views/CountryBrief/blocks/ExecSummaryBlock.jsx` - Executive summary block renderer.
- `frontend/src/views/CountryBrief/blocks/FdiBenchmarkChart.jsx` - FDI benchmark chart block renderer.
- `frontend/src/views/CountryBrief/blocks/InlineChartBlock.jsx` - Generic inline chart block renderer.
- `frontend/src/views/CountryBrief/blocks/MetricsRibbon.jsx` - Metrics ribbon block renderer.
- `frontend/src/views/CountryBrief/blocks/NarrativeBlock.jsx` - Narrative paragraph/section block renderer.
- `frontend/src/views/CountryBrief/blocks/OutlookBlock.jsx` - Outlook section block renderer.
- `frontend/src/views/CountryBrief/blocks/SectionDivider.jsx` - Section divider/decorative separator block.
- `frontend/src/views/CountryBrief/blocks/TriagePanel.jsx` - KPI triage panel renderer.

## `frontend-lab`

- `frontend-lab/package.json` - Sandbox frontend dependency and script manifest.
- `frontend-lab/package-lock.json` - Locked dependency graph for sandbox UI.
- `frontend-lab/vite.config.js` - Vite config for sandbox build/dev.
- `frontend-lab/index.html` - Sandbox HTML entry.
- `frontend-lab/src/main.jsx` - Sandbox React bootstrap.
- `frontend-lab/src/App.jsx` - Sandbox app view.
- `frontend-lab/src/styles.css` - Sandbox styles.
- `frontend-lab/dist/index.html` - Built sandbox HTML artifact.
- `frontend-lab/dist/assets/index-*.js` - Built sandbox JavaScript bundle artifact.
- `frontend-lab/dist/assets/index-*.css` - Built sandbox stylesheet bundle artifact.

## Other top-level files and folders

- `README.md` - Main project documentation and setup guide.
- `launch.py` - Convenience runner for backend + frontend dev startup.
- `requirements.txt` - Python dependency list.
- `.env.example` - Environment variable template.
- `.gitignore` - Root ignore rules.
- `CHECK.md` - Local checklist/scratch path note.
- `.env` - Local environment configuration (developer machine specific).
- `data/` - Runtime database/artifact directory used by local runs.
- `docs/` - Documentation folder (currently empty in this workspace state).
- `.cursor/` - Local Cursor metadata/configuration.
- `.venv/` - Local Python virtual environment directory.
- `.pytest_cache/` - Local pytest cache directory.

