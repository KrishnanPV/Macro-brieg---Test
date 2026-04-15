"""Insights Lab endpoint — standalone investigation pipeline."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.models.insights import InsightLabRequest
from backend.pipelines.insights_lab import run_pipeline

router = APIRouter(prefix="/api/insights-lab", tags=["insights-lab"])


@router.post("/run")
def run_insights_lab(req: InsightLabRequest):
    """Run the full insights investigation pipeline, streaming NDJSON."""
    return StreamingResponse(
        run_pipeline(req),
        media_type="application/x-ndjson",
    )
