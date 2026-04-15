"""Country Brief generation and refinement endpoints.

The generation logic lives in backend.pipelines.country_brief; this router
is a thin HTTP layer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.models.schemas import CountryBriefGenerateRequest, CountryBriefRefineRequest
from backend.pipelines.country_brief import run_pipeline
from backend.prompts.brief_prompts import build_refine_prompt

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/country-brief", tags=["country-brief"])


def _get_client():
    from openai import OpenAI
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _temperature_kw(model: str) -> dict[str, float]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.3}


# ---------------------------------------------------------------------------
# POST /api/country-brief/generate
# ---------------------------------------------------------------------------

@router.post("/generate")
def generate_country_brief(req: CountryBriefGenerateRequest):
    """Generate a full country brief with streaming NDJSON blocks."""
    return StreamingResponse(
        run_pipeline(req, deep_analysis=req.deep_analysis),
        media_type="application/x-ndjson",
    )


# ---------------------------------------------------------------------------
# POST /api/country-brief/refine
# ---------------------------------------------------------------------------

@router.post("/refine")
def refine_section(req: CountryBriefRefineRequest):
    """Refine a section of the brief via chat."""

    messages = build_refine_prompt(
        section_content=req.section_content,
        data_context=req.data_context,
        message=req.message,
        history=req.history,
    )

    client = _get_client()
    model = OPENAI_MODEL

    def _stream():
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=2048,
            stream=True,
            **_temperature_kw(model),
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield json.dumps({"type": "text", "content": delta.content}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")
