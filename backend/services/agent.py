"""Agentic AI orchestrator with tool calling and multi-step reasoning."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.prompts.system import build_insight_prompt, build_cross_country_prompt, SYSTEM_PROMPT
from backend.services.cost_tracker import record_usage
from backend.services.derived_facts import compute_derived_facts
from backend.services.news_client import (
    DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
    fetch_news_bulk,
    fetch_news_for_kpi,
    flatten_news_catalog,
    synthesize_news_context,
)

log = logging.getLogger(__name__)


def _ndjson_line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _temperature_kw(model: str) -> dict[str, float]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.3}


# ---------------------------------------------------------------------------
# Tool definitions for the agentic loop
# ---------------------------------------------------------------------------

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_kpi_data",
            "description": "Fetch macroeconomic KPI data from Oxford Economics for given countries and KPI IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "countries": {"type": "array", "items": {"type": "string"}, "description": "ISO3 country codes"},
                    "kpi_ids": {"type": "array", "items": {"type": "string"}, "description": "KPI IDs to fetch"},
                    "timerange": {"type": "string", "description": "Year range like '2015-2026'"},
                },
                "required": ["countries", "kpi_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Search for recent news articles about macroeconomic topics for specific countries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "countries": {"type": "array", "items": {"type": "string"}, "description": "ISO3 country codes"},
                    "kpi_id": {"type": "string", "description": "KPI ID for context-specific search"},
                },
                "required": ["query", "countries"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_statistics",
            "description": "Compute derived facts (CAGR, inflection points, trend segments) for KPI data.",
            "parameters": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "description": "KPI results to analyze (same objects as returned by fetch_kpi_data).",
                        "items": {"type": "object"},
                    },
                },
                "required": ["results"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_graph_node",
            "description": "Add a node to the knowledge graph (event, policy, KPI movement, or insight).",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {"type": "string", "enum": ["event", "policy", "kpi_movement", "insight"]},
                    "label": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "required": ["node_type", "label"],
            },
        },
    },
]


def _execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool call and return the result as a string."""
    if name == "fetch_kpi_data":
        from backend.services.knoema_client import fetch_kpi_data
        tr = args.get("timerange", "2015-2026")
        result = fetch_kpi_data(
            countries=args["countries"],
            kpi_ids=args["kpi_ids"],
            timerange_q=tr,
            timerange_a=tr,
        )
        return result.model_dump_json()

    elif name == "search_news":
        kpi_id = args.get("kpi_id", "3")
        articles = fetch_news_for_kpi(kpi_id, args["countries"], [])
        summarized = synthesize_news_context(
            articles, args["countries"], kpi_id=kpi_id,
            max_per_country=DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
        )
        return json.dumps(summarized, default=str)

    elif name == "compute_statistics":
        facts = compute_derived_facts(args["results"])
        return json.dumps(facts, default=str)

    elif name == "create_graph_node":
        return json.dumps({"status": "created", "node_type": args["node_type"], "label": args["label"]})

    return json.dumps({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Streaming insight generation (backward-compatible)
# ---------------------------------------------------------------------------

def stream_kpi_insight(
    countries: list[str],
    kpi_result: dict[str, Any],
):
    """Stream insight text for a single KPI (backward-compatible with V1 endpoint)."""
    kpi_id = str(kpi_result.get("kpi_id", ""))
    selection = {"countries": countries, "kpi_ids": [kpi_id]}
    derived_facts = compute_derived_facts([kpi_result])

    news_context = None
    try:
        raw_articles = fetch_news_for_kpi(kpi_id, countries, derived_facts)
        if raw_articles:
            from datetime import datetime
            news_context = synthesize_news_context(
                raw_articles, countries,
                kpi_id=kpi_id,
                anchor_date=datetime.now().strftime("%Y-%m-%d"),
                derived_facts=derived_facts,
                max_per_country=DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
            )
            if not news_context:
                news_context = None
    except Exception as exc:
        log.warning("News fetch failed for KPI %s: %s", kpi_id, exc)

    articles_flat, prompt_bundle = flatten_news_catalog(news_context)
    yield _ndjson_line({"type": "news_catalog", "content": {"articles": articles_flat}})

    messages = build_insight_prompt(
        selection, [kpi_result], derived_facts,
        news_context=news_context,
        news_prompt_bundle=prompt_bundle if news_context else None,
    )
    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
        **_temperature_kw(model),
    )
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield _ndjson_line({"type": "text_delta", "content": delta.content})
    record_usage(model, usage, caller="agent.stream_kpi_insight")
    yield _ndjson_line({"type": "done"})


def stream_single_country_kpi_insight(
    country: str,
    kpi_result: dict[str, Any],
):
    """Stream insight for a single KPI filtered to a single country."""
    kpi_id = str(kpi_result.get("kpi_id", ""))

    filtered_series = [s for s in kpi_result.get("series", []) if s.get("country") == country]
    filtered_result = {**kpi_result, "series": filtered_series}

    selection = {"countries": [country], "kpi_ids": [kpi_id]}
    derived_facts = compute_derived_facts([filtered_result])

    news_context = None
    try:
        raw_articles = fetch_news_for_kpi(kpi_id, [country], derived_facts)
        if raw_articles:
            from datetime import datetime
            news_context = synthesize_news_context(
                raw_articles, [country],
                kpi_id=kpi_id,
                anchor_date=datetime.now().strftime("%Y-%m-%d"),
                derived_facts=derived_facts,
                max_per_country=DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
            )
            if not news_context:
                news_context = None
    except Exception as exc:
        log.warning("News fetch failed for KPI %s / %s: %s", kpi_id, country, exc)

    articles_flat, prompt_bundle = flatten_news_catalog(news_context)
    yield _ndjson_line({"type": "news_catalog", "content": {"articles": articles_flat}})

    messages = build_insight_prompt(
        selection, [filtered_result], derived_facts,
        news_context=news_context,
        news_prompt_bundle=prompt_bundle if news_context else None,
    )
    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
        **_temperature_kw(model),
    )
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield _ndjson_line({"type": "text_delta", "content": delta.content})
    record_usage(model, usage, caller="agent.stream_single_country_kpi_insight")
    yield _ndjson_line({"type": "done"})


