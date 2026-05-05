"""Integrity checks for lab prompt manifest."""
from __future__ import annotations

import json

from backend.insights_pipeline.stages.common import PROMPTS_DIR

VALID_WORKFLOW_STEPS = {
    "signal_extractor",
    "hypotheses_generator",
    "news_researcher",
    "insights_generator",
    "evaluator",
    "brief_writer",
}


def _load_manifest() -> dict:
    manifest_path = PROMPTS_DIR / "manifest.yaml"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_prompt_manifest_references_existing_files():
    manifest = _load_manifest()
    prompts = manifest.get("prompts", [])
    assert prompts, "manifest.yaml must define at least one prompt entry."

    for prompt in prompts:
        file_name = prompt["file"]
        prompt_path = PROMPTS_DIR / file_name
        assert prompt_path.exists(), f"Prompt file not found: {file_name}"
        text = prompt_path.read_text(encoding="utf-8").strip()
        assert text, f"Prompt file is empty: {file_name}"


def test_prompt_manifest_step_names_are_valid():
    manifest = _load_manifest()
    for prompt in manifest.get("prompts", []):
        for step in prompt.get("used_by", []):
            assert step in VALID_WORKFLOW_STEPS, f"Unknown workflow step in manifest: {step}"


def test_manifest_has_versioned_model_profile():
    manifest = _load_manifest()
    assert manifest.get("prompt_bundle_version"), "prompt_bundle_version is required."
    models = manifest.get("models", {})
    assert models.get("reasoning"), "reasoning model is required."
    assert models.get("brief_writer"), "brief_writer model is required."
    assert models.get("news_researcher"), "news_researcher model is required."

