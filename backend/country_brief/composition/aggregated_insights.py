"""Country-brief aggregated insights composition over reusable stages."""
from __future__ import annotations

import logging
import math
import re
from typing import Any

from backend.insights_pipeline.stages import (
    evaluator,
    hypotheses_generator,
    insights_generator,
    news_researcher,
    search_planner,
    signal_event_linker,
    signal_extractor,
    signal_graph,
)
from backend.insights_pipeline.stages.common import REASONING_MODEL, get_kpi_context
from backend.models.kpi_registry import ISO3_TO_NAME

log = logging.getLogger(__name__)

_KPI_ID_RE = re.compile(r"\bKPI\s*([0-9]+)\b", re.IGNORECASE)
_AGGREGATION_SERIES_POLICY = "prefer_annual_then_native"


def _payload_has_series(payload: dict[str, Any]) -> bool:
    for key in ("series_annual", "series"):
        rows = payload.get(key)
        if isinstance(rows, list) and rows:
            return True
    return False


def _build_gdp_l2_addendum(
    selected_kpi_ids: list[str],
    kpi_results: dict[str, dict[str, Any]],
) -> str:
    selected = set(selected_kpi_ids)
    lines = [
        "GDP L2 guidance:",
        "- Use a top-down storyline: overall growth arc first, then key drivers, then implications.",
        "- Link each growth claim to a concrete driver present in the selected KPI payload.",
        "- Mention volatility only when swings are materially uneven; for smooth trends, emphasize persistence.",
    ]

    driver_lines: list[str] = []
    if "2" in selected:
        driver_lines.append("- If KPI 2 is present, decompose growth into oil and non-oil real-volume contributions.")
    if "11" in selected:
        driver_lines.append("- If KPI 11 is present, identify which sectors are gaining or losing share of nominal GDP. Caveat that this is a nominal series — share shifts can reflect price effects, not real output changes.")
    if "10" in selected and _payload_has_series(dict(kpi_results.get("10") or {})):
        driver_lines.append(
            "- If KPI 10 data is present, use expenditure decomposition (private consumption, fixed investment, exports, imports) to explain growth peaks/troughs."
        )
    if not driver_lines:
        driver_lines.append("- If decomposition KPIs are absent, keep GDP claims aggregate and avoid unsupported component attribution.")
    lines.extend(driver_lines)
    lines.append("- Keep real-vs-nominal discipline: do not treat price moves as evidence of real GDP volume changes.")
    return "\n".join(lines)