def stream_cross_country_insight(
    countries: list[str],
    kpi_result: dict[str, Any],
):
    """Stream cross-country comparative insight for a single KPI."""
    from datetime import datetime

    kpi_id = str(kpi_result.get("kpi_id", ""))
    selection = {"countries": countries, "kpi_ids": [kpi_id]}
    derived_facts = compute_derived_facts([kpi_result])
    today_str = datetime.now().strftime("%Y-%m-%d")

    merged_news: dict[str, Any] = {}
    try:
        raw_articles = fetch_news_for_kpi(kpi_id, countries, derived_facts)
        if raw_articles:
            kpi_news = synthesize_news_context(
                raw_articles, countries, kpi_id=kpi_id, anchor_date=today_str,
                derived_facts=derived_facts,
                max_per_country=DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
            )
            if kpi_news:
                merged_news = kpi_news
    except Exception as exc:
        log.warning("News fetch failed for cross-country KPI %s: %s", kpi_id, exc)

    nc = merged_news if merged_news else None
    articles_flat, prompt_bundle = flatten_news_catalog(nc)
    yield _ndjson_line({"type": "news_catalog", "content": {"articles": articles_flat}})

    messages = build_cross_country_prompt(
        selection, [kpi_result], derived_facts,
        news_context=nc,
        news_prompt_bundle=prompt_bundle if nc else None,
    )

    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
        **_temperature_kw(model),
    )
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield _ndjson_line({"type": "text_delta", "content": delta.content})
    record_usage(model, usage, caller="agent.stream_cross_country_insight")
    yield _ndjson_line({"type": "done"})


