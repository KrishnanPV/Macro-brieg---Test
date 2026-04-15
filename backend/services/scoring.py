"""LLM-scored Signal-Event connections and M:N Insight assembly."""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import (
    AnalystQuestion,
    Event,
    Insight,
    InsightConnection,
    Signal,
)

log = logging.getLogger(__name__)

_RELEVANCY_THRESHOLD = 0.3

_SCORING_SYSTEM = """\
You are a macroeconomic analyst specializing in causal attribution. You will receive:
1. SIGNALS — notable data movements in KPI time series.
2. EVENTS — real-world occurrences extracted from research (each tagged as "cause" or "effect").

Your task: score every plausible Signal-Event pair. For each pair, produce:
- "signal_id": the signal's ID
- "event_id": the event's ID
- "direction": one of "event_caused_signal" (event drove the data movement), \
"signal_caused_event" (data movement triggered this downstream event), or \
"correlated" (temporal correlation, uncertain causation)
- "transmission_channel": 1-2 sentence explanation of the economic mechanism
- "relevancy_score": 0.0-1.0 (how relevant is this event to understanding this signal?)
- "confidence_score": 0.0-1.0 (how confident are you in this connection?)

Rules:
- Consider temporal alignment: causes should precede signals, effects should follow.
- Use the event's "role" tag as a hint but override if the evidence suggests otherwise.
- Only include pairs with relevancy_score >= 0.3. Drop weak connections.
- Be specific about transmission channels — name the economic mechanism.
- A signal may connect to zero, one, or many events. An event may connect to multiple signals.

Also produce a SHORT headline (max 12 words) for each signal that captures its main story, \
informed by the connected events. Include these as a separate array.

Respond with JSON:
{
  "connections": [
    {"signal_id": "...", "event_id": "...", "direction": "...", \
"transmission_channel": "...", "relevancy_score": 0.85, "confidence_score": 0.7}
  ],
  "signal_headlines": [
    {"signal_id": "...", "headline": "..."}
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


def score_and_assemble_insights(
    signals: list[Signal],
    events: list[Event],
    questions: list[AnalystQuestion],
) -> list[Insight]:
    """LLM scores Signal-Event connections, then assembles M:N Insight objects."""
    if not signals:
        return []
    if not events:
        return [
            Insight(
                primary_signal_id=s.signal_id,
                headline=s.description[:80],
                narrative="No events were identified to explain this data movement.",
            )
            for s in signals
        ]

    signals_block = json.dumps(
        [{"signal_id": s.signal_id, "type": s.signal_type,
          "description": s.description, "from_date": s.from_date,
          "to_date": s.to_date, "magnitude_pct": s.magnitude_pct,
          "kpi_name": s.kpi_name, "country": s.country}
         for s in signals],
        indent=2,
    )
    events_block = json.dumps(
        [{"event_id": e.event_id, "headline": e.headline,
          "summary": e.summary, "date_range": e.date_range,
          "role": e.role, "actors": e.actors}
         for e in events],
        indent=2,
    )

    user_prompt = (
        f"SIGNALS ({len(signals)}):\n```json\n{signals_block}\n```\n\n"
        f"EVENTS ({len(events)}):\n```json\n{events_block}\n```\n\n"
        "Score all plausible Signal-Event connections and produce signal headlines. "
        "Return JSON object only."
    )

    client = _get_client()

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _SCORING_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=4096,
    )
    record_usage(OPENAI_MODEL, response.usage, caller="scoring.score_and_assemble_insights")

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
        log.warning("Failed to parse scoring JSON: %s", text[:300])
        return [
            Insight(
                primary_signal_id=s.signal_id,
                headline=s.description[:80],
                narrative="Scoring failed — could not parse LLM output.",
            )
            for s in signals
        ]

    valid_signal_ids = {s.signal_id for s in signals}
    valid_event_ids = {e.event_id for e in events}

    connections: list[InsightConnection] = []
    raw_conns = parsed.get("connections", []) if isinstance(parsed, dict) else []

    for item in raw_conns:
        if not isinstance(item, dict):
            continue
        sid = item.get("signal_id", "")
        eid = item.get("event_id", "")
        if sid not in valid_signal_ids or eid not in valid_event_ids:
            continue

        direction = item.get("direction", "correlated")
        if direction not in ("event_caused_signal", "signal_caused_event", "correlated"):
            direction = "correlated"

        rel = float(item.get("relevancy_score", 0))
        conf = float(item.get("confidence_score", 0))
        rel = max(0.0, min(1.0, rel))
        conf = max(0.0, min(1.0, conf))

        if rel < _RELEVANCY_THRESHOLD:
            continue

        connections.append(InsightConnection(
            signal_id=sid,
            event_id=eid,
            direction=direction,
            transmission_channel=item.get("transmission_channel", ""),
            relevancy_score=round(rel, 2),
            confidence_score=round(conf, 2),
        ))

    headlines: dict[str, str] = {}
    for item in parsed.get("signal_headlines", []) if isinstance(parsed, dict) else []:
        if isinstance(item, dict):
            headlines[item.get("signal_id", "")] = item.get("headline", "")

    conns_by_signal: dict[str, list[InsightConnection]] = defaultdict(list)
    for c in connections:
        conns_by_signal[c.signal_id].append(c)

    insights: list[Insight] = []
    for s in signals:
        signal_conns = conns_by_signal.get(s.signal_id, [])
        signal_conns.sort(key=lambda c: c.relevancy_score, reverse=True)

        headline = headlines.get(s.signal_id, s.description[:80])

        insights.append(Insight(
            primary_signal_id=s.signal_id,
            connections=signal_conns,
            headline=headline,
        ))

    log.info(
        "Assembled %d insights with %d total connections",
        len(insights), len(connections),
    )
    return insights
