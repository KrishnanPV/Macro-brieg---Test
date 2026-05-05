"""Dashboard insight endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.dashboard.pipeline import (
    generate_country_insight,
    generate_cross_country_insight,
)
from backend.dashboard.schemas import (
    DashboardCountryInsightRequest,
    DashboardCrossCountryInsightRequest,
)

router = APIRouter(prefix="/api/dashboard/insights", tags=["dashboard"])


@router.post("/country")
def dashboard_country_insight(req: DashboardCountryInsightRequest) -> dict:
    payload = req.kpi_result or {}
    series = payload.get("series")
    if not isinstance(series, list) or not series:
        raise HTTPException(400, "No data series to generate insights from.")
    return generate_country_insight(
        country=req.country,
        kpi_result=payload,
        reasoning_model=req.reasoning_model,
    )


@router.post("/cross-country")
def dashboard_cross_country_insight(req: DashboardCrossCountryInsightRequest) -> dict:
    payload = req.kpi_result or {}
    series = payload.get("series")
    if not isinstance(series, list) or not series:
        raise HTTPException(400, "No data series to generate insights from.")
    if len(req.countries) < 2:
        raise HTTPException(400, "Cross-country insights require at least two countries.")
    return generate_cross_country_insight(
        countries=req.countries,
        kpi_result=payload,
        reasoning_model=req.reasoning_model,
    )