def _as_dict_list(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _as_text_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _truncate(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _kpi_scope_name(selected_kpi_ids: list[str], kpi_results: dict[str, dict[str, Any]]) -> str:
    names: list[str] = []
    for kid in selected_kpi_ids:
        kpi_name = str((kpi_results.get(kid) or {}).get("kpi_name") or f"KPI {kid}").strip()
        names.append(f"{kpi_name} (KPI {kid})")
    if not names:
        return "Selected macro KPI set"
    if len(names) <= 4:
        return ", ".join(names)
    return f"{', '.join(names[:4])}, +{len(names) - 4} more"


def _select_series_for_aggregation(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    annual_series = payload.get("series_annual")
    if isinstance(annual_series, list) and annual_series:
        return [dict(s) for s in annual_series if isinstance(s, dict)], "A"

    native_series = payload.get("series")
    if isinstance(native_series, list) and native_series:
        hinted = str(payload.get("frequency") or "").strip().upper() or "native"
        return [dict(s) for s in native_series if isinstance(s, dict)], hinted
    return [], "none"


def _bundle_kpi_payload(
    *,
    selected_kpi_ids: list[str],
    kpi_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    combined_series: list[dict[str, Any]] = []
    source_frequencies: dict[str, str] = {}
    bundle_errors: list[Any] = []

    for kid in selected_kpi_ids:
        payload = dict(kpi_results.get(kid) or {})
        series_rows, frequency = _select_series_for_aggregation(payload)
        source_frequencies[kid] = frequency

        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            bundle_errors.extend(errors)

        for series in series_rows:
            row = dict(series)
            indicator = str(row.get("indicator") or payload.get("kpi_name") or f"KPI {kid}").strip()
            row["indicator"] = f"{indicator} [KPI {kid}]"
            row["source_kpi_id"] = kid
            row["source_frequency"] = frequency
            combined_series.append(row)

    return {
        "kpi_id": "bundle",
        "kpi_name": "Country brief KPI bundle",
        "frequency": "mixed",
        "aggregation_policy": _AGGREGATION_SERIES_POLICY,
        "source_frequencies": source_frequencies,
        "series": combined_series,
        "errors": bundle_errors,
    }


def _extract_kpi_ids_from_signal(signal: dict[str, Any], selected_kpi_ids: list[str]) -> list[str]:
    source_kpi_id = str(signal.get("source_kpi_id") or "").strip()
    if source_kpi_id in selected_kpi_ids:
        return [source_kpi_id]

    joined = " ".join(
        [
            str(signal.get("kpi") or ""),
            str(signal.get("description") or ""),
            str(signal.get("period_summary") or ""),
        ]
    )
    found = [m.group(1) for m in _KPI_ID_RE.finditer(joined)]
    seen: set[str] = set()
    ordered: list[str] = []
    for kid in found:
        if kid in selected_kpi_ids and kid not in seen:
            seen.add(kid)
            ordered.append(kid)
    return ordered


def _build_bundle_kpi_context(
    selected_kpi_ids: list[str],
    kpi_results: dict[str, dict[str, Any]],
) -> str:
    sections: list[str] = []
    for kid in selected_kpi_ids:
        payload = dict(kpi_results.get(kid) or {})
        kpi_name = str(payload.get("kpi_name") or f"KPI {kid}").strip()
        unit = str(payload.get("unit") or "").strip()
        context_lines: list[str] = [f"KPI {kid}: {kpi_name}"]
        if unit:
            context_lines.append(f"Data unit: {unit}")
        per_kpi_context = get_kpi_context(kid)
        if per_kpi_context:
            context_lines.append(per_kpi_context)
        if kid == "3":
            context_lines.append(_build_gdp_l2_addendum(selected_kpi_ids, kpi_results))
        sections.append("\n".join(context_lines).strip())
    return "\n\n---\n\n".join(section for section in sections if section)


def _signal_impact_text(selected_signals: list[dict[str, Any]], start: int = 0) -> str:
    if not selected_signals:
        return "Material movement observed across selected KPIs."
    impacts: list[str] = []
    window = selected_signals[start : start + 2]
    if not window:
        window = selected_signals[:2]
    for signal in window:
        evidence = signal.get("evidence")
        if isinstance(evidence, dict):
            start_value = evidence.get("start_value")
            end_value = evidence.get("end_value")
            pct = evidence.get("overall_pct_change")
            kpi_name = str(signal.get("kpi") or "indicator").strip()
            if isinstance(start_value, (int, float)) and isinstance(end_value, (int, float)) and isinstance(pct, (int, float)):
                impacts.append(f"{kpi_name} moved from {start_value:.2f} to {end_value:.2f} ({pct:+.1f}%).")
                continue
        fallback = str(signal.get("period_summary") or signal.get("description") or "").strip()
        if fallback:
            impacts.append(_truncate(fallback, 180))
    return " ".join(impacts) if impacts else "Material movement observed across selected KPIs."


def _theme_nature(selected_signals: list[dict[str, Any]]) -> str:
    patterns = {str(sig.get("pattern", "")).lower().strip() for sig in selected_signals}
    return "cyclical" if patterns.intersection({"volatile", "reversing", "mixed"}) else "structural"


def _build_themes(
    *,
    selected_signals: list[dict[str, Any]],
    hypotheses: list[dict[str, Any]],
    final_insights: dict[str, Any],
    selected_kpi_ids: list[str],
) -> tuple[list[dict[str, Any]], list[list[str]]]:
    nature = _theme_nature(selected_signals)
    insights = _as_dict_list(final_insights.get("insights"))
    executive_summary = _as_text_list(final_insights.get("executive_summary"))
    signal_ids = [str(sig.get("id") or "").strip() for sig in selected_signals]
    signal_ids = [sid for sid in signal_ids if sid]
    signal_kpi_map = {
        str(sig.get("id") or "").strip(): _extract_kpi_ids_from_signal(sig, selected_kpi_ids)
        for sig in selected_signals
    }

    themes: list[dict[str, Any]] = []
    theme_kpis: list[list[str]] = []
    source_count = max(len(insights), len(hypotheses), len(executive_summary), 1)
    source_count = min(source_count, 4)

    for idx in range(source_count):
        insight = insights[idx] if idx < len(insights) else {}
        hypothesis = hypotheses[idx] if idx < len(hypotheses) else {}
        exec_point = executive_summary[idx] if idx < len(executive_summary) else ""

        title = str(insight.get("headline") or hypothesis.get("title") or "").strip()
        if not title:
            title = f"Macro theme {idx + 1}"

        thesis = str(insight.get("analysis") or hypothesis.get("causal_story") or exec_point).strip()
        if not thesis:
            thesis = _signal_impact_text(selected_signals, start=idx)

        trigger = str(hypothesis.get("title") or title).strip()
        mechanism = str(hypothesis.get("causal_story") or thesis).strip()
        impact = _signal_impact_text(selected_signals, start=idx)

        signal_window = signal_ids[idx * 2 : idx * 2 + 2]
        if not signal_window:
            signal_window = signal_ids[:2]
        if not signal_window:
            signal_window = [f"bundle_sig_{idx + 1}"]

        chain = {
            "trigger": _truncate(trigger, 160),
            "mechanism": _truncate(mechanism, 260),
            "kpi_impact": _truncate(impact, 220),
            "structural_or_cyclical": nature,
            "signal_ids": signal_window,
        }
        key_drivers = _as_text_list(hypothesis.get("potential_effects"))[:3]
        if not key_drivers:
            key_drivers = [_truncate(trigger, 80)]

        themes.append(
            {
                "title": _truncate(title, 120),
                "thesis": _truncate(thesis, 260),
                "nature": nature,
                "causal_chains": [chain],
                "key_drivers": key_drivers,
            }
        )

        kpis: list[str] = []
        for sid in signal_window:
            for kid in signal_kpi_map.get(sid, []):
                if kid not in kpis:
                    kpis.append(kid)
        if not kpis:
            kpis = selected_kpi_ids[:2]
        theme_kpis.append(kpis)

    return themes, theme_kpis


def _article_from_evidence(
    item: dict[str, Any],
    *,
    index: int,
    hypothesis_titles: dict[str, str] | None = None,
    related_theme_override: str = "",
) -> dict[str, Any]:
    summary = str(item.get("summary") or "").strip()
    title = str(item.get("title") or "").strip()
    if not title and summary:
        title = summary.split(".")[0].strip()
    if not title:
        title = f"Macro evidence {index}"
    if len(title) > 120:
        title = title[:117].rstrip() + "..."
    related_theme = related_theme_override
    if not related_theme and hypothesis_titles:
        hypothesis_id = str(item.get("hypothesis_id") or "").strip()
        related_theme = hypothesis_titles.get(hypothesis_id, "")
    article = {
        "index": index,
        "id": f"lab-{index}",
        "title": title,
        "snippet": summary,
        "source": str(item.get("source") or "").strip(),
        "date": str(item.get("date") or "").strip(),
        "url": str(item.get("url") or "").strip(),
    }
    event_type = str(item.get("event_type") or "").strip()
    actor = str(item.get("actor") or "").strip()
    action = str(item.get("action") or "").strip()
    if event_type:
        article["event_type"] = event_type
    if actor:
        article["actor"] = actor
    if action:
        article["action"] = action
    if related_theme:
        article["related_theme"] = related_theme
    return article


def _filter_top_signals_per_kpi(
    raw_signals: list[dict[str, Any]],
    selected_kpi_ids: list[str],
) -> list[dict[str, Any]]:
    """Group flat signals by ``kpi_id`` and keep the top max(2, ceil(N*0.2)) per KPI.

    The new flat-schema replacement for the old ``materiality_score`` ranker:
    signals are sorted by ``abs(pct_change)`` descending. Signals without
    ``pct_change`` fall to the bottom of their bucket with score 0.0.

    Edge cases:
    - When a KPI has only 1 signal, that 1 signal is kept.
    - Signals missing ``kpi_id`` are bucketed under an empty key and treated as
      their own group so they aren't silently dropped.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for sig in raw_signals:
        kid = str(sig.get("kpi_id") or sig.get("source_kpi_id") or "").strip()
        grouped.setdefault(kid, []).append(sig)

    ordered_keys = [k for k in selected_kpi_ids if k in grouped]
    ordered_keys.extend(k for k in grouped.keys() if k not in ordered_keys)

    def _rank_key(sig: dict[str, Any]) -> float:
        try:
            return abs(float(sig.get("pct_change") or 0.0))
        except (TypeError, ValueError):
            return 0.0

    selected: list[dict[str, Any]] = []
    for kid in ordered_keys:
        bucket = grouped.get(kid, [])
        if not bucket:
            continue
        n = len(bucket)
        if n < 2:
            keep_n = n
        else:
            keep_n = max(2, math.ceil(n * 0.2))
            keep_n = min(keep_n, n)
        bucket_sorted = sorted(bucket, key=_rank_key, reverse=True)
        selected.extend(bucket_sorted[:keep_n])
    return selected


_LEGACY_CONFIDENCE_MAP: dict[str, str] = {"high": "high", "medium": "medium", "low": "low"}


def _flatten_hypotheses_for_legacy(
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    """Flatten the grouped hypotheses document into the legacy hypothesis shape.

    Walks every ``hypothesis_groups[*].hypotheses[*]`` and emits the
    ``{id, title, causal_story, potential_effects, confidence}`` shape that
    the existing ``insights_generator.run_step`` and ``_build_themes`` expect.
    ``null_data_hypothesis`` rows are skipped -- they would muddy theme
    construction. This adapter is temporary scaffolding until downstream
    consumers learn the new document shape.
    """
    legacy: list[dict[str, Any]] = []
    if not isinstance(document, dict):
        return legacy
    for group in document.get("hypothesis_groups") or []:
        if not isinstance(group, dict):
            continue
        for hyp in group.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            if str(hyp.get("hypothesis_type") or "") == "null_data_hypothesis":
                continue
            title = str(hyp.get("hypothesis") or "").strip()
            if len(title) > 120:
                title = title[:117].rstrip() + "..."
            priority = str(hyp.get("search_priority") or "medium")
            legacy.append(
                {
                    "id": str(hyp.get("hypothesis_id") or ""),
                    "title": title or "Untitled hypothesis",
                    "causal_story": str(hyp.get("mechanism") or "").strip(),
                    "potential_effects": [
                        str(item).strip()
                        for item in (hyp.get("expected_evidence") or [])
                        if str(item).strip()
                    ],
                    "confidence": _LEGACY_CONFIDENCE_MAP.get(priority, "medium"),
                }
            )
    return legacy


def run_for_country(
    *,
    country: str,
    start_year: int,
    end_year: int,
    selected_kpi_ids: list[str],
    kpi_results: dict[str, dict[str, Any]],
    deep_analysis: bool,
    reasoning_model: str = REASONING_MODEL,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """Run aggregated insights composition for country brief generation."""
    payload = _bundle_kpi_payload(selected_kpi_ids=selected_kpi_ids, kpi_results=kpi_results)
    if not payload.get("series"):
        interpretation = {
            "period_highlight": f"{country} has limited data for the selected KPIs in {start_year}-{end_year}.",
            "themes": [],
            "noise_signals": [],
            "cross_kpi_connections": [],
            "composition_shifts": [],
        }
        return interpretation, [], None

    try:
        signal_output = signal_extractor.run_step(
            payload,
            reasoning_model=reasoning_model,
            use_llm_triage=False,
        )
    except Exception:
        log.exception("Aggregated signal extraction failed")
        signal_output = {"raw_signals": [], "selected_signals": []}
    raw_signals = _as_dict_list(signal_output.get("raw_signals"))
    selected_signals = _filter_top_signals_per_kpi(raw_signals, selected_kpi_ids)

    kpi_scope_name = _kpi_scope_name(selected_kpi_ids, kpi_results)
    country_name = ISO3_TO_NAME.get(str(country).upper().strip(), str(country))

    hypotheses: list[dict[str, Any]] = []
    hypothesis_document: dict[str, Any] = {}
    planned_queries: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    news_output: dict[str, Any] | None = None

    if deep_analysis and selected_signals:
        try:
            groups = signal_graph.build_groups(raw_signals)
            attached_groups = signal_graph.attach_signals(groups, raw_signals)
        except Exception:
            log.exception("Aggregated signal grouping failed")
            attached_groups = []

        if attached_groups:
            try:
                hyp_output = hypotheses_generator.run_step_groups(
                    country=country_name,
                    period=f"{start_year}-{end_year}",
                    archetype_tags=None,
                    attached_groups=attached_groups,
                    reasoning_model=reasoning_model,
                )
                hypothesis_document = dict(hyp_output.get("document") or {})
            except Exception:
                log.exception("Aggregated grouped hypotheses generation failed")
                hypothesis_document = {}

            hypotheses = _flatten_hypotheses_for_legacy(hypothesis_document)
            planned_queries = search_planner.plan_searches(
                hypothesis_document,
                budget=search_planner.DEFAULT_BUDGET,
            )

            if planned_queries:
                try:
                    news_output = news_researcher.run_planned_queries(
                        planned_queries=planned_queries,
                        country_name=country_name,
                        start_year=start_year,
                        end_year=end_year,
                    )
                    events = _as_dict_list(news_output.get("events"))
                except Exception:
                    log.exception("Aggregated planned-queries news research failed")
                    events = []

    try:
        link_output = signal_event_linker.link(selected_signals, events)
    except Exception:
        log.exception("Aggregated signal-event linking failed")
        link_output = {"links": [], "unlinked_signals": [], "unlinked_events": []}

    try:
        if deep_analysis:
            first_pass = insights_generator.run_step(
                country=country,
                kpi_name=kpi_scope_name,
                selected_signals=selected_signals,
                hypotheses=hypotheses,
                evidence_items=events,
                reasoning_model=reasoning_model,
            )
            eval_output = evaluator.run_step(
                country=country,
                kpi_name=kpi_scope_name,
                insight_payload=first_pass,
                reasoning_model=reasoning_model,
            )
            final_insights = insights_generator.run_step(
                country=country,
                kpi_name=kpi_scope_name,
                selected_signals=selected_signals,
                hypotheses=hypotheses,
                evidence_items=events,
                evaluator_feedback=_as_text_list(eval_output.get("revision_instructions")),
                reasoning_model=reasoning_model,
            )
        else:
            final_insights = insights_generator.run_step(
                country=country,
                kpi_name=kpi_scope_name,
                selected_signals=selected_signals,
                hypotheses=hypotheses,
                evidence_items=[],
                generation_mode="light",
                reasoning_model=reasoning_model,
            )
    except Exception:
        log.exception("Aggregated insights generation failed")
        final_insights = {}

    themes, theme_kpis = _build_themes(
        selected_signals=selected_signals,
        hypotheses=hypotheses,
        final_insights=final_insights,
        selected_kpi_ids=selected_kpi_ids,
    )
    articles_flat: list[dict[str, Any]] = []
    prompt_articles: list[dict[str, Any]] = []
    for idx, event in enumerate(events, start=1):
        article = _article_from_evidence(event, index=idx)
        articles_flat.append(article)
        prompt_articles.append({"n": idx, **article})

    selected_signal_ids = {str(sig.get("id") or "").strip() for sig in selected_signals}
    noise_signals: list[str] = []
    for signal in raw_signals:
        sid = str(signal.get("id") or "").strip()
        if sid and sid not in selected_signal_ids:
            noise_signals.append(sid)

    cross_kpi_connections: list[dict[str, Any]] = []
    for idx in range(min(3, max(0, len(theme_kpis) - 1))):
        left = theme_kpis[idx]
        right = theme_kpis[idx + 1]
        pair = [kid for kid in [*left, *right] if kid in selected_kpi_ids]
        deduped: list[str] = []
        for kid in pair:
            if kid not in deduped:
                deduped.append(kid)
        if len(deduped) < 2:
            continue
        cross_kpi_connections.append(
            {
                "description": (
                    f"KPI {deduped[0]} and KPI {deduped[1]} move through linked macro channels in {country}."
                ),
                "kpi_ids": deduped[:3],
            }
        )

    exec_summary = _as_text_list(final_insights.get("executive_summary"))
    insight_rows = _as_dict_list(final_insights.get("insights"))
    period_highlight = (
        (exec_summary[0] if exec_summary else "")
        or (str(insight_rows[0].get("analysis") or "").strip() if insight_rows else "")
        or (str(hypotheses[0].get("causal_story") or "").strip() if hypotheses else "")
        or f"{country} shows material shifts across selected KPIs in {start_year}-{end_year}."
    )

    interpretation = {
        "period_highlight": _truncate(period_highlight, 240),
        "themes": themes[:4],
        "noise_signals": noise_signals[:24],
        "cross_kpi_connections": cross_kpi_connections,
        "composition_shifts": [],
        "signal_event_links": link_output.get("links", []),
        "unlinked_signals": link_output.get("unlinked_signals", []),
        "unlinked_events": link_output.get("unlinked_events", []),
        "planned_queries": planned_queries,
        "news_by_query": (news_output or {}).get("by_query", []) if news_output else [],
        "hypothesis_document": hypothesis_document,
    }
    prompt_bundle = {"articles": prompt_articles} if prompt_articles else None
    return interpretation, articles_flat, prompt_bundle

