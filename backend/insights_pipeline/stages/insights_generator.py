"""Insights generation step for insights workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_json_model, load_prompt


def run_step(
    *,
    country: str,
    kpi_name: str,
    selected_signals: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    evaluator_feedback: list[str] | None = None,
    generation_mode: str = "deep",
    reasoning_model: str = REASONING_MODEL,
) -> dict[str, Any]:
    """Generate current and forward-looking KPI insights."""
    system_base = load_prompt("system_base.md")
    playbook = load_prompt("reasoning_playbook.md")
    causal_rules = load_prompt("causal_language_rules.md")
    if generation_mode == "light":
        system_prompt = (
            "You are a macro insights generator.\n"
            "Produce an executive summary for one KPI with only the main decision-relevant points.\n"
            "Ensure the points are anchored with numbers and evidence and do not simply say things like:\n"
            "'Recent inflection point'. State when and what the inflection was.\n"
            "Return JSON with key `executive_summary` as an array of 3-5 concise bullet strings."
        )
    else:
        system_prompt = (
            "You are a macro insights generator.\n"
            "Build concise evidence-backed insights and forward-looking predictions.\n"
            "Return JSON with keys `insights` and `predictions`.\n"
            "Each insight must include `id`, `headline`, `analysis`, `evidence_refs`, `confidence`."
        )
    if system_base:
        system_prompt = f"{system_prompt}\n\n{system_base}"
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

    if generation_mode == "light":
        user_prompt = (
            f"Country: {country}\n"
            f"KPI: {kpi_name}\n\n"
            "Selected signals:\n"
            f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
            "Hypotheses:\n"
            f"{json.dumps(hypotheses, indent=2, default=str)}\n\n"
            "News evidence:\n"
            f"{json.dumps(evidence_items, indent=2, default=str)}\n\n"
            "Generate only 3-5 executive summary bullets for this KPI."
        )
    else:
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
        model=reasoning_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.insights_generator",
        include_call_meta=True,
    )
    if generation_mode == "light":
        executive_summary = parsed.get("executive_summary", [])
        if not isinstance(executive_summary, list):
            executive_summary = []
        if not executive_summary and parsed.get("items"):
            executive_summary = [str(item) for item in parsed.get("items", []) if str(item).strip()]
        return {"executive_summary": executive_summary[:5], "call_meta": call_meta}
    insights = parsed.get("insights", [])
    predictions = parsed.get("predictions", [])
    return {"insights": insights, "predictions": predictions, "call_meta": call_meta}

