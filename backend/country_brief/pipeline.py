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
import uuid
from datetime import datetime
from typing import Any, Iterator

from backend.config import OPENAI_MODEL
from backend.models.kpi_registry import SPECS
from backend.models.schemas import CountryBriefGenerateRequest
from backend.services.derived_facts import compute_derived_facts
from backend.services.knoema_client import fetch_kpi_data, fetch_oil_price_data
from backend.services.kpi_triage import triage_kpis
from backend.services.metrics_ribbon import compute_ribbon_metrics
from backend.services.signals import extract_signals

from backend.country_brief.agents.signal_interpreter import interpret_signals
from backend.country_brief.agents.news_researcher import research_signals
from backend.country_brief.agents.benchmark_selector import select_benchmark_countries
from backend.country_brief.agents.brief_writer import stream_brief, parse_brief_blocks
from backend.country_brief.fdi_benchmark import build_fdi_benchmark_payload
from backend.country_brief.prompts import build_brief_prompt

log = logging.getLogger(__name__)

# GCC economies — matches frontend region grouping (CountryBrief / Dashboard).
_GCC_CODES = frozenset({"SAU", "ARE", "QAT", "KWT", "BHR", "OMN"})
_OIL_NON_OIL_KPI = "2"

# In-memory cache so the frontend can re-slice FDI benchmarks by year
# without re-fetching from Oxford Economics. Keyed by a random UUID.
_fdi_benchmark_cache: dict[str, dict[str, Any]] = {}


