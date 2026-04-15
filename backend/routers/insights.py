"""Insights endpoints: single-KPI and multi-KPI insight generation."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.config import NEWSCATCHER_API_KEY
from backend.models.schemas import (
    InsightsRequest, SingleKpiInsightRequest,
    SingleCountryKpiInsightRequest, CrossCountryInsightRequest,
    AgentChatRequest,
)
from backend.services.agent import (
    stream_kpi_insight, stream_multi_kpi_insight,
    stream_single_country_kpi_insight, stream_cross_country_insight,
    stream_agent_chat,
)
from backend.services.derived_facts import compute_derived_facts
from backend.services.news_client import fetch_news_for_kpi, synthesize_news_context

router = APIRouter(prefix="/api", tags=["insights"])


@router.post("/insights")
def generate_insights(req: InsightsRequest):
    valid_results = [r for r in req.results if r.get("series")]
    if not valid_results:
        raise HTTPException(400, "No data series to generate insights from.")

    def _stream():
        yield from stream_multi_kpi_insight(req.countries, req.kpi_ids, valid_results)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/insights/kpi")
def generate_single_kpi_insight(req: SingleKpiInsightRequest):
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(400, "No data series to generate insights from.")

    def _stream():
        yield from stream_kpi_insight(req.countries, r)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/insights/kpi/country")
def generate_single_country_kpi_insight(req: SingleCountryKpiInsightRequest):
    """Generate insight for a single KPI filtered to a single country."""
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(400, "No data series to generate insights from.")

    def _stream():
        yield from stream_single_country_kpi_insight(req.country, r)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/insights/kpi/cross-country")
def generate_cross_country_kpi_insight(req: CrossCountryInsightRequest):
    """Generate cross-country comparative insight for a single KPI."""
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(400, "No data series to generate insights from.")

    def _stream():
        yield from stream_cross_country_insight(req.countries, r)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/agent/chat")
def agent_chat(req: AgentChatRequest):
    """Agentic chat endpoint with tool calling."""
    def _stream():
        for chunk in stream_agent_chat(req.message, req.context):
            yield json.dumps(chunk, default=str) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@router.post("/news/lab")
def news_lab(req: SingleKpiInsightRequest) -> dict[str, Any]:
    """Fetch and score Newscatcher articles for the News Lab UI."""
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(
            400,
            "No data series — open the Dashboard and fetch KPI data first, then return here.",
        )

    if not NEWSCATCHER_API_KEY or NEWSCATCHER_API_KEY == "your_newscatcher_api_key_here":
        return {
            "articles": [],
            "message": "Newscatcher API key is not configured. Set NEWSCATCHER_API_KEY in .env.",
        }

    kpi_id = str(r.get("kpi_id", ""))
    countries = req.countries
    derived = compute_derived_facts([r])
    raw = fetch_news_for_kpi(kpi_id, countries, derived)
    anchor = datetime.now().strftime("%Y-%m-%d")
    synthesized = synthesize_news_context(
        raw, countries, kpi_id=kpi_id, anchor_date=anchor, derived_facts=derived,
    )

    flat: list[dict[str, Any]] = []
    for bucket, items in synthesized.items():
        for it in items:
            row = dict(it)
            row["country_iso3"] = None if bucket == "_general" else bucket
            flat.append(row)

    flat.sort(key=lambda x: x.get("score") or 0, reverse=True)

    out: dict[str, Any] = {"articles": flat}
    if not flat and raw:
        out["message"] = "Articles were retrieved but none passed ranking filters (try another KPI or country)."
    elif not flat:
        out["message"] = "No articles returned for this query. Try a different KPI or widen your country selection."

    return out
