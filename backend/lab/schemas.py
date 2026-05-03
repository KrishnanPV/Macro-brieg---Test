"""Pydantic contracts for lab endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LabGenerateRequest(BaseModel):
    """Request payload for insight generation in lab mode."""

    country: str = Field(..., min_length=3, max_length=3, description="ISO3 country code")
    kpi_id: str = Field(..., min_length=1)
    start_year: int = Field(2015, ge=1990, le=2100)
    end_year: int = Field(2026, ge=1990, le=2100)


class LabStreamEvent(BaseModel):
    """Standard NDJSON event shape emitted by the lab pipeline."""

    type: str
    stage: str | None = None
    content: Any = None
    meta: dict[str, Any] = Field(default_factory=dict)

