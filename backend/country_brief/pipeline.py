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
import sys
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
from backend.services.signals import extract_signals, rank_signals

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


_KPI_SECTION_ORDER = {
    "3": 1, "2": 1, "11": 1, "1": 1,
    "4": 2, "8": 2,
    "7": 3,
    "5": 4, "6": 4,
    "9": 5,
}

_KPI_DISPLAY_ORDER: dict[str, int] = {
    "3": 0, "2": 1, "11": 2, "1": 3,
    "4": 0, "8": 1,
    "7": 0,
    "5": 0, "6": 1,
    "9": 0,
}


def _compute_exhibit_map(notable_kpi_ids: list[str]) -> dict[str, str]:
    """Pre-compute deterministic exhibit labels (e.g. '1A', '2A') from notable KPIs."""
    section_kpis: dict[int, list[str]] = {}
    for kid in notable_kpi_ids:
        sec = _KPI_SECTION_ORDER.get(kid)
        if sec:
            section_kpis.setdefault(sec, []).append(kid)
    exhibit_map: dict[str, str] = {}
    for sec in sorted(section_kpis):
        kpis = sorted(section_kpis[sec], key=lambda k: _KPI_DISPLAY_ORDER.get(k, 99))
        for i, kid in enumerate(kpis):
            letter = chr(ord("A") + i)
            exhibit_map[kid] = f"{sec}{letter}"
    return exhibit_map


def _assign_exhibit_labels(blocks: list[dict[str, Any]], exhibit_map: dict[str, str]) -> None:
    """Attach exhibit_label to each chart_ref block in-place."""
    for block in blocks:
        if block.get("type") != "section":
            continue
        for child in block.get("children") or []:
            if child.get("type") == "chart_ref":
                kid = str(child.get("kpi_id", ""))
                label = exhibit_map.get(kid)
                if label:
                    child["exhibit_label"] = label


def _is_demographics_section_title(title: str) -> bool:
    """Match demographics section even if the model shortens the heading."""
    t = (title or "").lower()
    return "demographic" in t


def _ensure_kpi9_demographics_chart(
    blocks: list[dict[str, Any]],
    ids_with_data: set[str],
) -> list[dict[str, Any]]:
    """Ensure population (KPI 9) chart sits under the Demographics section.

    Inserts the section before Forward Outlook if missing; strips misplaced KPI 9
    charts from other sections; appends chart_ref when needed.
    """
    if "9" not in ids_with_data:
        return blocks

    demo_idx: int | None = None
    for i, b in enumerate(blocks):
        if b.get("type") == "section" and _is_demographics_section_title(b.get("title", "")):
            demo_idx = i
            break

    if demo_idx is None:
        insert_at = len(blocks)
        for i, b in enumerate(blocks):
            if b.get("type") == "outlook":
                insert_at = i
                break
        blocks.insert(insert_at, {
            "type": "section",
            "title": "Demographics & Structural Factors",
            "children": [],
        })
        demo_idx = insert_at

    for i, b in enumerate(blocks):
        if i == demo_idx or b.get("type") != "section":
            continue
        oc = list(b.get("children") or [])
        b["children"] = [
            c for c in oc
            if not (c.get("type") == "chart_ref" and str(c.get("kpi_id")) == "9")
        ]

    demo = blocks[demo_idx]
    children = list(demo.get("children") or [])
    if not any(
        c.get("type") == "chart_ref" and str(c.get("kpi_id")) == "9"
        for c in children
    ):
        children.append({"type": "chart_ref", "kpi_id": "9"})
    demo["children"] = children
    return blocks


