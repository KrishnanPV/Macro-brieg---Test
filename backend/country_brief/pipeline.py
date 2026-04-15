"""Country Brief pipeline orchestrator — wires the 3 agents together.

Flow:
  1. Fetch KPI data from Oxford Economics           (deterministic)
  2. Compute derived facts + triage + signals       (deterministic math)
  3. Agent 1: interpret signals                     (1 GPT call)
  4. Agent 2: research news — if deep_analysis      (0-1 Perplexity call)
  5. Agent 3: stream the brief                      (1 GPT call, streamed)
  6. Parse blocks + override metrics ribbon          (deterministic)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

from backend.config import OPENAI_MODEL
from backend.models.kpi_registry import SPECS
from backend.models.schemas import CountryBriefGenerateRequest
from backend.services.derived_facts import compute_derived_facts
from backend.services.knoema_client import fetch_kpi_data
from backend.services.kpi_triage import triage_kpis
from backend.services.metrics_ribbon import compute_ribbon_metrics
from backend.services.signals import extract_signals

from backend.country_brief.agents.signal_interpreter import interpret_signals
from backend.country_brief.agents.news_researcher import research_signals
from backend.country_brief.agents.brief_writer import stream_brief, parse_brief_blocks
from backend.country_brief.prompts import build_brief_prompt

log = logging.getLogger(__name__)


def _ndjson(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def run_pipeline(
    req: CountryBriefGenerateRequest,
    *,
    deep_analysis: bool = False,
) -> Iterator[str]:
    """Generate a country brief using the 3-agent pipeline.

    Agent 1: Math signals + 1 GPT interpretation call
    Agent 2: 1 Perplexity news call (only if deep_analysis=True)
    Agent 3: 1 GPT call to write the final brief
    """
    all_oxford_ids = [s.id for s in SPECS if s.source == "oxford"]
    manual_selection = bool(req.kpi_ids)
    available_ids = req.kpi_ids if req.kpi_ids else all_oxford_ids
    available_ids = [kid for kid in available_ids if kid in {s.id for s in SPECS if s.source == "oxford"}]
    if not available_ids:
        available_ids = all_oxford_ids
    # In automatic mode, always include the 3 core GDP KPIs
    GDP_CORE_IDS = ["3", "11", "2"]
    if not manual_selection:
        for kid in GDP_CORE_IDS:
            if kid not in available_ids:
                available_ids.append(kid)
    timerange = f"{req.start_year}-{req.end_year}"

    # ── Phase 1: Fetch KPI data ──────────────────────────────────────────
    yield _ndjson({"type": "status", "content": f"Fetching data for {len(available_ids)} KPIs..."})

    fetch_resp = fetch_kpi_data(
        countries=[req.country],
        kpi_ids=available_ids,
        timerange_q=timerange,
        timerange_a=timerange,
        dual_fetch=True,
    )
    results_raw = [r.model_dump() for r in fetch_resp.results]
    yield _ndjson({"type": "kpi_data", "content": results_raw})

    valid_results = [r for r in results_raw if r.get("series")]

    # ── Phase 2: Agent 1 — Signal Detection + Interpretation ─────────────
    yield _ndjson({"type": "status", "content": "Detecting signals..."})

    derived_facts = compute_derived_facts(valid_results)
    scores = triage_kpis(derived_facts)
    notable_ids = [s.kpi_id for s in scores if s.notable]

    if manual_selection:
        ids_with_data = {str(r.get("kpi_id")) for r in valid_results}
        notable_ids = [kid for kid in available_ids if kid in ids_with_data]
    else:
        # Force core GDP KPIs as notable so they always get brief sections
        for kid in GDP_CORE_IDS:
            if kid not in notable_ids:
                notable_ids.append(kid)

    yield _ndjson({
        "type": "triage",
        "content": [
            {"kpi_id": s.kpi_id, "kpi_name": s.kpi_name,
             "score": s.score, "notable": s.notable, "reasons": s.reasons}
            for s in scores
        ],
    })

    all_signals = extract_signals(valid_results)
    signals_data = [
        {"signal_id": s.signal_id, "kpi_id": s.kpi_id, "kpi_name": s.kpi_name,
         "country": s.country, "signal_type": s.signal_type,
         "from_date": s.from_date, "to_date": s.to_date,
         "from_value": s.from_value, "to_value": s.to_value,
         "magnitude_pct": s.magnitude_pct, "description": s.description}
        for s in all_signals
    ]

    yield _ndjson({"type": "status", "content": "Interpreting signals..."})
    signal_interpretation = interpret_signals(
        signals_data, req.country, req.start_year, req.end_year,
    )

    # ── Phase 3: Agent 2 — News Correlation (deep search only) ───────────
    articles_flat: list[dict[str, Any]] = []
    prompt_bundle: dict[str, Any] | None = None

    if deep_analysis and signals_data:
        yield _ndjson({"type": "status", "content": "Searching for correlated news..."})
        try:
            articles_flat, prompt_bundle = research_signals(
                signals_data, req.country, req.start_year, req.end_year,
            )
            log.info("Perplexity returned %d articles", len(articles_flat))
        except Exception as exc:
            log.warning("News research failed: %s", exc)

    yield _ndjson({
        "type": "news_catalog",
        "content": {"articles": articles_flat},
    })

    # ── Phase 4: Agent 3 — Brief Writer ──────────────────────────────────
    yield _ndjson({"type": "status", "content": "Writing brief..."})

    messages = build_brief_prompt(
        country=req.country,
        start_year=req.start_year,
        end_year=req.end_year,
        results=valid_results,
        derived_facts=derived_facts,
        notable_kpi_ids=notable_ids,
        news_context=None,
        news_prompt_bundle=prompt_bundle,
        focus=req.focus,
        manual_selection=manual_selection,
    )

    interpretation_json = json.dumps(signal_interpretation, indent=2, default=str)
    injection = (
        "SIGNAL INTERPRETATION (from analysis agent):\n"
        f"```json\n{interpretation_json}\n```\n\n"
        "Use these thematic groupings, identified drivers, and cross-KPI connections "
        "to structure your narrative. Ignore signals flagged as noise."
    )

    if deep_analysis and articles_flat:
        injection += (
            "\n\nNEWS CORRELATION: Perplexity research found articles that explain "
            "the data movements. Use [src:N] markers at the END of sentences grounded "
            "in specific articles (where N is the article's \"n\" value)."
        )

    messages.append({"role": "user", "content": injection})

    full_text = ""
    for event_type, payload in stream_brief(messages):
        if event_type == "text_delta":
            yield _ndjson({"type": "text_delta", "content": payload})
        elif event_type == "full_text":
            full_text = payload

    # ── Phase 5: Parse and finalize ──────────────────────────────────────
    blocks = parse_brief_blocks(full_text)
    computed_metrics = compute_ribbon_metrics(derived_facts)
    if computed_metrics:
        blocks = [b for b in blocks if b.get("type") != "metrics_ribbon"]
        blocks.insert(0, {"type": "metrics_ribbon", "metrics": computed_metrics})

    yield _ndjson({"type": "blocks", "content": blocks})
    yield _ndjson({"type": "done"})
