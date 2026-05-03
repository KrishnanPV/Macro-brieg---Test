"""Hypothesis generation step for lab workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.lab.workflow.common import REASONING_MODEL, call_json_model, get_kpi_context, load_prompt


def run_step(
    *,
    country: str,
    kpi_id: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    selected_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate broad causal hypotheses for the selected KPI signals."""
    per_kpi_prompt = load_prompt("per_kpi_context.md")
    kpi_context = get_kpi_context(kpi_id)
    system_prompt = (
        "You are a macro hypothesis generator.\n"
        "Given KPI signal evidence, generate broad but testable causal hypotheses.\n"
        "Return JSON with key `hypotheses` where each item has: "
        "`id`, `title`, `causal_story`, `potential_effects`, `confidence`."
    )
    if per_kpi_prompt:
        system_prompt = f"{system_prompt}\n\n{per_kpi_prompt}"

    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name} ({kpi_id})\n"
        f"Window: {start_year}-{end_year}\n\n"
        f"KPI context:\n{kpi_context}\n\n"
        "Selected signals:\n"
        f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
        "Generate 3-6 hypotheses. Keep them specific enough for evidence checks."
    )
    parsed, call_meta = call_json_model(
        model=REASONING_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="lab.hypotheses_generator",
        include_call_meta=True,
    )
    hypotheses = parsed.get("hypotheses", [])
    if not hypotheses:
        hypotheses = [{
            "id": "hyp_1",
            "title": "Insufficient structured hypotheses from model",
            "causal_story": "Model did not return structured hypotheses. Manual review needed.",
            "potential_effects": [],
            "confidence": "low",
        }]
    return {"hypotheses": hypotheses, "call_meta": call_meta}

