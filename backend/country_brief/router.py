"""Country Brief HTTP endpoints.

Thin layer over the 3-agent pipeline.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.models.schemas import CountryBriefGenerateRequest, CountryBriefRefineRequest
from backend.country_brief.pipeline import (
    run_pipeline, recompute_fdi_benchmark, get_fdi_cache_entry, set_fdi_cache_entry,
)
from backend.country_brief.brief_writer import stream_refine

log = logging.getLogger(__name__)

_TEST_REPORT_PATH = Path(__file__).parent / "_test_report.json"

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


@router.post("/fdi-benchmark")
async def refresh_fdi_benchmark(request: Request):
    """Re-slice FDI benchmark data for a different year window."""
    body = await request.json()
    cache_key = body.get("benchmark_cache_key")
    start_year = body.get("start_year")
    end_year = body.get("end_year")
    if not cache_key or start_year is None or end_year is None:
        raise HTTPException(status_code=400, detail="Missing required fields.")
    if int(start_year) >= int(end_year):
        raise HTTPException(status_code=400, detail="start_year must be less than end_year.")
    result = recompute_fdi_benchmark(cache_key, int(start_year), int(end_year))
    if result is None:
        raise HTTPException(status_code=404, detail="Benchmark cache expired or not found. Regenerate the brief.")
    return result


def _require_debug():
    if os.environ.get("MACROBRIEF_DEBUG") != "1":
        raise HTTPException(status_code=403, detail="Debug mode is not enabled.")


@router.post("/test-report/store")
async def store_test_report(request: Request):
    """Save the current report snapshot to disk (debug only)."""
    _require_debug()
    body = await request.json()
    benchmark = body.get("fdiBenchmark") or {}
    cache_key = benchmark.get("benchmark_cache_key")
    if cache_key:
        entry = get_fdi_cache_entry(cache_key)
        if entry:
            body["_fdi_cache_entry"] = entry
    _TEST_REPORT_PATH.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


@router.get("/test-report/load")
def load_test_report():
    """Load a previously stored report snapshot from disk (debug only)."""
    _require_debug()
    if not _TEST_REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="No stored test report found.")
    data = json.loads(_TEST_REPORT_PATH.read_text(encoding="utf-8"))
    fdi_cache_entry = data.pop("_fdi_cache_entry", None)
    benchmark = data.get("fdiBenchmark") or {}
    cache_key = benchmark.get("benchmark_cache_key")
    if cache_key and fdi_cache_entry:
        set_fdi_cache_entry(cache_key, fdi_cache_entry)
    return data
