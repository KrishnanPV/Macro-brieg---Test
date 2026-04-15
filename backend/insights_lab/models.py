"""Backward-compatibility shim — models live in backend.models.insights."""
from backend.models.insights import (  # noqa: F401
    AnalystQuestion,
    Event,
    Hypothesis,
    Insight,
    InsightConnection,
    InsightLabRequest,
    InsightResult,
    Signal,
    SignalHypotheses,
    SourceRef,
)
