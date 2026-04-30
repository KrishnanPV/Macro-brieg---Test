"""Insights endpoints: single-KPI streaming insight generation."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.models.schemas import (
    SingleKpiInsightRequest,
    SingleCountryKpiInsightRequest,
    CrossCountryInsightRequest,
)
from backend.services.agent import (
    stream_kpi_insight,
    stream_single_country_kpi_insight,
    stream_cross_country_insight,
)

router = APIRouter(prefix="/api", tags=["insights"])


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
    """Cross-country comparative insight for a single KPI."""
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(400, "No data series to generate insights from.")

    def _stream():
        yield from stream_cross_country_insight(req.countries, r)

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
