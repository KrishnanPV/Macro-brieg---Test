"""Brief writing step for insights workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.insights_pipeline.stages.common import BRIEF_MODEL, call_text_model, load_prompt


def run_step(
    *,
    country: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    selected_signals: list[dict[str, Any]],
    final_insights: dict[str, Any],
    evaluator_output: dict[str, Any] | None = None,
    generation_mode: str = "deep",
    brief_model: str = BRIEF_MODEL,
) -> dict[str, Any]:
    """Generate final markdown brief text from finalized insights."""
    system_base = load_prompt("system_base.md")
    style_guide = load_prompt("style_guide.md")
    if generation_mode == "light":
        system_prompt = (
            "You are a macro brief writer. Write a tightly scoped markdown output for one KPI.\n"
            "Structure: Executive Summary only.\n"
            "Keep it concise and focused on main points; avoid detailed section expansion."
        )
    else:
        system_prompt = (
            "You are a macro brief writer. Write clear, concise prose in markdown.\n"
            "Structure: Executive Summary, Signal Interpretation, Corroborating Evidence, "
            "Forward Look, Risks."
        )
    if system_base:
        system_prompt = f"{system_prompt}\n\n{system_base}"
    if style_guide:
        system_prompt = f"{system_prompt}\n\n{style_guide}"

    if generation_mode == "light":
        user_prompt = (
            f"Country: {country}\n"
            f"KPI focus: {kpi_name}\n"
            f"Window: {start_year}-{end_year}\n\n"
            "Selected signals:\n"
            f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
            "Executive summary points:\n"
            f"{json.dumps(final_insights, indent=2, default=str)}\n\n"
            "Write only an Executive Summary section with 3-5 bullets and a short closing sentence."
        )
    else:
        user_prompt = (
            f"Country: {country}\n"
            f"KPI focus: {kpi_name}\n"
            f"Window: {start_year}-{end_year}\n\n"
            "Selected signals:\n"
            f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
            "Final insights and predictions:\n"
            f"{json.dumps(final_insights, indent=2, default=str)}\n\n"
            "Evaluator notes:\n"
            f"{json.dumps(evaluator_output or {}, indent=2, default=str)}\n\n"
            "Write one cohesive brief."
        )
    brief_text, call_meta = call_text_model(
        model=brief_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.brief_writer",
        include_call_meta=True,
    )
    return {"brief_markdown": brief_text, "call_meta": call_meta}

