"""LLM-based event extraction from Perplexity search results."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import Event, Signal, SignalHypotheses, SourceRef

log = logging.getLogger(__name__)

_EVENT_EXTRACTION_SYSTEM = """\
You are a macroeconomic research assistant. You will receive:
1. SIGNALS — notable data movements detected in a KPI time series.
2. HYPOTHESES — potential causes and effects for each signal, with time windows.
3. SEARCH RESULTS — web search results grouped by signal, retrieved using the hypotheses.

Your task: extract distinct real-world EVENTS from the search results. An event is a \
specific, datable occurrence — a policy decision, a geopolitical action, an economic \
shock, a reform announcement, a market event, etc.

Rules:
- Each event must be classified as "cause" (happened before/during the signal and \
could have driven it) or "effect" (happened after the signal and could be a consequence).
- Deduplicate: if the same event appears in results for multiple signals, produce it \
ONCE but note which signal(s) it relates to via originating_hypothesis_id.
- Each event must have: headline (short label), summary (2-3 sentences), date_range, \
role ("cause" or "effect"), actors involved, and source_indices (referencing the \
search results).
- Extract between 5 and 20 events total. Prioritize the most significant ones.
- Do NOT invent events not supported by the search results.

Respond with a JSON array of objects:
{
  "headline": "short event label",
  "summary": "2-3 sentence context",
  "date_range": "approximate period",
  "role": "cause" or "effect",
  "actors": ["actor1", "actor2"],
  "source_indices": [0, 3, 7],
  "related_signal_ids": ["signal_id_1"]
}

Return ONLY the JSON array."""


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def extract_events(
    signals: list[Signal],
    signal_hypotheses: list[SignalHypotheses],
    search_results: dict[str, list[dict[str, Any]]],
) -> list[Event]:
    """Single batched LLM call to extract Events from all search results."""
    all_sources: list[dict[str, Any]] = []
    source_index_map: dict[int, dict[str, Any]] = {}

    for sid, results in search_results.items():
        for r in results:
            idx = len(all_sources)
            entry = {
                "index": idx,
                "signal_id": sid,
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", "")[:500],
                "date": r.get("date", ""),
                "source_domain": r.get("source_domain", ""),
            }
            all_sources.append(entry)
            source_index_map[idx] = r

    if not all_sources:
        return []

    signals_block = json.dumps(
        [{"signal_id": s.signal_id, "type": s.signal_type,
          "description": s.description, "from_date": s.from_date,
          "to_date": s.to_date}
         for s in signals],
        indent=2,
    )

    hypotheses_block = json.dumps(
        [{"signal_id": sh.signal_id,
          "causes": [{"text": c.text, "time_window": list(c.time_window)} for c in sh.causes],
          "effects": [{"text": e.text, "time_window": list(e.time_window)} for e in sh.effects]}
         for sh in signal_hypotheses],
        indent=2,
    )

    sources_for_prompt = json.dumps(
        [{"index": s["index"], "signal_id": s["signal_id"],
          "title": s["title"], "date": s["date"],
          "source_domain": s["source_domain"],
          "snippet": s["snippet"]}
         for s in all_sources],
        indent=2,
    )

    user_prompt = (
        f"SIGNALS:\n```json\n{signals_block}\n```\n\n"
        f"HYPOTHESES:\n```json\n{hypotheses_block}\n```\n\n"
        f"SEARCH RESULTS ({len(all_sources)} results):\n```json\n{sources_for_prompt}\n```\n\n"
        "Extract distinct events. Return JSON array only."
    )

    client = _get_client()

    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _EVENT_EXTRACTION_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=4096,
    )
    record_usage(OPENAI_MODEL, response.usage, caller="events.extract_events")

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
        log.warning("Failed to parse event extraction JSON: %s", text[:300])
        return []

    if not isinstance(parsed, list):
        parsed = [parsed]

    events: list[Event] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue

        refs: list[SourceRef] = []
        for idx in item.get("source_indices", []):
            if isinstance(idx, int) and idx in source_index_map:
                r = source_index_map[idx]
                refs.append(SourceRef(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("snippet", "")[:300],
                    date=r.get("date", ""),
                    source_domain=r.get("source_domain", ""),
                ))

        role = item.get("role", "cause")
        if role not in ("cause", "effect"):
            role = "cause"

        related = item.get("related_signal_ids", [])
        hyp_id = related[0] if related else ""

        events.append(Event(
            headline=item.get("headline", "Unknown event"),
            summary=item.get("summary", ""),
            date_range=item.get("date_range", ""),
            role=role,
            actors=item.get("actors", []),
            source_refs=refs,
            originating_hypothesis_id=hyp_id,
        ))

    log.info(
        "Extracted %d events from %d search results",
        len(events), len(all_sources),
    )
    return events