def stream_multi_kpi_insight(
    countries: list[str],
    kpi_ids: list[str],
    results: list[dict[str, Any]],
):
    """Stream insight text for multiple KPIs."""
    from datetime import datetime

    valid_results = [r for r in results if r.get("series")]
    if not valid_results:
        yield "No data series to generate insights from."
        return

    selection = {"countries": countries, "kpi_ids": kpi_ids}
    derived_facts = compute_derived_facts(valid_results)
    today_str = datetime.now().strftime("%Y-%m-%d")

    merged_news: dict[str, Any] = {}
    try:
        raw_articles = fetch_news_bulk(kpi_ids, countries, derived_facts)
        if raw_articles:
            merged_news = synthesize_news_context(
                raw_articles, countries, anchor_date=today_str,
                derived_facts=derived_facts, kpi_ids=kpi_ids,
                max_per_country=DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
            )
    except Exception as exc:
        log.warning("Bulk news fetch failed: %s", exc)

    nc = merged_news if merged_news else None
    articles_flat, prompt_bundle = flatten_news_catalog(nc)
    yield _ndjson_line({"type": "news_catalog", "content": {"articles": articles_flat}})

    messages = build_insight_prompt(
        selection, valid_results, derived_facts,
        news_context=nc,
        news_prompt_bundle=prompt_bundle if nc else None,
    )

    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
        **_temperature_kw(model),
    )
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield _ndjson_line({"type": "text_delta", "content": delta.content})
    record_usage(model, usage, caller="agent.stream_multi_kpi_insight")
    yield _ndjson_line({"type": "done"})


# ---------------------------------------------------------------------------
# Agentic chat (multi-step tool-using)
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """\
You are Macro Brief AI, an expert macroeconomic research assistant. You help analysts understand economic trends, compare countries, and build insights.

You have access to tools that let you:
- Fetch KPI data from Oxford Economics
- Search for relevant news articles
- Compute statistical analyses
- Add nodes to the knowledge graph

When the user asks a question:
1. Think about what data and context you need
2. Use your tools to gather information
3. Synthesize a clear, specific, data-grounded response
4. Suggest follow-up analyses or related topics

Always be specific — cite numbers, name policies, identify transmission channels. Never use vague phrases.
"""


def stream_agent_chat(
    message: str,
    workspace_context: dict[str, Any] | None = None,
):
    """Run an agentic chat loop with tool calling."""
    client = _get_client()
    model = OPENAI_MODEL

    messages = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
    ]

    if workspace_context:
        ctx_str = json.dumps(workspace_context, default=str)
        messages.append({"role": "system", "content": f"Current workspace context:\n{ctx_str}"})

    messages.append({"role": "user", "content": message})

    max_iterations = 5
    for _ in range(max_iterations):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=AGENT_TOOLS,
            max_completion_tokens=4096,
            stream=True,
            stream_options={"include_usage": True},
            **_temperature_kw(model),
        )

        tool_calls_buffer: dict[int, dict] = {}
        has_tool_calls = False
        usage = None

        for chunk in response:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                yield {"type": "text", "content": delta.content}

            if delta.tool_calls:
                has_tool_calls = True
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name or "" if tc.function else "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_buffer[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_buffer[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments

        record_usage(model, usage, caller="agent.stream_agent_chat")

        if not has_tool_calls:
            yield {"type": "done"}
            return

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": []}
        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            assistant_msg["tool_calls"].append({
                "id": tc["id"],
                "type": "function",
                "function": {"name": tc["name"], "arguments": tc["arguments"]},
            })
        messages.append(assistant_msg)

        for idx in sorted(tool_calls_buffer.keys()):
            tc = tool_calls_buffer[idx]
            yield {
                "type": "tool_call",
                "content": json.dumps({"tool": tc["name"], "args": tc["arguments"][:200]}),
            }

            try:
                args = json.loads(tc["arguments"])
                result = _execute_tool(tc["name"], args)
            except Exception as e:
                result = json.dumps({"error": str(e)})

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

            yield {"type": "tool_result", "content": result[:500]}

    yield {"type": "done"}