def _ndjson(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def get_fdi_cache_entry(cache_key: str) -> dict[str, Any] | None:
    return _fdi_benchmark_cache.get(cache_key)


def set_fdi_cache_entry(cache_key: str, entry: dict[str, Any]) -> None:
    _fdi_benchmark_cache[cache_key] = entry


def _extract_all_years(fdi_result: dict[str, Any]) -> list[int]:
    years: set[int] = set()
    for s in fdi_result.get("series") or []:
        for p in s.get("points") or []:
            d = p.get("date")
            if not d:
                continue
            try:
                years.add(datetime.fromisoformat(str(d).replace("Z", "+00:00")).year)
            except Exception:
                continue
    return sorted(years)


def recompute_fdi_benchmark(
    cache_key: str,
    start_year: int,
    end_year: int,
) -> dict[str, Any] | None:
    """Re-slice a cached FDI benchmark for a new year window."""
    cached = _fdi_benchmark_cache.get(cache_key)
    if not cached:
        return None
    payload = build_fdi_benchmark_payload(
        target_country=cached["target_country"],
        start_year=start_year,
        end_year=end_year,
        fdi_result=cached["fdi_result"],
        benchmark_selection=cached["benchmark_selection"],
    )
    if payload:
        payload["benchmark_cache_key"] = cache_key
        all_years = _extract_all_years(cached["fdi_result"])
        payload["min_year"] = min(all_years) if all_years else start_year
        payload["max_year"] = max(all_years) if all_years else end_year
    return payload


def _collect_chart_ids(blocks: list[dict[str, Any]]) -> set[str]:
    chart_ids: set[str] = set()
    for block in blocks:
        if block.get("type") != "section":
            continue
        for child in block.get("children") or []:
            if child.get("type") == "chart_ref":
                kid = str(child.get("kpi_id", "")).strip()
                if kid:
                    chart_ids.add(kid)
    return chart_ids


def _ensure_chart_blocks(
    blocks: list[dict[str, Any]],
    *,
    preferred_chart_ids: list[str],
) -> list[dict[str, Any]]:
    if not preferred_chart_ids:
        return blocks
    existing = _collect_chart_ids(blocks)
    if existing:
        return blocks

    fallback_charts = [{"type": "chart_ref", "kpi_id": kid} for kid in preferred_chart_ids]
    for block in blocks:
        if block.get("type") != "section":
            continue
        children = list(block.get("children") or [])
        block["children"] = [*children, *fallback_charts]
        return blocks

    blocks.append({
        "type": "section",
        "title": "Data Visuals",
        "children": fallback_charts,
    })
    return blocks


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
    # Automatic + GCC: always fetch oil/non-oil; other economies rely on triage-only selection.
    if not manual_selection and req.country.upper() in _GCC_CODES:
        if _OIL_NON_OIL_KPI not in available_ids:
            available_ids.append(_OIL_NON_OIL_KPI)
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
    # Oil price overlay for KPI 2 (Oil vs Non-Oil GDP)
    if _OIL_NON_OIL_KPI in available_ids:
        yield _ndjson({"type": "status", "content": "Fetching Brent oil price overlay..."})
        try:
            oil_overlay = fetch_oil_price_data(
                country=req.country,
                timerange=timerange,
                frequency="A",
            )
            if oil_overlay:
                for r in fetch_resp.results:
                    if r.kpi_id == _OIL_NON_OIL_KPI:
                        r.oil_price_overlay = oil_overlay
                        break
                log.info("Oil price overlay attached for %s", req.country)
            else:
                log.info("Oil price overlay unavailable for %s — skipping.", req.country)
        except Exception as exc:
            log.warning("Oil price overlay failed for %s: %s", req.country, exc)

    results_raw = [r.model_dump() for r in fetch_resp.results]
    yield _ndjson({"type": "kpi_data", "content": results_raw})

    valid_results = [r for r in results_raw if r.get("series")]

    fdi_benchmark_payload: dict[str, Any] | None = None
    if "4" in available_ids:
        yield _ndjson({"type": "status", "content": "Selecting FDI benchmark peers..."})
        benchmark_selection = select_benchmark_countries(
            req.country,
            start_year=req.start_year,
            end_year=req.end_year,
        )
        benchmark_fetch_countries = [req.country, *benchmark_selection.get("backfill_pool", [])]
        deduped_benchmark_countries: list[str] = []
        seen_codes: set[str] = set()
        for code in benchmark_fetch_countries:
            iso3 = str(code).upper().strip()
            if not iso3 or iso3 in seen_codes:
                continue
            deduped_benchmark_countries.append(iso3)
            seen_codes.add(iso3)

        if deduped_benchmark_countries:
            yield _ndjson({"type": "status", "content": "Building FDI benchmark chart data..."})
            fdi_fetch = fetch_kpi_data(
                countries=deduped_benchmark_countries,
                kpi_ids=["4"],
                timerange_q=timerange,
                timerange_a=timerange,
                frequency_overrides={"4": "A"},
            )
            fdi_result = None
            if fdi_fetch.results:
                fdi_result = fdi_fetch.results[0].model_dump()
            fdi_benchmark_payload = build_fdi_benchmark_payload(
                target_country=req.country,
                start_year=req.start_year,
                end_year=req.end_year,
                fdi_result=fdi_result or {},
                benchmark_selection=benchmark_selection,
            )
            if fdi_benchmark_payload:
                cache_key = uuid.uuid4().hex
                _fdi_benchmark_cache[cache_key] = {
                    "target_country": req.country,
                    "fdi_result": fdi_result or {},
                    "benchmark_selection": benchmark_selection,
                }
                fdi_benchmark_payload["benchmark_cache_key"] = cache_key
                all_years = _extract_all_years(fdi_result or {})
                fdi_benchmark_payload["min_year"] = min(all_years) if all_years else req.start_year
                fdi_benchmark_payload["max_year"] = max(all_years) if all_years else req.end_year
                yield _ndjson({"type": "fdi_benchmark", "content": fdi_benchmark_payload})

    # ── Phase 2: Agent 1 — Signal Detection + Interpretation ─────────────
    yield _ndjson({"type": "status", "content": "Detecting signals..."})

    derived_facts = compute_derived_facts(valid_results)
    scores = triage_kpis(derived_facts)
    notable_ids = [s.kpi_id for s in scores if s.notable]

    ids_with_data = {str(r.get("kpi_id")) for r in valid_results}
    if manual_selection:
        notable_ids = [kid for kid in available_ids if kid in ids_with_data]
    elif req.country.upper() in _GCC_CODES:
        if _OIL_NON_OIL_KPI in ids_with_data and _OIL_NON_OIL_KPI not in notable_ids:
            notable_ids.append(_OIL_NON_OIL_KPI)

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
        fdi_benchmark_context=fdi_benchmark_payload,
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
    fallback_chart_ids = [kid for kid in available_ids if kid in ids_with_data]
    blocks = _ensure_chart_blocks(blocks, preferred_chart_ids=fallback_chart_ids)
    computed_metrics = compute_ribbon_metrics(derived_facts)
    if computed_metrics:
        blocks = [b for b in blocks if b.get("type") != "metrics_ribbon"]
        blocks.insert(0, {"type": "metrics_ribbon", "metrics": computed_metrics})

    yield _ndjson({"type": "blocks", "content": blocks})
    yield _ndjson({"type": "done"})
