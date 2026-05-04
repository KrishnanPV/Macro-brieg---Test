# Lab Backend Index

Purpose: quick file map for agents and developers working in `backend/lab`.

## Root
- `__init__.py` - Marks `backend.lab` as a package.
- `schemas.py` - Request/event schemas for lab HTTP endpoints.
- `router.py` - FastAPI routes (`/api/lab/health`, `/api/lab/generate`).
- `pipeline.py` - Top-level stage orchestration and NDJSON event streaming.
- `REPO.md` - This index file.

## Workflow
- `workflow/__init__.py` - Marks workflow steps package.
- `workflow/common.py` - Shared clients, model constants, prompt loaders, NDJSON helper.
- `workflow/signal_extractor.py` - Deterministic signal detection + LLM relevance filtering.
- `workflow/hypotheses_generator.py` - Generates broad causal hypotheses from selected signals.
- `workflow/news_researcher.py` - Uses Perplexity Sonar to corroborate/refute hypotheses.
- `workflow/insights_generator.py` - Produces evidence-backed insights and forward-looking predictions.
- `workflow/evaluator.py` - Evaluates insight quality and emits one-pass revision feedback.
- `workflow/brief_writer.py` - Writes final markdown brief from finalized pipeline output.

## Prompts
- `prompts/manifest.yaml` - Prompt bundle metadata, version, model profile, usage map.
- `prompts/PROMPT_CHANGES.md` - Append-only log for prompt edits and rationale.
- `prompts/system_base.md` - Base behavioral instructions for lab LLM steps.
- `prompts/style_guide.md` - Writing tone/format guidance for final brief output.
- `prompts/per_kpi_context.md` - KPI-aware hypothesis generation guidance.
- `prompts/reasoning_playbook.md` - Reasoning checklist for insights/evaluation steps.
- `prompts/causal_language_rules.md` - Causality wording and confidence constraints.

## Tests
- `tests/test_prompt_manifest_integrity.py` - Verifies manifest references and workflow mapping validity.
- `tests/test_prompt_bundle_snapshot.py` - Snapshot guard for prompt bundle hash/shape changes.
- `tests/test_signal_extractor.py` - Verifies phase-based signal profiling across full periods.
- `tests/fixtures/prompt_bundle_snapshot.json` - Expected prompt bundle snapshot fixture.

## Reasoning Distillation
- `reasoning_distillation/__init__.py` - Package marker for IMF reasoning distillation scripts.
- `reasoning_distillation/run_annotation.py` - Extracts capped PDF excerpts and annotates reasoning units into JSONL.
- `reasoning_distillation/synthesize_patterns.py` - Synthesizes recurring reasoning patterns into a playbook draft.
- `reasoning_distillation/prompts/annotation_prompt_v1.md` - Annotation system prompt with the canonical IMF schema.
- `reasoning_distillation/prompts/pattern_synthesis_prompt_v1.md` - Synthesis system prompt for playbook generation.
- `reasoning_distillation/corpus/imf_article_iv/raw/.gitkeep` - Placeholder for raw IMF Article IV PDF inputs.
- `reasoning_distillation/corpus/imf_article_iv/excerpts/.gitkeep` - Placeholder for generated excerpt text files.
- `reasoning_distillation/annotations/imf_reasoning_units_v1.jsonl` - Output annotations JSONL artifact.
- `reasoning_distillation/outputs/reasoning_playbook_v1.md` - Generated reasoning playbook draft output.

Maintenance note: whenever a new file is added under `backend/lab`, add one line here in the same section.

