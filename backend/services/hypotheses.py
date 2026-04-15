"""LLM-generated hypotheses (causes & effects) for filtered signals."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import (
    AnalystQuestion,
    Hypothesis,
    Signal,
    SignalHypotheses,
)

log = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior macroeconomic analyst. You will receive a list of SIGNALS — notable \
statistical movements in a KPI — and ANALYST QUESTIONS guiding this investigation.

For EACH signal, produce:
1. 10 potential CAUSES — real-world events, policies, or shocks that could have \
produced this data movement. Focus on the time window BEFORE the signal.
2. 10 potential EFFECTS — consequences or downstream impacts that this data movement \
might trigger. Focus on the time window AFTER the signal.
3. A single CONSOLIDATED SEARCH QUERY — a rich, multi-angle search string that \
combines all 20 hypotheses into one query suitable for a web search API. This query \
should be 40-80 words, using OR-separated phrases, covering the country name, the KPI \
topic, and key terms from both causes and effects. Include year references from the \
signal's time window. Do NOT use boolean AND — just a natural, keyword-rich query.

For time windows:
- Causes: start 1 year before the signal's from_date, end at the signal's from_date
- Effects: start at the signal's to_date, end 1 year after the signal's to_date

Respond with a JSON array (one entry per signal):
{
  "signal_id": "...",
  "causes": [
    {"text": "hypothesis text", "time_window": ["2020-01", "2021-06"]}
  ],
  "effects": [
    {"text": "hypothesis text", "time_window": ["2022-01", "2023-06"]}
  ],
  "consolidated_search_query": "rich multi-angle query string"
}

Return ONLY the JSON array."""


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def generate_hypotheses(
    signals: list[Signal],
    questions: list[AnalystQuestion],
    kpi_name: str,
    country: str,
) -> list[SignalHypotheses]:
    """Single batched LLM call to generate hypotheses for all filtered signals."""
    if not signals:
        return []

    signals_block = json.dumps(
        [{"signal_id": s.signal_id, "type": s.signal_type,
          "description": s.description, "from_date": s.from_date,
          "to_date": s.to_date, "magnitude_pct": s.magnitude_pct,
          "kpi_name": s.kpi_name, "country": s.country}
         for s in signals],
        indent=2,
    )
    questions_block = json.dumps(
        [{"question_id": q.question_id, "text": q.text, "focus_area": q.focus_area}
         for q in questions],
        indent=2,
    )

    user_prompt = (
        f"KPI: {kpi_name} | Country: {country}\n\n"
        f"SIGNALS ({len(signals)}):\n```json\n{signals_block}\n```\n\n"
        f"ANALYST QUESTIONS (for context):\n```json\n{questions_block}\n```\n\n"
        f"Generate 10 causes + 10 effects + 1 consolidated search query per signal. "
        f"Return JSON array only."
    )

    client = _get_client()

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=8192,
    )
    record_usage(OPENAI_MODEL, response.usage, caller="hypotheses.generate_hypotheses")

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
        log.warning("Failed to parse hypotheses JSON: %s", text[:300])
        return []

    if not isinstance(parsed, list):
        parsed = [parsed]

    valid_signal_ids = {s.signal_id for s in signals}
    result: list[SignalHypotheses] = []

    for item in parsed:
        if not isinstance(item, dict):
            continue
        sid = item.get("signal_id", "")
        if sid not in valid_signal_ids:
            continue

        causes: list[Hypothesis] = []
        for c in item.get("causes", []):
            if not isinstance(c, dict):
                continue
            tw = c.get("time_window", ["", ""])
            if not isinstance(tw, list) or len(tw) < 2:
                tw = ["", ""]
            causes.append(Hypothesis(
                signal_id=sid,
                role="cause",
                text=c.get("text", ""),
                time_window=(str(tw[0]), str(tw[1])),
            ))

        effects: list[Hypothesis] = []
        for e in item.get("effects", []):
            if not isinstance(e, dict):
                continue
            tw = e.get("time_window", ["", ""])
            if not isinstance(tw, list) or len(tw) < 2:
                tw = ["", ""]
            effects.append(Hypothesis(
                signal_id=sid,
                role="effect",
                text=e.get("text", ""),
                time_window=(str(tw[0]), str(tw[1])),
            ))

        result.append(SignalHypotheses(
            signal_id=sid,
            causes=causes,
            effects=effects,
            consolidated_search_query=item.get("consolidated_search_query", ""),
        ))

    log.info(
        "Generated hypotheses for %d/%d signals (%d causes, %d effects total)",
        len(result), len(signals),
        sum(len(sh.causes) for sh in result),
        sum(len(sh.effects) for sh in result),
    )
    return result
