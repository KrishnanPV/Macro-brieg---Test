"""Agent 1 — Signal Interpreter.

Takes raw math-detected signals and produces thematic groupings with
causal chains, noise flags, and cross-KPI connections via a single GPT call.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.models.kpi_registry import ISO3_TO_NAME, INSIGHT_LENSES
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior macroeconomic analyst interpreting statistical signals from KPI \
time-series data for a specific country.

Your task is NOT to describe the data — the charts already do that. Your task is to \
explain the MECHANISMS behind each movement: what triggered it, how the trigger \
transmitted through the economy, and what KPI impact resulted.

For each signal:
1. Identify the specific trigger (a named policy, decision, event, or structural force — \
not a vague category like "government reforms" or "global uncertainties").
2. Articulate the transmission mechanism: HOW does this trigger produce this KPI movement? \
Name the channel (e.g. "OPEC+ cuts reduced extraction volume", "Fed rate hike passed \
through SAR peg to domestic credit conditions").
3. Flag signals that are likely noise vs genuinely notable.
4. Note cross-KPI relationships where one mechanism explains multiple signal movements.

Group related signals into 2-4 thematic narratives. Each theme needs a governing \
thesis (one sentence) and at least one causal chain.

QUALITY STANDARD — each causal chain must pass this test:
"Could someone write this chain by only looking at the chart?"
If yes, it is too shallow. Name the specific trigger and explain the mechanism.

Respond with JSON:
{
  "period_highlight": "One sentence identifying the single most significant economic development in the window — this becomes the governing thought for the brief.",
  "themes": [
    {
      "title": "theme name",
      "thesis": "One-sentence governing thought for this theme",
      "nature": "structural or cyclical — is this theme about a permanent shift or a temporary fluctuation?",
      "causal_chains": [
        {
          "trigger": "Specific named event, policy, or structural force with date/period",
          "mechanism": "How the trigger transmits to KPI impact — name the economic channel",
          "kpi_impact": "The resulting data movement with specific figures from the signals",
          "structural_or_cyclical": "structural or cyclical",
          "signal_ids": ["sig_1", "sig_2"]
        }
      ],
      "key_drivers": ["driver 1", "driver 2"]
    }
  ],
  "noise_signals": ["sig_id_1"],
  "cross_kpi_connections": [
    {"description": "how KPIs relate via shared mechanism", "kpi_ids": ["3", "5"]}
  ],
  "composition_shifts": [
    {"kpi_id": "11", "description": "which sectors gained or lost share and why"}
  ]
}

EXAMPLE 1 — well-formed theme (generic — adapt to actual country context):
{
  "title": "Policy-Driven Structural Shift in Growth Composition",
  "thesis": "Government reform programme is redirecting growth from the traditional \
dominant sector toward emerging sectors, creating divergent sub-aggregate performance.",
  "causal_chains": [
    {
      "trigger": "[Named policy/programme] implemented in [year]",
      "mechanism": "[How the policy transmits to economic activity — name the channel]",
      "kpi_impact": "[Specific KPI movement with numbers from the signals]",
      "structural_or_cyclical": "structural",
      "signal_ids": ["sig_X"]
    }
  ],
  "key_drivers": ["[Named policy 1]", "[Named structural force 2]"]
}

EXAMPLE 2 — well-formed theme for an oil-exporting economy:
{
  "title": "Oil GDP Drag vs Non-Oil Acceleration",
  "thesis": "OPEC+ production discipline is dragging headline growth while diversification \
capex structurally lifts non-oil sectors, creating a two-speed economy.",
  "causal_chains": [
    {
      "trigger": "OPEC+ voluntary production cut of ~1M bpd extended through 2024",
      "mechanism": "Reduced crude extraction volume directly contracted oil GDP (real/volume \
series) — this is a supply constraint, not a price effect",
      "kpi_impact": "Real GDP growth slowed to 0.8% in 2023 despite non-oil GDP accelerating \
above 4%",
      "structural_or_cyclical": "cyclical",
      "signal_ids": ["sig_3", "sig_7"]
    }
  ],
  "key_drivers": ["OPEC+ production policy", "Vision 2030 giga-project execution"]
}

EXAMPLE 3 — well-formed theme for an advanced economy:
{
  "title": "Monetary Tightening Cycle and Demand Cooling",
  "thesis": "Central bank rate hikes transmitted through mortgage and credit channels to \
compress household demand, pulling inflation down but exposing labour market fragility.",
  "causal_chains": [
    {
      "trigger": "Central bank raised policy rate by 525bp between 2022 and 2024",
      "mechanism": "Higher borrowing costs reduced mortgage origination and consumer credit, \
contracting interest-sensitive demand components",
      "kpi_impact": "Private consumption growth slowed from 4.2% to 1.1% while CPI inflation \
eased from 9.1% to 2.5%",
      "structural_or_cyclical": "cyclical",
      "signal_ids": ["sig_5", "sig_8"]
    }
  ],
  "key_drivers": ["Monetary policy tightening", "Mortgage rate pass-through"]
}

Return ONLY the JSON object."""


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _model_kwargs(model: str) -> dict[str, Any]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.3}


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return text


