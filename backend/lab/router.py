"""HTTP endpoints for lab pipeline."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.lab.pipeline import run_pipeline
from backend.lab.schemas import LabGenerateRequest

router = APIRouter(prefix="/api/lab", tags=["lab"])


@router.get("/health")
def health() -> dict[str, bool]:
    """Simple endpoint for frontend readiness checks."""
    return {"ok": True}


@router.post("/generate")
def generate_lab_insights(req: LabGenerateRequest):
    """Run the lab workflow and stream stage events as NDJSON."""
    return StreamingResponse(
        run_pipeline(req),
        media_type="application/x-ndjson",
    )