def _inject_oil_gdp_split(blocks: list[dict[str, Any]], is_gcc: bool, exhibit_map: dict[str, str]) -> None:
    """For GCC countries, insert a '2-oil' chart_ref after KPI 2 in the growth section."""
    if not is_gcc:
        return
    for block in blocks:
        if block.get("type") != "section":
            continue
        children = block.get("children") or []
        insert_after = None
        for i, child in enumerate(children):
            if child.get("type") == "chart_ref" and str(child.get("kpi_id")) == "2":
                insert_after = i
                break
        if insert_after is not None:
            oil_label = None
            if "2" in exhibit_map:
                base_sec = exhibit_map["2"][0]
                existing_in_sec = sum(1 for c in children if c.get("type") == "chart_ref")
                oil_label = f"{base_sec}{chr(ord('A') + existing_in_sec)}"
            oil_chart = {"type": "chart_ref", "kpi_id": "2-oil"}
            if oil_label:
                oil_chart["exhibit_label"] = oil_label
            children.insert(insert_after + 1, oil_chart)
            break


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
        manual_notable_set = set(notable_ids)
        for s in scores:
            selected = s.kpi_id in manual_notable_set
            if selected and not s.notable:
                s.reasons.append("selected manually")
            s.notable = selected
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

    # Full KPI context for news breadth (before pre-filtering narrows KPI diversity)
    all_kpi_signals: dict[str, list[str]] = {}
    for s in all_signals:
        all_kpi_signals.setdefault(s.kpi_name, []).append(s.description)

    top_signals = rank_signals(all_signals, scores)
    signals_data = [
        {"signal_id": s.signal_id, "kpi_id": s.kpi_id, "kpi_name": s.kpi_name,
         "country": s.country, "signal_type": s.signal_type,
         "from_date": s.from_date, "to_date": s.to_date,
         "from_value": s.from_value, "to_value": s.to_value,
         "magnitude_pct": s.magnitude_pct, "description": s.description}
        for s in top_signals
    ]

    yield _ndjson({"type": "status", "content": "Interpreting signals..."})
    signal_interpretation = interpret_signals(
        signals_data, req.country, req.start_year, req.end_year,
        notable_kpi_ids=notable_ids,
    )

    # ── Phase 3: Agent 2 — News Correlation (deep search only) ───────────
    articles_flat: list[dict[str, Any]] = []
    prompt_bundle: dict[str, Any] | None = None

    if deep_analysis and signals_data:
        yield _ndjson({"type": "status", "content": "Searching for correlated news..."})
        try:
            articles_flat, prompt_bundle = research_signals(
                signals_data, req.country, req.start_year, req.end_year,
                signal_interpretation=signal_interpretation,
                all_kpi_signals=all_kpi_signals,
            )
            n = len(articles_flat)
            # print + flush: visible in the uvicorn terminal (app loggers are easy to miss)
            def _pplx_line(msg: str) -> None:
                print(msg, file=sys.stderr, flush=True)

            _pplx_line("========== Perplexity / news research ==========")
            _pplx_line(f"Country {req.country} | articles in news_catalog: {n}")
            preview_n = min(n, 12)
            for i, a in enumerate(articles_flat[:preview_n], 1):
                title = (a.get("title") or "")[:100]
                dt = a.get("date") or ""
                src = a.get("source") or ""
                url = (a.get("url") or "")[:80]
                snip = (a.get("snippet") or "")[:160].replace("\n", " ")
                _pplx_line(f"  [{i}/{n}] {title} | date={dt} | source={src}")
                _pplx_line(f"        url: {url}")
                _pplx_line(f"        snippet: {snip}")
            if n > preview_n:
                _pplx_line(f"  ... {n - preview_n} more (omitted from terminal preview)")
            _pplx_line("==================================================")
            log.info("Perplexity news_catalog: %d articles", n)
        except Exception as exc:
            print(f"[Perplexity] ERROR: {exc}", file=sys.stderr, flush=True)
            log.warning("News research failed: %s", exc)
    elif not deep_analysis:
        print(
            "[Perplexity] Skipped: deep_analysis=False (enable deep analysis for news fetch)",
            file=sys.stderr,
            flush=True,
        )
    elif not signals_data:
        print(
            "[Perplexity] Skipped: no signals_data after ranking (nothing to match to news)",
            file=sys.stderr,
            flush=True,
        )

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

    period_highlight = ""
    if isinstance(signal_interpretation, dict):
        period_highlight = signal_interpretation.get("period_highlight", "")

    injection = (
        "SIGNAL INTERPRETATION (from analysis agent):\n"
        f"```json\n{interpretation_json}\n```\n\n"
    )

    if period_highlight:
        injection += (
            f"PERIOD HIGHLIGHT (use this as the governing thought for the executive summary):\n"
            f"{period_highlight}\n\n"
        )

    injection += (
        "HOW TO USE THIS INTERPRETATION:\n"
        "Each causal_chain has a trigger, mechanism, and kpi_impact. "
        "Translate each into a natural prose bullet — name the trigger, explain the channel, "
        "cite the data outcome. Do NOT use arrow symbols or template notation in your prose. "
        "Ignore noise_signals. Use cross_kpi_connections to synthesize.\n\n"
    )

    if deep_analysis and articles_flat:
        injection += (
            "NEWS CONTEXT:\n"
            "Use 2-3 news [src:N] citations across the ENTIRE brief where a named policy, "
            "event, or decision validates a structural claim. Do not force citations into "
            "every section.\n\n"
        )

    exhibit_map = _compute_exhibit_map(notable_ids)
    if exhibit_map:
        exhibit_lines = ", ".join(f"KPI {k} = ({v})" for k, v in sorted(exhibit_map.items()))
        injection += (
            f"EXHIBIT MAP — cite these labels when referencing chart data:\n"
            f"{exhibit_lines}\n"
            "When stating a number from a chart, append the exhibit label in parentheses: "
            "e.g. 'GDP grew 3.2% (1A)'. Do NOT write 'Exhibit' — just the code.\n\n"
        )

    injection += (
        "REMINDER — MANDATORY RULES:\n"
        "1. Produce exactly these 5 sections: Economic Performance & Growth, "
        "Investment & External Position, Inflation & Monetary Conditions, "
        "Labour Market & Domestic Demand, Demographics & Structural Factors.\n"
        "2. NEVER merge sections 3 and 4.\n"
        "3. TOP-DOWN per section: Bullet 1 = GOVERNING INSIGHT — bold the ENTIRE "
        "first sentence (structural takeaway), then un-bolded data with exhibit citations. "
        "Bullet 2 = composition/drivers with sub-bullets (indented '  - '). "
        "Bullet 3 = volatility ONLY if genuine reversal (skip if smooth). "
        "Bullet 4 = forward projection.\n"
        "4. Max 4-5 top-level bullets per section. Sub-bullets do not count.\n"
        "5. Use annual time references. No quarterly notation.\n"
        "6. Place each [CHART:kpi_id] only ONCE in the entire brief.\n"
        "7. No fluff, no bridging filler, no restating previous bullets.\n"
        "8. State start and end values. Do NOT narrate year-by-year. Only highlight an "
        "intermediate year if there was a drastic reversal.\n"
        "9. When aggregate GDP growth changes, state whether oil or non-oil GDP drove it. "
        "For GCC, connect oil GDP to oil price movements. Note: GDP is real, oil prices "
        "are nominal — flat oil GDP with rising prices reflects volume constraints.\n"
        "10. Decompose net FDI changes: state whether driven by inflow growth, outflow "
        "moderation, or both.\n"
        "11. When external debt as % of GDP changes, decompose numerator vs denominator.\n"
        "12. For Investment section: include one bullet benchmarking the country's FDI "
        "against peers from FDI_BENCHMARK_CONTEXT, if available.\n"
        "13. BOLDING: Bold ONLY the first sentence of each section's Bullet 1. Do NOT "
        "bold numbers. Maximum 1-2 structural phrases bolded across remaining bullets."
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
    blocks = _ensure_kpi9_demographics_chart(blocks, ids_with_data)
    fallback_chart_ids = [kid for kid in available_ids if kid in ids_with_data]
    blocks = _ensure_chart_blocks(blocks, preferred_chart_ids=fallback_chart_ids)
    _assign_exhibit_labels(blocks, exhibit_map)
    _inject_oil_gdp_split(blocks, req.country.upper() in _GCC_CODES, exhibit_map)
    computed_metrics = compute_ribbon_metrics(derived_facts)
    if computed_metrics:
        blocks = [b for b in blocks if b.get("type") != "metrics_ribbon"]
        blocks.insert(0, {"type": "metrics_ribbon", "metrics": computed_metrics})

    yield _ndjson({"type": "blocks", "content": blocks})
    yield _ndjson({"type": "done"})
