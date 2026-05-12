"""Insight quality evaluator for insights workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_json_model, load_prompt


def run_step(
    *,
    country: str,
    kpi_name: str,
    insight_payload: dict[str, Any],
    reasoning_model: str = REASONING_MODEL,
) -> dict[str, Any]:
    """Evaluate insight quality and provide one round of revision feedback."""
    playbook = load_prompt("reasoning_playbook.md")
    causal_rules = load_prompt("causal_language_rules.md")
    system_prompt = (
        "You are a strict macro insight evaluator.\n"
        "Check correctness, causal validity, overreach, and clarity.\n"
        "Return JSON with keys: `score`, `strengths`, `issues`, `revision_instructions`."
    )
    if playbook:
        system_prompt = f"{system_prompt}\n\n{playbook}"
    if causal_rules:
        system_prompt = f"{system_prompt}\n\n{causal_rules}"

    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name}\n\n"
        "Insights to evaluate:\n"
        f"{json.dumps(insight_payload, indent=2, default=str)}\n\n"
        "Be specific and actionable in revision instructions."
    )
    parsed, call_meta = call_json_model(
        model=reasoning_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.evaluator",
        include_call_meta=True,
    )
    return {
        "score": parsed.get("score", 0),
        "strengths": parsed.get("strengths", []),
        "issues": parsed.get("issues", []),
        "revision_instructions": parsed.get("revision_instructions", []),
        "call_meta": call_meta,
    }

