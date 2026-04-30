"""Pydantic request/response models for all API endpoints."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Data endpoints
# ---------------------------------------------------------------------------

class KpiInfo(BaseModel):
    id: str
    name: str
    source: str
    frequency: str
    indicators: list[str]
    notes: str
    available: bool


class FetchRequest(BaseModel):
    countries: list[str]
    kpi_ids: list[str]
    frequency_overrides: dict[str, str] | None = None
    timerange_q: str = "2015-2029"
    timerange_a: str = "2015-2026"


class SeriesPoint(BaseModel):
    date: str
    value: float | None


class IndicatorSeries(BaseModel):
    country: str
    indicator: str
    points: list[SeriesPoint]
    unit: str = ""
    scale: str = ""


class KpiResult(BaseModel):
    kpi_id: str
    kpi_name: str
    frequency: str
    native_frequency: str = ""
    unit: str = ""
    series: list[IndicatorSeries]
    series_annual: list[IndicatorSeries] | None = None
    oil_price_overlay: IndicatorSeries | None = None
    errors: list[str] = []
    last_actual_year: int = 2025


class FetchResponse(BaseModel):
    results: list[KpiResult]
    last_actual_year: int = 2025


class RefetchKpiRequest(BaseModel):
    countries: list[str]
    kpi_id: str
    frequency: str
    timerange_q: str = "2015-2029"
    timerange_a: str = "2015-2026"


# ---------------------------------------------------------------------------
# Insights endpoints
# ---------------------------------------------------------------------------

class SingleKpiInsightRequest(BaseModel):
    countries: list[str]
    kpi_result: dict[str, Any]


class SingleCountryKpiInsightRequest(BaseModel):
    country: str
    kpi_result: dict[str, Any]


class CrossCountryInsightRequest(BaseModel):
    countries: list[str]
    kpi_result: dict[str, Any]


# ---------------------------------------------------------------------------
# Workspace endpoints
# ---------------------------------------------------------------------------

class WorkspaceCreate(BaseModel):
    name: str
    description: str = ""
    countries: list[str] = []
    kpi_ids: list[str] = []
    country_brief: dict[str, Any] = {}


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    countries: list[str] | None = None
    kpi_ids: list[str] | None = None
    country_brief: dict[str, Any] | None = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: str
    countries: list[str]
    kpi_ids: list[str]
    country_brief: dict[str, Any]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Country Brief generation
# ---------------------------------------------------------------------------

class CountryBriefGenerateRequest(BaseModel):
    country: str
    kpi_ids: list[str] | None = None
    start_year: int = 2015
    end_year: int = 2026
    focus: str | None = None
    # Annual vs quarterly for all KPI series in this brief (where the source supports it).
    chart_frequency: Literal["A", "Q"] = "A"
    # When True, runs the full hypothesis-driven investigation pipeline
    # (signal detection, Perplexity evidence search, event extraction, scored
    # insights) before generating the narrative.
    deep_analysis: bool = False


class CountryBriefRefineRequest(BaseModel):
    section_content: str
    data_context: dict[str, Any] = {}
    message: str
    history: list[dict[str, str]] = []
