"""News corroboration step for lab workflow."""
from __future__ import annotations

import json
from typing import Any

from backend.lab.workflow.common import NEWS_MODEL, call_json_model


def run_step(
    *,
    country: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use Perplexity Sonar to find evidence for generated hypotheses."""
    if not hypotheses:
        return {"evidence_items": [], "research_notes": "No hypotheses to validate.", "call_meta": None}

    system_prompt = (
        "You are a macro news researcher using web search evidence.\n"
        "For each hypothesis, find concrete corroborating or contradicting evidence.\n"
        "Return JSON with keys: `evidence_items` (array) and `research_notes` (string).\n"
        "Each evidence item must include `hypothesis_id`, `stance`, `summary`, `date`, "
        "`source`, and `url`."
    )
    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name}\n"
        f"Window: {start_year}-{end_year}\n\n"
        "Hypotheses:\n"
        f"{json.dumps(hypotheses, indent=2, default=str)}\n\n"
        "Use high-quality sources. Return 6-12 evidence items total."
    )
    parsed, call_meta = call_json_model(
        model=NEWS_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="lab.news_researcher",
        use_perplexity=True,
        include_call_meta=True,
    )
    evidence_items = parsed.get("evidence_items", [])
    if not evidence_items and parsed.get("items"):
        evidence_items = parsed["items"]
    return {
        "evidence_items": evidence_items,
        "research_notes": parsed.get("research_notes", ""),
        "call_meta": call_meta,
    }

