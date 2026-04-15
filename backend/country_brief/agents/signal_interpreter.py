"""Agent 1 — Signal Interpreter.

Takes raw math-detected signals and produces thematic groupings,
noise flags, and cross-KPI connections via a single GPT call.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.models.kpi_registry import ISO3_TO_NAME
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a senior macroeconomic analyst. You will receive raw statistical signals \
detected from KPI time-series data for a specific country.

Your task: interpret and enrich each signal with analytical context. For each signal:
1. Explain what this movement likely means economically
2. Identify the most probable drivers (policies, global events, structural factors)
3. Flag any signals that are likely noise vs genuinely notable
4. Note cross-KPI relationships (e.g. GDP growth + falling unemployment = expansion)

Group related signals into 2-4 thematic narratives (e.g. "Growth & Diversification", \
"Price Stability", "Labor Market Dynamics").

Respond with JSON:
{
  "themes": [
    {
      "title": "theme name",
      "narrative": "2-3 sentences synthesizing the signals in this theme",
      "signal_ids": ["sig_1", "sig_2"],
      "key_drivers": ["driver 1", "driver 2"]
    }
  ],
  "noise_signals": ["sig_id_1"],
  "cross_kpi_connections": [
    {"description": "how KPIs relate", "kpi_ids": ["3", "5"]}
  ]
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


def interpret_signals(
    signals_data: list[dict[str, Any]],
    country: str,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    """Single GPT call: interpret raw math signals into themes."""
    if not signals_data:
        return dict(_EMPTY)

    country_name = ISO3_TO_NAME.get(country, country)
    signals_json = json.dumps(signals_data, indent=2, default=str)

    user_prompt = (
        f"Country: {country_name} ({country})\n"
        f"Time range: {start_year}–{end_year}\n\n"
        f"RAW SIGNALS ({len(signals_data)} detected):\n"
        f"```json\n{signals_json}\n```\n\n"
        "Interpret these signals. Group into themes, identify drivers, "
        "flag noise, and note cross-KPI connections. Return JSON only."
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
