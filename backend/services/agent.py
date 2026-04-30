"""Agentic AI orchestrator with tool calling and multi-step reasoning."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.prompts.system import build_insight_prompt, build_cross_country_prompt
from backend.services.cost_tracker import record_usage
from backend.services.derived_facts import compute_derived_facts
from backend.services.news_client import (
    DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY,
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
