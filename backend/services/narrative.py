"""McKinsey-tone narrative generation from scored Insights."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import Event, Insight, Signal

log = logging.getLogger(__name__)

_NARRATIVE_SYSTEM = """\
You are a senior macro-economic analyst producing data-grounded insights for an \
executive briefing tool. You combine rigorous data interpretation with broad knowledge \
of macroeconomic policy, geopolitics, and institutional developments.

You will receive STRUCTURED CONTEXT containing:
1. INSIGHTS — each insight links a primary signal (data movement) to scored events \
(causes/effects) via transmission channels, with relevancy and confidence scores.
2. SIGNALS — the underlying data movements with dates and magnitudes.
3. EVENTS — real-world occurrences with summaries and source references.

WRITING RULES — McKinsey execution:

LEAD WITH THE INSIGHT, not the number. The economic meaning is the headline; numbers \
are supporting evidence.
- GOOD: "Saudi non-oil GDP overtook oil GDP for the first time, signaling a structural \
shift in the economy (~$340B vs ~$310B in 2024)."
- BAD: "Non-oil GDP reached $340.2B in Q3 2024, up 12.3% year-over-year."

Be SUCCINCT. One tight sentence per bullet; two only when tracing a causal chain.

NUMBER FORMATTING:
- Abbreviate large numbers: K (thousands), M (millions), B (billions). Round to 2 \
significant digits.
- No raw large numbers. Never "336,777" — write "~337K" or "~340K".
- Percentages: at most 1 decimal place.
- Prefix approximations with ~.
- ALWAYS include the currency/unit when quoting absolute values. The KPI_DATA JSON \
includes a "unit" field for each KPI (e.g. "SAR millions", "USD millions"). Write \
"~340B SAR" not "~340B". For percentage KPIs, just use %.

DATE REFERENCES:
- Use calendar years by default ("2024", not "Q3 2024") unless the quarter is \
analytically critical to the causal chain.
- Never reference future years as established fact.

CONFIDENCE CALIBRATION:
- For connections with confidence_score >= 0.7: assertive language ("driven by", \
"caused by", "triggered").
- For confidence_score 0.4-0.7: moderate hedging ("likely driven by", "largely \
attributable to").
- For confidence_score < 0.4: explicit hedging ("possibly linked to", "temporal \
correlation with", "may reflect").

CAUSAL CHAIN REASONING:
- Build causal chains: [trigger event] → [transmission mechanism] → [KPI impact] → \
[downstream consequence].
- When multiple signals connect to the same event, CONNECT them into a coherent story.
- For insights with no strong event connections, state that the driver is unclear \
rather than fabricating vague explanations.

SOURCE REFERENCES:
- When grounding a claim in an event that has source references, append compact markers: \
[src:1], [src:2], etc. Match the order of source_refs on the event.
- Omit markers when not grounded in specific sources.

BANNED PHRASES:
- "global economic uncertainties", "geopolitical tensions", "market dynamics", \
"external shocks" (without naming specifics)
- "challenging macroeconomic environment", "shifting investor sentiment" (without cause)
- "it is worth noting", "it should be noted", "interestingly"

OUTPUT STRUCTURE — mandatory:

## Summary
2-3 sentences capturing the single most important takeaway. Frame across the FULL data \
window. Lead with the insight.

## Key Findings
3-5 bullet points. Each leads with the analytical insight, cites numbers as supporting \
evidence. Span the full time range — do NOT just describe the latest period.

## Implications
2-4 bullet points building a CONNECTED CAUSAL NARRATIVE.
Each bullet: [data trend] → [specific event/policy] → [transmission mechanism] → \
[forward outlook].
Connect implications to each other where possible."""


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _build_user_prompt(
    insights: list[Insight],
    signals: list[Signal],
    events: list[Event],
    kpi_data: dict[str, Any],
) -> str:
    signals_by_id = {s.signal_id: s for s in signals}
    events_by_id = {e.event_id: e for e in events}

    insights_block = []
    for ins in insights:
        sig = signals_by_id.get(ins.primary_signal_id)
        conns = []
        for c in ins.connections:
            ev = events_by_id.get(c.event_id)
            conns.append({
                "event_headline": ev.headline if ev else "?",
                "event_summary": ev.summary if ev else "",
                "event_role": ev.role if ev else "?",
                "direction": c.direction,
                "transmission_channel": c.transmission_channel,
                "relevancy_score": c.relevancy_score,
                "confidence_score": c.confidence_score,
                "source_refs": [
                    {"index": i + 1, "title": sr.title, "date": sr.date,
                     "source_domain": sr.source_domain}
                    for i, sr in enumerate(ev.source_refs)
                ] if ev else [],
            })
        insights_block.append({
            "headline": ins.headline,
            "signal": {
                "description": sig.description if sig else "",
                "from_date": sig.from_date if sig else "",
                "to_date": sig.to_date if sig else "",
                "magnitude_pct": sig.magnitude_pct if sig else 0,
            },
            "connections": conns,
        })

    data_block = json.dumps(kpi_data, indent=2, default=str)
    insights_json = json.dumps(insights_block, indent=2, default=str)

    return (
        f"KPI_DATA:\n```json\n{data_block}\n```\n\n"
        f"INSIGHTS ({len(insights)}):\n```json\n{insights_json}\n```\n\n"
        "Synthesize into a cohesive insight narrative following the OUTPUT STRUCTURE."
    )


def stream_narrative(
    insights: list[Insight],
    signals: list[Signal],
    events: list[Event],
    kpi_data: dict[str, Any],
) -> Iterator[str]:
    """Stream narrative text chunks from the LLM."""
    client = _get_client()

    user_prompt = _build_user_prompt(insights, signals, events, kpi_data)

    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": _NARRATIVE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=3072,
        stream=True,
        stream_options={"include_usage": True},
    )

    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content
    record_usage(OPENAI_MODEL, usage, caller="narrative.stream_narrative")