_EMPTY: dict[str, Any] = {"themes": [], "noise_signals": [], "cross_kpi_connections": []}


def _build_lens_context(notable_kpi_ids: list[str]) -> str:
    """Build per-KPI domain context from insight lenses for the interpreter."""
    blocks: list[str] = []
    for kpi_id in notable_kpi_ids:
        lens = INSIGHT_LENSES.get(kpi_id)
        if not lens:
            continue
        lines = [f"KPI {kpi_id} — {lens.headline}:"]
        if lens.context_hooks:
            lines.append("  Relevant context to consider:")
            for hook in lens.context_hooks:
                lines.append(f"    - {hook}")
        if lens.notability_cues:
            lines.append("  What counts as notable:")
            for cue in lens.notability_cues:
                lines.append(f"    - {cue}")
        if lens.forbidden_claims:
            lines.append("  Analytical pitfalls to avoid:")
            for fc in lens.forbidden_claims:
                lines.append(f"    - {fc}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def interpret_signals(
    signals_data: list[dict[str, Any]],
    country: str,
    start_year: int,
    end_year: int,
    *,
    notable_kpi_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Single GPT call: interpret raw math signals into themes with causal chains."""
    if not signals_data:
        return dict(_EMPTY)

    country_name = ISO3_TO_NAME.get(country, country)
    signals_json = json.dumps(signals_data, indent=2, default=str)

    lens_block = ""
    if notable_kpi_ids:
        lens_text = _build_lens_context(notable_kpi_ids)
        if lens_text:
            lens_block = (
                "\n\nDOMAIN CONTEXT — use these per-KPI analytical lenses to inform "
                "your interpretation. They contain the specific policies, programs, and "
                "mechanisms most likely to explain movements in each KPI:\n\n"
                f"{lens_text}\n"
            )

    user_prompt = (
        f"Country: {country_name} ({country})\n"
        f"Time range: {start_year}–{end_year}\n\n"
        f"RAW SIGNALS ({len(signals_data)} detected):\n"
        f"```json\n{signals_json}\n```"
        f"{lens_block}\n\n"
        "Interpret these signals. For each theme, provide a governing thesis and "
        "at least one causal chain (trigger -> mechanism -> KPI impact). "
        "Flag noise and note cross-KPI connections. Return JSON only."
    )

    client = _get_client()

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            **_model_kwargs(OPENAI_MODEL),
        )

        record_usage(OPENAI_MODEL, response.usage, caller="signal_interpreter.interpret_signals")
        text = _strip_code_fence((response.choices[0].message.content or "").strip())
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            parsed = dict(_EMPTY)

        log.info(
            "Signal interpretation: %d themes, %d noise, %d cross-KPI connections",
            len(parsed.get("themes", [])),
            len(parsed.get("noise_signals", [])),
            len(parsed.get("cross_kpi_connections", [])),
        )
        return parsed

    except Exception:
        log.exception("Signal interpretation failed")
        return dict(_EMPTY)
