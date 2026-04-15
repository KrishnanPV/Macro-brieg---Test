"""Country Brief generation pipeline — orchestrates data, triage, news, and LLM narrative.

Supports two modes:
- Standard (default): fast generation using derived facts + news + single LLM call
- Deep analysis (deep_analysis=True): runs a full hypothesis-driven investigation
  pipeline **per notable KPI in parallel**, then synthesizes cross-KPI connections,
  and feeds all structured evidence into the brief prompt.
"""
from __future__ import annotations

import json
import logging
import queue
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Iterator

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.models.kpi_registry import SPECS, SPECS_BY_ID, ISO3_TO_NAME
from backend.models.schemas import CountryBriefGenerateRequest
from backend.prompts.brief_prompts import build_brief_prompt
from backend.services.derived_facts import compute_derived_facts
from backend.services.knoema_client import fetch_kpi_data
from backend.services.kpi_triage import triage_kpis
from backend.services.metrics_ribbon import compute_ribbon_metrics
from backend.services.news_client import (
    COUNTRY_BRIEF_ARTICLES_PER_COUNTRY,
    fetch_news_bulk,
    flatten_news_catalog,
    synthesize_news_context,
)

log = logging.getLogger(__name__)

_MAX_SIGNALS_PER_KPI = 3


def _ndjson(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def _get_client():
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
# Block parser — converts raw LLM text with markers into typed blocks
# ---------------------------------------------------------------------------

_METRICS_RE = re.compile(r"\[METRICS_RIBBON\](.*?)\[/METRICS_RIBBON\]", re.DOTALL)
_EXEC_RE = re.compile(r"\[EXEC_SUMMARY\](.*?)\[/EXEC_SUMMARY\]", re.DOTALL)
_SECTION_RE = re.compile(r"\[SECTION:([^\]]+)\](.*?)\[/SECTION\]", re.DOTALL)
_OUTLOOK_RE = re.compile(r"\[OUTLOOK\](.*?)\[/OUTLOOK\]", re.DOTALL)
_CHART_RE = re.compile(r"\[CHART:(\d+)\]")


def _parse_metrics_ribbon(text: str) -> list[dict[str, str]]:
    metrics = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            metrics.append({"label": parts[0], "value": parts[1], "direction": parts[2]})
        elif len(parts) == 2:
            metrics.append({"label": parts[0], "value": parts[1], "direction": "flat"})
    return metrics


def _split_narrative_and_charts(body: str) -> list[dict[str, Any]]:
    """Split section body into alternating narrative and chart_ref blocks."""
    blocks: list[dict[str, Any]] = []
    parts = _CHART_RE.split(body)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            text = part.strip()
            if text:
                blocks.append({"type": "narrative", "content": text})
        else:
            blocks.append({"type": "chart_ref", "kpi_id": part.strip()})
    return blocks


def parse_brief_blocks(raw_text: str) -> list[dict[str, Any]]:
    """Parse the full LLM output into a list of typed blocks."""
    blocks: list[dict[str, Any]] = []

    m = _METRICS_RE.search(raw_text)
    if m:
        metrics = _parse_metrics_ribbon(m.group(1))
        if metrics:
            blocks.append({"type": "metrics_ribbon", "metrics": metrics})

    m = _EXEC_RE.search(raw_text)
    if m:
        blocks.append({"type": "executive_summary", "content": m.group(1).strip()})

    for m in _SECTION_RE.finditer(raw_text):
        title = m.group(1).strip()
        body = m.group(2).strip()
        sub_blocks = _split_narrative_and_charts(body)
        blocks.append({
            "type": "section",
            "title": title,
            "children": sub_blocks,
        })

    m = _OUTLOOK_RE.search(raw_text)
    if m:
        blocks.append({"type": "outlook", "content": m.group(1).strip()})
    else:
        # Fallback: try to detect an outlook section by markdown headings
        outlook_content = _extract_outlook_fallback(raw_text)
        if outlook_content:
            blocks.append({"type": "outlook", "content": outlook_content})

    return blocks


# Fallback regex: look for **Tailwinds** / **Headwinds** / **Net Assessment**
# patterns that might appear without the [OUTLOOK] wrapper
_TW_HW_RE = re.compile(
    r"\*\*Tailwinds\*\*",
    re.IGNORECASE,
)


def _extract_outlook_fallback(raw_text: str) -> str | None:
    """Try to extract outlook content when [OUTLOOK] markers are missing."""
    m = _TW_HW_RE.search(raw_text)
    if not m:
        return None

    # Already consumed by a [SECTION:...] block?
    for sm in _SECTION_RE.finditer(raw_text):
        if sm.start() <= m.start() < sm.end():
            return None

    # Take from **Tailwinds** to end of text (or next [/SECTION] etc.)
    remainder = raw_text[m.start():]
    # Trim at any trailing block marker
    for marker in ("[/SECTION]", "[METRICS_RIBBON]", "[EXEC_SUMMARY]"):
        idx = remainder.find(marker)
        if idx > 0:
            remainder = remainder[:idx]
    return remainder.strip() or None


def _collect_perplexity_sources(
    deep_results: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Extract unique source articles from deep analysis events' source_refs.

    Returns (articles_flat, prompt_bundle) in the same format as
    flatten_news_catalog so the LLM can cite them with [src:N] markers
    and the frontend can render SourceChip components.
    """
    seen_urls: set[str] = set()
    api_rows: list[dict[str, Any]] = []
    prompt_articles: list[dict[str, Any]] = []
    n = 0

    for kpi_result in deep_results:
        for event in kpi_result.get("events", []):
            for ref in event.get("source_refs", []):
                url = ref.get("url", "")
                title = ref.get("title", "")
                key = url if url else title
                if not key or key in seen_urls:
                    continue
                seen_urls.add(key)
                n += 1
                api_rows.append({
                    "index": n,
                    "id": f"perplexity-{n}",
                    "title": title,
                    "snippet": ref.get("snippet", ""),
                    "source": ref.get("source_domain", ""),
                    "date": ref.get("date", ""),
                    "url": url,
                })
                prompt_articles.append({
                    "n": n,
                    "id": f"perplexity-{n}",
                    "title": title,
                    "snippet": ref.get("snippet", ""),
                    "source": ref.get("source_domain", ""),
                    "date": ref.get("date", ""),
                    "url": url,
                })

    if not api_rows:
        return [], None

    return api_rows, {"articles": prompt_articles}


# ---------------------------------------------------------------------------
# Per-KPI investigation pipeline
# ---------------------------------------------------------------------------

def run_kpi_pipeline(
    kpi_id: str,
    country: str,
    kpi_results: list[dict[str, Any]],
    start_year: int,
    end_year: int,
) -> dict[str, Any] | None:
    """Run the full 7-step investigation pipeline for a single KPI.

    Returns a dict with kpi_id, kpi_name, questions, signals, events, insights,
    or None if no signals were detected.
    """
    from backend.services.analyst_questions import generate_analyst_questions
    from backend.services.events import extract_events
    from backend.services.hypotheses import generate_hypotheses
    from backend.services.research import search_for_evidence
    from backend.services.scoring import score_and_assemble_insights
    from backend.services.signals import extract_signals, filter_signals_with_questions

    spec = SPECS_BY_ID.get(kpi_id)
    kpi_name = spec.name if spec else f"KPI {kpi_id}"
    country_name = ISO3_TO_NAME.get(country, country)

    log.info("KPI pipeline started: %s (%s) for %s", kpi_id, kpi_name, country)

    try:
        # Step 1: Analyst questions
        questions = generate_analyst_questions(
            kpi_id=kpi_id,
            country=country,
            start_year=start_year,
            end_year=end_year,
        )

        # Step 2: Extract signals
        all_signals = extract_signals(kpi_results)
        if not all_signals:
            log.info("KPI %s: no signals detected — skipping", kpi_id)
            return None

        # Step 3: Filter signals, then cap at top N by magnitude
        filtered = filter_signals_with_questions(
            signals=all_signals,
            questions=questions,
            kpi_name=kpi_name,
            country=country_name,
        )
        capped = sorted(filtered, key=lambda s: abs(s.magnitude_pct), reverse=True)[
            :_MAX_SIGNALS_PER_KPI
        ]

        log.info(
            "KPI %s: %d raw → %d filtered → %d capped signals",
            kpi_id, len(all_signals), len(filtered), len(capped),
        )

        # Step 4: Generate hypotheses
        hypotheses = generate_hypotheses(
            signals=capped,
            questions=questions,
            kpi_name=kpi_name,
            country=country_name,
        )

        # Step 5: Perplexity research (parallel within this KPI)
        search_results = search_for_evidence(
            signal_hypotheses=hypotheses,
            country_iso3=country,
        )

        # Step 6: Event extraction
        events = extract_events(
            signals=capped,
            signal_hypotheses=hypotheses,
            search_results=search_results,
        )

        # Step 7: Score and assemble insights
        insights = score_and_assemble_insights(
            signals=capped,
            events=events,
            questions=questions,
        )

        log.info(
            "KPI %s pipeline complete: %d signals, %d events, %d insights",
            kpi_id, len(capped), len(events), len(insights),
        )

        return {
            "kpi_id": kpi_id,
            "kpi_name": kpi_name,
            "questions": [q.model_dump() for q in questions],
            "signals": [s.model_dump() for s in capped],
            "events": [e.model_dump() for e in events],
            "insights": [i.model_dump() for i in insights],
        }

    except Exception:
        log.exception("KPI pipeline failed for %s (%s)", kpi_id, kpi_name)
        return None


# ---------------------------------------------------------------------------
# Parallel deep analysis dispatcher
# ---------------------------------------------------------------------------

def _run_deep_analysis(
    valid_results: list[dict[str, Any]],
    notable_ids: list[str],
    country: str,
    start_year: int,
    end_year: int,
    progress_queue: queue.Queue[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Run per-KPI investigation pipelines in parallel.

    Returns a list of per-KPI result dicts (one per KPI that produced signals).
    If progress_queue is provided, puts progress events onto it as each KPI
    completes.
    """
    if not notable_ids:
        return []

    with ThreadPoolExecutor(max_workers=len(notable_ids)) as pool:
        futures = {
            pool.submit(
                run_kpi_pipeline,
                kpi_id=kid,
                country=country,
                kpi_results=[r for r in valid_results if str(r.get("kpi_id")) == kid],
                start_year=start_year,
                end_year=end_year,
            ): kid
            for kid in notable_ids
        }

        results: list[dict[str, Any]] = []
        for future in as_completed(futures):
            kid = futures[future]
            try:
                result = future.result()
            except Exception:
                log.exception("KPI pipeline future failed for %s", kid)
                result = None

            if result:
                results.append(result)
                if progress_queue is not None:
                    progress_queue.put({
                        "type": "deep_analysis_kpi_done",
                        "content": {
                            "kpi_id": result["kpi_id"],
                            "kpi_name": result["kpi_name"],
                            "signals": len(result["signals"]),
                            "events": len(result["events"]),
                            "insights": len(result["insights"]),
                        },
                    })

    return results


# ---------------------------------------------------------------------------
# Cross-KPI synthesis
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = """\
You are a senior macroeconomic analyst. You will receive investigation results from \
multiple KPIs for a single country. Each KPI has its own signals (data movements), \
events (real-world occurrences), and scored insights (signal-event connections with \
transmission channels and confidence scores).

Your task: identify CROSS-KPI CONNECTIONS and THEMATIC CLUSTERS.

For each cross-KPI connection, provide:
- "kpi_ids": list of KPI IDs involved
- "description": 1-2 sentences explaining how these KPIs interact
- "mechanism": the economic transmission channel linking them
- "confidence": 0.0-1.0

For thematic clusters, group KPIs into 2-4 macro themes and provide:
- "theme": short label (e.g. "Growth & Investment", "Price Stability & Employment")
- "kpi_ids": which KPIs belong to this theme
- "narrative": 2-3 sentences capturing the unified story across these KPIs

Also identify any COMMON EVENTS — real-world events that appear in multiple KPI \
pipelines (same event driving or affected by multiple indicators).

Respond with JSON:
{
  "cross_connections": [...],
  "themes": [...],
  "common_events": [
    {"event_headline": "...", "kpi_ids": [...], "role": "cause/effect"}
  ]
}

Return ONLY the JSON object."""


def _synthesize_cross_kpi(
    kpi_results: list[dict[str, Any]],
    country: str,
) -> dict[str, Any]:
    """Single LLM call to find cross-KPI connections and thematic clusters."""
    if len(kpi_results) < 2:
        return {"cross_connections": [], "themes": [], "common_events": []}

    country_name = ISO3_TO_NAME.get(country, country)

    summary_per_kpi = []
    for kr in kpi_results:
        summary_per_kpi.append({
            "kpi_id": kr["kpi_id"],
            "kpi_name": kr["kpi_name"],
            "signals": [
                {"description": s["description"], "magnitude_pct": s["magnitude_pct"],
                 "from_date": s["from_date"], "to_date": s["to_date"]}
                for s in kr.get("signals", [])
            ],
            "events": [
                {"headline": e["headline"], "summary": e["summary"],
                 "date_range": e["date_range"], "role": e["role"]}
                for e in kr.get("events", [])
            ],
            "insight_headlines": [
                i.get("headline", "") for i in kr.get("insights", [])
            ],
        })

    user_prompt = (
        f"Country: {country_name} ({country})\n\n"
        f"PER-KPI INVESTIGATION RESULTS ({len(kpi_results)} KPIs):\n"
        f"```json\n{json.dumps(summary_per_kpi, indent=2, default=str)}\n```\n\n"
        "Identify cross-KPI connections, thematic clusters, and common events. "
        "Return JSON object only."
    )

    client = _get_client()

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=2048,
            **_temperature_kw(OPENAI_MODEL),
        )

        raw_text = response.choices[0].message.content or ""
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)

        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            parsed = {"cross_connections": [], "themes": [], "common_events": []}

        log.info(
            "Cross-KPI synthesis: %d connections, %d themes, %d common events",
            len(parsed.get("cross_connections", [])),
            len(parsed.get("themes", [])),
            len(parsed.get("common_events", [])),
        )
        return parsed

    except Exception:
        log.exception("Cross-KPI synthesis failed")
        return {"cross_connections": [], "themes": [], "common_events": []}


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    req: CountryBriefGenerateRequest,
    *,
    deep_analysis: bool = False,
) -> Iterator[str]:
    """Generate a full country brief, yielding NDJSON lines.

    When deep_analysis=True, the pipeline runs a full hypothesis-driven
    investigation per notable KPI in parallel, synthesizes cross-KPI
    connections, and feeds all structured evidence into the brief prompt.
    """
    available_ids = [s.id for s in SPECS if s.source == "oxford"]
    timerange = f"{req.start_year}-{req.end_year}"
    freq = req.chart_frequency if req.chart_frequency in ("A", "Q") else "A"
    frequency_overrides = {str(kid): freq for kid in available_ids}

    # Phase 1: Fetch all KPI data
    yield _ndjson({"type": "status", "content": "Fetching KPI data..."})

    fetch_resp = fetch_kpi_data(
        countries=[req.country],
        kpi_ids=available_ids,
        timerange_q=timerange,
        timerange_a=timerange,
        frequency_overrides=frequency_overrides,
    )
    results_raw = [r.model_dump() for r in fetch_resp.results]

    yield _ndjson({"type": "kpi_data", "content": results_raw})

    valid_results = [r for r in results_raw if r.get("series")]

    # Phase 2: Derive facts & triage
    yield _ndjson({"type": "status", "content": "Analyzing data relevance..."})

    derived_facts = compute_derived_facts(valid_results)
    scores = triage_kpis(derived_facts)
    notable_ids = [s.kpi_id for s in scores if s.notable]

    yield _ndjson({
        "type": "triage",
        "content": [
            {"kpi_id": s.kpi_id, "kpi_name": s.kpi_name,
             "score": s.score, "notable": s.notable, "reasons": s.reasons}
            for s in scores
        ],
    })

    # Phase 2b (optional): Deep analysis — per-KPI parallel pipelines
    deep_results: list[dict[str, Any]] = []
    synthesis: dict[str, Any] = {}

    if deep_analysis and notable_ids:
        yield _ndjson({
            "type": "deep_analysis_start",
            "content": {"kpi_ids": notable_ids, "total": len(notable_ids)},
        })

        progress_q: queue.Queue[dict[str, Any]] = queue.Queue()

        # Run all KPI pipelines in parallel in a background thread so we can
        # yield progress events as they complete.
        with ThreadPoolExecutor(max_workers=1) as dispatcher:
            analysis_future = dispatcher.submit(
                _run_deep_analysis,
                valid_results,
                notable_ids,
                req.country,
                req.start_year,
                req.end_year,
                progress_q,
            )

            # Yield per-KPI progress events as they arrive
            finished = False
            while not finished:
                try:
                    event = progress_q.get(timeout=0.5)
                    yield _ndjson(event)
                except queue.Empty:
                    if analysis_future.done():
                        # Drain any remaining events
                        while not progress_q.empty():
                            yield _ndjson(progress_q.get_nowait())
                        finished = True

            deep_results = analysis_future.result()

        # Cross-KPI synthesis pass
        if len(deep_results) >= 2:
            yield _ndjson({"type": "status", "content": "Synthesizing cross-KPI connections..."})
            synthesis = _synthesize_cross_kpi(deep_results, req.country)
            yield _ndjson({"type": "deep_analysis_synthesis", "content": synthesis})
        elif deep_results:
            yield _ndjson({
                "type": "deep_analysis_synthesis",
                "content": {"cross_connections": [], "themes": [], "common_events": []},
            })

    # Phase 3: Collect source articles — from Perplexity (deep) or Newscatcher
    merged_news: dict[str, Any] = {}
    articles_flat: list[dict[str, Any]] = []
    prompt_bundle: dict[str, Any] | None = None

    if deep_results:
        log.info("Skipping Newscatcher — collecting Perplexity sources from deep analysis")
        articles_flat, prompt_bundle = _collect_perplexity_sources(deep_results)
        log.info("Collected %d Perplexity source articles for citations", len(articles_flat))
    else:
        yield _ndjson({"type": "status", "content": "Gathering news context..."})
        try:
            raw_articles = fetch_news_bulk(
                notable_ids, [req.country], derived_facts,
            )
            if raw_articles:
                merged_news = synthesize_news_context(
                    raw_articles, [req.country],
                    anchor_date=datetime.now().strftime("%Y-%m-%d"),
                    derived_facts=derived_facts,
                    kpi_ids=notable_ids,
                    max_per_country=COUNTRY_BRIEF_ARTICLES_PER_COUNTRY,
                )
        except Exception as exc:
            log.warning("Bulk news fetch failed: %s", exc)

        articles_flat, prompt_bundle = flatten_news_catalog(merged_news if merged_news else None)

    yield _ndjson({
        "type": "news_catalog",
        "content": {"articles": articles_flat},
    })

    # Phase 4: Build prompt and stream LLM response
    yield _ndjson({"type": "status", "content": "Generating brief..."})

    messages = build_brief_prompt(
        country=req.country,
        start_year=req.start_year,
        end_year=req.end_year,
        results=valid_results,
        derived_facts=derived_facts,
        notable_kpi_ids=notable_ids,
        news_context=merged_news if merged_news else None,
        news_prompt_bundle=prompt_bundle,
        focus=req.focus,
    )

    # Inject per-KPI deep analysis results + cross-KPI synthesis into the prompt
    if deep_results:
        per_kpi_json = json.dumps(deep_results, indent=2, default=str)
        synthesis_json = json.dumps(synthesis, indent=2, default=str) if synthesis else "{}"
        messages.append({
            "role": "user",
            "content": (
                "STRUCTURED INVESTIGATION RESULTS — Per-KPI deep analysis:\n"
                f"```json\n{per_kpi_json}\n```\n\n"
                "CROSS-KPI SYNTHESIS:\n"
                f"```json\n{synthesis_json}\n```\n\n"
                "Use these scored insights, signals, events, and cross-KPI themes "
                "to ground your narrative in specific causal evidence. "
                "Weave cross-KPI connections into a unified story rather than "
                "treating each KPI in isolation.\n\n"
                "IMPORTANT — Source citations: The NEWS_CONTEXT above contains "
                "articles from the Perplexity research phase. Use [src:N] markers "
                "(where N is the article's \"n\" value) at the END of any bullet or "
                "sentence grounded in a specific article. This is critical for "
                "traceability."
            ),
        })

    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=6000,
        stream=True,
        **_temperature_kw(model),
    )

    full_text = ""
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            full_text += delta.content
            yield _ndjson({"type": "text_delta", "content": delta.content})

    # Phase 5: Parse completed text into blocks; replace headline figures with
    # data-computed metrics so arrows match actual trends.
    blocks = parse_brief_blocks(full_text)
    computed_metrics = compute_ribbon_metrics(derived_facts)
    if computed_metrics:
        blocks = [b for b in blocks if b.get("type") != "metrics_ribbon"]
        blocks.insert(0, {"type": "metrics_ribbon", "metrics": computed_metrics})

    yield _ndjson({"type": "blocks", "content": blocks})

    yield _ndjson({"type": "done"})
