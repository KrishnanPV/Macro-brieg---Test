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

class InsightsRequest(BaseModel):
    countries: list[str]
    kpi_ids: list[str]
    results: list[dict[str, Any]]


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
# Notebook endpoints
# ---------------------------------------------------------------------------

class NotebookCellCreate(BaseModel):
    cell_type: str  # "markdown" | "data" | "ai" | "insight" | "source"
    content: str = ""
    metadata: dict[str, Any] = {}
    position: int | None = None


class NotebookCellUpdate(BaseModel):
    content: str | None = None
    metadata: dict[str, Any] | None = None
    position: int | None = None


class NotebookCellOut(BaseModel):
    id: str
    workspace_id: str
    cell_type: str
    content: str
    metadata: dict[str, Any]
    position: int
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Knowledge Graph endpoints
# ---------------------------------------------------------------------------

class GraphNodeCreate(BaseModel):
    node_type: str  # "kpi_movement" | "event" | "policy" | "insight" | "article"
    label: str
    metadata: dict[str, Any] = {}
    x: float | None = None
    y: float | None = None


class GraphNodeUpdate(BaseModel):
    label: str | None = None
    metadata: dict[str, Any] | None = None
    x: float | None = None
    y: float | None = None


class GraphNodeOut(BaseModel):
    id: str
    workspace_id: str
    node_type: str
    label: str
    metadata: dict[str, Any]
    x: float | None
    y: float | None
    created_at: str

    model_config = {"from_attributes": True}


class GraphEdgeCreate(BaseModel):
    source_id: str
    target_id: str
    edge_type: str  # "caused_by" | "correlated_with" | "led_to" | "sourced_from"
    label: str = ""
    metadata: dict[str, Any] = {}


class GraphEdgeOut(BaseModel):
    id: str
    workspace_id: str
    source_id: str
    target_id: str
    edge_type: str
    label: str
    metadata: dict[str, Any]
    created_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Flash Cards endpoints
# ---------------------------------------------------------------------------

class FlashCardDeckCreate(BaseModel):
    name: str
    tags: list[str] = []


class FlashCardDeckOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    tags: list[str]
    card_count: int = 0
    created_at: str

    model_config = {"from_attributes": True}


class FlashCardCreate(BaseModel):
    front: str
    back: str
    source_cell_id: str | None = None
    tags: list[str] = []


class FlashCardUpdate(BaseModel):
    front: str | None = None
    back: str | None = None
    tags: list[str] | None = None
    ease_factor: float | None = None
    interval_days: int | None = None


class FlashCardOut(BaseModel):
    id: str
    deck_id: str
    front: str
    back: str
    source_cell_id: str | None
    tags: list[str]
    ease_factor: float
    interval_days: int
    repetitions: int
    next_review: str | None
    created_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Context Documents
# ---------------------------------------------------------------------------

class ContextDocCreate(BaseModel):
    title: str
    content: str
    doc_type: str = "text"  # "text" | "pdf" | "url"
    source_url: str | None = None


class ContextDocOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    content: str
    doc_type: str
    source_url: str | None
    created_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Brief Builder
# ---------------------------------------------------------------------------

class BriefCreate(BaseModel):
    title: str
    template: str = "country_overview"  # "country_overview" | "comparative" | "thematic"
    content: dict[str, Any] = {}


class BriefUpdate(BaseModel):
    title: str | None = None
    content: dict[str, Any] | None = None


class BriefOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    template: str
    content: dict[str, Any]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Agent chat
# ---------------------------------------------------------------------------

class AgentChatRequest(BaseModel):
    message: str
    workspace_id: str
    cell_id: str | None = None
    context: dict[str, Any] = {}


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


class AgentToolCall(BaseModel):
    tool: str
    args: dict[str, Any]
    result: Any = None


class AgentChatChunk(BaseModel):
    type: str  # "text" | "tool_call" | "tool_result" | "done" | "error"
    content: str = ""
    tool_call: AgentToolCall | None = None
