"""Pydantic contracts for dashboard insights APIs."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardCountryInsightRequest(BaseModel):
    """Generate insights for one country and one KPI payload."""

    country: str = Field(..., min_length=3, max_length=3)
    kpi_result: dict[str, Any]
    reasoning_model: str | None = Field(default=None, min_length=1)


class DashboardCrossCountryInsightRequest(BaseModel):
    """Generate cross-country insights for one KPI payload."""

    countries: list[str] = Field(..., min_length=2)
    kpi_result: dict[str, Any]
    reasoning_model: str | None = Field(default=None, min_length=1)

