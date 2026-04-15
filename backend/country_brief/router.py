"""Country Brief HTTP endpoints.

Thin layer over the 3-agent pipeline.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.models.schemas import CountryBriefGenerateRequest, CountryBriefRefineRequest
from backend.country_brief.pipeline import run_pipeline
from backend.country_brief.agents.brief_writer import stream_refine

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/country-brief", tags=["country-brief"])


@router.post("/generate")
def generate_country_brief(req: CountryBriefGenerateRequest):
    """Generate a full country brief with streaming NDJSON blocks."""
    return StreamingResponse(
        run_pipeline(req, deep_analysis=req.deep_analysis),
        media_type="application/x-ndjson",
    )


@router.post("/refine")
def refine_section(req: CountryBriefRefineRequest):
    """Refine a section of the brief via chat."""

    def _stream():
        for event_type, content in stream_refine(
            section_content=req.section_content,
            data_context=req.data_context,
            message=req.message,
            history=req.history,
        ):
            yield json.dumps({"type": event_type, "content": content}) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
