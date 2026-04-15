"""LLM-generated analyst questions for a KPI-country-timerange investigation."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import AnalystQuestion
from backend.models.kpi_registry import SPECS_BY_ID, INSIGHT_LENSES, ISO3_TO_NAME

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior macroeconomic research analyst. Given a KPI, country, and time range, \
generate 10 investigative questions that a McKinsey analyst would ask when looking for \
insights in this data. These questions will guide a search for notable data movements \
and their real-world drivers.

Each question should probe a different angle:
- Structural reforms or policy shifts that could move this KPI
- External shocks (commodity prices, pandemics, geopolitical events)
- Cyclical patterns vs secular trends
- Cross-sector or cross-indicator linkages
- Institutional or regulatory changes
- Demographic or social shifts
- Trade and capital flow dynamics
- Comparison with regional/global benchmarks

Questions should be SPECIFIC to the country and KPI, not generic. Reference known \
programs, institutions, or events relevant to this country.

Respond with a JSON array of 10 objects:
{"text": "the question", "focus_area": "one of: structural_change, policy_impact, \
external_shock, cyclical_pattern, institutional_change, demographic_shift, \
trade_dynamics, regional_comparison, sectoral_linkage, fiscal_monetary"}

Return ONLY the JSON array."""


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def generate_analyst_questions(
    kpi_id: str,
    country: str,
    start_year: int,
    end_year: int,
) -> list[AnalystQuestion]:
    """Generate 10 analyst questions for a KPI-country-timerange combination."""
    spec = SPECS_BY_ID.get(kpi_id)
    lens = INSIGHT_LENSES.get(kpi_id)
    country_name = ISO3_TO_NAME.get(country, country)

    kpi_context = ""
    if spec:
        kpi_context += f"KPI: {spec.name}\n"
        kpi_context += f"Indicators: {', '.join(spec.indicators)}\n"
        kpi_context += f"Frequency: {'Quarterly' if spec.frequency == 'Q' else 'Annual'}\n"
        if spec.notes:
            kpi_context += f"Notes: {spec.notes}\n"

    if lens:
        kpi_context += f"\nAnalytical lens: {lens.headline}\n"
        kpi_context += f"What to look for: {'; '.join(lens.notability_cues)}\n"
        if lens.context_hooks:
            kpi_context += f"Relevant context: {'; '.join(lens.context_hooks)}\n"

    user_prompt = (
        f"Country: {country_name} ({country})\n"
        f"Time range: {start_year}–{end_year}\n\n"
        f"{kpi_context}\n"
        f"Generate 10 investigative questions for this KPI-country-timerange combination."
    )

    client = _get_client()

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=2048,
    )
    record_usage(OPENAI_MODEL, response.usage, caller="analyst_questions.generate_analyst_questions")

    raw_text = response.choices[0].message.content or ""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Failed to parse questions JSON: %s", text[:300])
        return []

    if not isinstance(parsed, list):
        parsed = [parsed]

    questions: list[AnalystQuestion] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        questions.append(AnalystQuestion(
            text=item.get("text", ""),
            focus_area=item.get("focus_area", "general"),
        ))

    log.info("Generated %d analyst questions", len(questions))
    return questions
