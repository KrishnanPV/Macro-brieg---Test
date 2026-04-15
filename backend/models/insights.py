"""Pydantic models for the insights investigation pipeline.

These models represent artifacts produced at each stage of the
hypothesis-driven insights pipeline: analyst questions, signals,
hypotheses, evidence events, scored connections, and assembled insights.
"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
import uuid


def _short_id() -> str:
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class InsightLabRequest(BaseModel):
    """Payload accepted by POST /api/insights-lab/run."""
    country: str
    kpi_id: str
    start_year: int = 2015
    end_year: int = 2026


# ---------------------------------------------------------------------------
# Analyst Questions
# ---------------------------------------------------------------------------

class AnalystQuestion(BaseModel):
    """An investigative question an analyst would ask about this KPI-country combo."""
    question_id: str = Field(default_factory=_short_id)
    text: str
    focus_area: str  # e.g. "structural_change", "policy_impact", "external_shock"


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class Signal(BaseModel):
    """A notable statistical movement detected in KPI data."""
    signal_id: str = Field(default_factory=_short_id)
    kpi_id: str
    kpi_name: str
    country: str
    signal_type: Literal[
        "inflection_point",
        "trend_segment",
        "cagr_notable",
        "outsized_period_change",
        "sign_reversal",
    ]
    from_date: str
    to_date: str
    from_value: float
    to_value: float
    magnitude_pct: float
    description: str
    question_relevance: list[str] = Field(
        default_factory=list,
        description="IDs of AnalystQuestions this signal is relevant to",
    )


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

class Hypothesis(BaseModel):
    """A potential cause or effect related to a signal."""
    hypothesis_id: str = Field(default_factory=_short_id)
    signal_id: str
    role: Literal["cause", "effect"]
    text: str
    time_window: tuple[str, str] = ("", "")  # (start_date, end_date)


class SignalHypotheses(BaseModel):
    """All hypotheses for a single signal, plus the consolidated search query."""
    signal_id: str
    causes: list[Hypothesis] = Field(default_factory=list)
    effects: list[Hypothesis] = Field(default_factory=list)
    consolidated_search_query: str = ""


# ---------------------------------------------------------------------------
# Sources & Events
# ---------------------------------------------------------------------------

class SourceRef(BaseModel):
    """Reference to a source document (article, policy brief, report, etc.)."""
    title: str
    url: str = ""
    snippet: str = ""
    date: str = ""
    source_domain: str = ""


class Event(BaseModel):
    """A real-world event extracted from search results by an LLM."""
    event_id: str = Field(default_factory=_short_id)
    headline: str
    summary: str
    date_range: str
    role: Literal["cause", "effect"]
    actors: list[str] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    originating_hypothesis_id: str = ""


# ---------------------------------------------------------------------------
# Scoring & Insights
# ---------------------------------------------------------------------------

class InsightConnection(BaseModel):
    """A scored link between a signal and an event."""
    signal_id: str
    event_id: str
    direction: Literal[
        "event_caused_signal",
        "signal_caused_event",
        "correlated",
    ]
    transmission_channel: str
    relevancy_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)


class Insight(BaseModel):
    """An assembled insight linking signals to events via scored connections."""
    insight_id: str = Field(default_factory=_short_id)
    primary_signal_id: str
    connections: list[InsightConnection] = Field(default_factory=list)
    headline: str = ""
    narrative: str = ""


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

class InsightResult(BaseModel):
    """Complete pipeline output."""
    questions: list[AnalystQuestion] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    filtered_signals: list[Signal] = Field(default_factory=list)
    hypotheses: list[SignalHypotheses] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    narrative: str = ""
