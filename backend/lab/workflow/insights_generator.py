"""Insights generation step for lab workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.lab.workflow.common import REASONING_MODEL, call_json_model, load_prompt


def run_step(
    *,
    country: str,
    kpi_name: str,
    selected_signals: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    evaluator_feedback: list[str] | None = None,
) -> dict[str, Any]:
    """Generate current and forward-looking KPI insights."""
    playbook = load_prompt("reasoning_playbook.md")
    causal_rules = load_prompt("causal_language_rules.md")
    system_prompt = (
        "You are a macro insights generator.\n"
        "Build concise evidence-backed insights and forward-looking predictions.\n"
        "Return JSON with keys `insights` and `predictions`.\n"
        "Each insight must include `id`, `headline`, `analysis`, `evidence_refs`, `confidence`."
    )
    if playbook:
        system_prompt = f"{system_prompt}\n\n{playbook}"
    if causal_rules:
        system_prompt = f"{system_prompt}\n\n{causal_rules}"

    feedback_block = ""
    if evaluator_feedback:
        feedback_block = (
            "Evaluator revision instructions:\n"
            f"{json.dumps(evaluator_feedback, indent=2, default=str)}\n\n"
            "Apply these revisions before finalizing output.\n\n"
        )

    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name}\n\n"
        f"{feedback_block}"
        "Selected signals:\n"
        f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
        "Hypotheses:\n"
        f"{json.dumps(hypotheses, indent=2, default=str)}\n\n"
        "News evidence:\n"
        f"{json.dumps(evidence_items, indent=2, default=str)}\n\n"
        "Generate 3-5 insights and 2-4 predictions."
    )
    parsed, call_meta = call_json_model(
        model=REASONING_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="lab.insights_generator",
        include_call_meta=True,
    )
    insights = parsed.get("insights", [])
    predictions = parsed.get("predictions", [])
    return {"insights": insights, "predictions": predictions, "call_meta": call_meta}

