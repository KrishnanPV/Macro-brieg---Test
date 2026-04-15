"""Orchestrator: chains all 7 pipeline steps, yielding NDJSON events for progressive rendering."""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from backend.services.knoema_client import fetch_kpi_data
from backend.models.kpi_registry import SPECS_BY_ID, ISO3_TO_NAME
from backend.models.insights import InsightLabRequest, InsightResult
from backend.services.analyst_questions import generate_analyst_questions
from backend.services.signals import extract_signals, filter_signals_with_questions
from backend.services.hypotheses import generate_hypotheses
from backend.services.research import search_for_evidence
from backend.services.events import extract_events
from backend.services.scoring import score_and_assemble_insights
from backend.services.narrative import stream_narrative

log = logging.getLogger(__name__)


def _ndjson(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def run_pipeline(req: InsightLabRequest) -> Iterator[str]:
    """Execute the full 7-step insights pipeline, yielding NDJSON events."""

    spec = SPECS_BY_ID.get(req.kpi_id)
    kpi_name = spec.name if spec else f"KPI {req.kpi_id}"
    country_name = ISO3_TO_NAME.get(req.country, req.country)

    # ------------------------------------------------------------------
    # Step 1: Fetch KPI data
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Fetching KPI data..."})

    timerange = f"{req.start_year}-{req.end_year}"
    fetch_resp = fetch_kpi_data(
        countries=[req.country],
        kpi_ids=[req.kpi_id],
        timerange_q=timerange,
        timerange_a=timerange,
    )
    results_raw = [r.model_dump() for r in fetch_resp.results]
    valid_results = [r for r in results_raw if r.get("series")]

    yield _ndjson({"type": "kpi_data", "content": results_raw})

    if not valid_results:
        yield _ndjson({"type": "error", "content": "No data series returned for this KPI/country/time range."})
        yield _ndjson({"type": "done", "content": None})
        return

    # ------------------------------------------------------------------
    # Step 2: Generate analyst questions
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Generating analyst questions..."})

    questions = generate_analyst_questions(
        kpi_id=req.kpi_id,
        country=req.country,
        start_year=req.start_year,
        end_year=req.end_year,
    )
    yield _ndjson({
        "type": "questions",
        "content": [q.model_dump() for q in questions],
    })

    log.info("Generated %d analyst questions", len(questions))

    # ------------------------------------------------------------------
    # Step 3: Detect and filter signals
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Detecting signals in data..."})

    all_signals = extract_signals(valid_results)
    yield _ndjson({
        "type": "signals",
        "content": [s.model_dump() for s in all_signals],
    })

    log.info("Detected %d raw signals", len(all_signals))

    if not all_signals:
        yield _ndjson({"type": "status", "content": "No notable signals detected — data may be too stable."})
        yield _ndjson({"type": "done", "content": InsightResult(questions=questions).model_dump()})
        return

    yield _ndjson({"type": "status", "content": "Filtering signals by analyst questions..."})

    filtered_signals = filter_signals_with_questions(
        signals=all_signals,
        questions=questions,
        kpi_name=kpi_name,
        country=country_name,
    )
    yield _ndjson({
        "type": "filtered_signals",
        "content": [s.model_dump() for s in filtered_signals],
    })

    log.info("Filtered to %d signals", len(filtered_signals))

    # ------------------------------------------------------------------
    # Step 4: Generate hypotheses
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Generating hypotheses (causes & effects)..."})

    signal_hypotheses = generate_hypotheses(
        signals=filtered_signals,
        questions=questions,
        kpi_name=kpi_name,
        country=country_name,
    )
    yield _ndjson({
        "type": "hypotheses",
        "content": [sh.model_dump() for sh in signal_hypotheses],
    })

    log.info(
        "Generated hypotheses for %d signals",
        len(signal_hypotheses),
    )

    # ------------------------------------------------------------------
    # Step 5: Perplexity research + event extraction
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Searching for evidence (Perplexity)..."})

    search_results = search_for_evidence(
        signal_hypotheses=signal_hypotheses,
        country_iso3=req.country,
    )

    total_results = sum(len(v) for v in search_results.values())
    log.info("Perplexity returned %d total results", total_results)

    yield _ndjson({"type": "status", "content": f"Extracting events from {total_results} search results..."})

    events = extract_events(
        signals=filtered_signals,
        signal_hypotheses=signal_hypotheses,
        search_results=search_results,
    )
    yield _ndjson({
        "type": "events",
        "content": [e.model_dump() for e in events],
    })

    log.info("Extracted %d events", len(events))

    # ------------------------------------------------------------------
    # Step 6: Score connections and assemble insights
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Scoring signal-event connections..."})

    insights = score_and_assemble_insights(
        signals=filtered_signals,
        events=events,
        questions=questions,
    )
    yield _ndjson({
        "type": "insights",
        "content": [i.model_dump() for i in insights],
    })

    log.info("Assembled %d insights", len(insights))

    # ------------------------------------------------------------------
    # Step 7: Generate narrative
    # ------------------------------------------------------------------
    yield _ndjson({"type": "status", "content": "Generating narrative..."})

    kpi_data_for_narrative = {
        "kpi_id": req.kpi_id,
        "kpi_name": kpi_name,
        "country": req.country,
        "country_name": country_name,
        "start_year": req.start_year,
        "end_year": req.end_year,
        "results": valid_results,
    }

    full_narrative = ""
    for text_chunk in stream_narrative(insights, filtered_signals, events, kpi_data_for_narrative):
        full_narrative += text_chunk
        yield _ndjson({"type": "narrative_delta", "content": text_chunk})

    result = InsightResult(
        questions=questions,
        signals=all_signals,
        filtered_signals=filtered_signals,
        hypotheses=signal_hypotheses,
        events=events,
        insights=insights,
        narrative=full_narrative,
    )

    yield _ndjson({"type": "done", "content": result.model_dump()})
