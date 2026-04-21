"""Pydantic models for signal detection in KPI data."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field
import uuid


def _short_id() -> str:
    return uuid.uuid4().hex[:10]


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
