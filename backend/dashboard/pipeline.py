"""Dashboard insight orchestration built on insights-pipeline stages."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from backend.insights_pipeline.stages import (
    evaluator,
    hypotheses_generator,
    insights_generator,
    news_researcher,
    signal_extractor,
)
from backend.insights_pipeline.stages.common import REASONING_MODEL

log = logging.getLogger(__name__)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _norm_text(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _extract_year(value: Any) -> int | None:
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1900 <= year <= 2100:
            return year
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).year
    except Exception:  # noqa: BLE001
        return None


def _infer_window(kpi_payload: dict[str, Any]) -> tuple[int, int]:
    years: list[int] = []
    for series in kpi_payload.get("series", []):
        if not isinstance(series, dict):
            continue
        for point in series.get("points", []):
            if not isinstance(point, dict) or point.get("value") is None:
                continue
            year = _extract_year(point.get("date"))
            if year is not None:
                years.append(year)
    if not years:
        current_year = datetime.now().year
        return current_year - 10, current_year
    return min(years), max(years)


def _filter_payload_to_countries(
    kpi_payload: dict[str, Any],
    countries: list[str],
) -> dict[str, Any]:
    allow = {country.upper().strip() for country in countries if country}
    series = []
    for row in kpi_payload.get("series", []):
        if not isinstance(row, dict):
            continue
        country = str(row.get("country") or "").upper().strip()
        if country in allow:
            series.append(dict(row))
    return {
        **kpi_payload,
        "series": series,
    }


def _stage_chain_for_payload(
    *,
    country_label: str,
    kpi_payload: dict[str, Any],
    reasoning_model: str,
) -> dict[str, Any]:
    kpi_id = str(kpi_payload.get("kpi_id") or "")
    kpi_name = str(kpi_payload.get("kpi_name") or f"KPI {kpi_id}" or "KPI")
    start_year, end_year = _infer_window(kpi_payload)

    signal_output = signal_extractor.run_step(
        kpi_payload,
        reasoning_model=reasoning_model,
    )
    selected_signals = _dict_list(signal_output.get("selected_signals"))
    hypotheses_output = hypotheses_generator.run_step(
        country=country_label,
        kpi_id=kpi_id,
        kpi_name=kpi_name,
        start_year=start_year,
        end_year=end_year,
        selected_signals=selected_signals,
        reasoning_model=reasoning_model,
    )
    hypotheses = _dict_list(hypotheses_output.get("hypotheses"))

    news_output: dict[str, Any]
    try:
        news_output = news_researcher.run_step_bulk(
            country=country_label,
            kpi_name=kpi_name,
            start_year=start_year,
            end_year=end_year,
            hypotheses=hypotheses,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Dashboard news_researcher failed: %s", exc)
        news_output = {
            "evidence_items": [],
            "research_notes": "News research unavailable for this request.",
            "call_meta": None,
        }
    evidence_items = _dict_list(news_output.get("evidence_items"))

    first_pass = insights_generator.run_step(
        country=country_label,
        kpi_name=kpi_name,
        selected_signals=selected_signals,
        hypotheses=hypotheses,
        evidence_items=evidence_items,
        reasoning_model=reasoning_model,
    )

    evaluator_output: dict[str, Any]
    try:
        evaluator_output = evaluator.run_step(
            country=country_label,
            kpi_name=kpi_name,
            insight_payload=first_pass,
            reasoning_model=reasoning_model,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Dashboard evaluator failed: %s", exc)
        evaluator_output = {"revision_instructions": []}

    final_insights = insights_generator.run_step(
        country=country_label,
        kpi_name=kpi_name,
        selected_signals=selected_signals,
        hypotheses=hypotheses,
        evidence_items=evidence_items,
        evaluator_feedback=evaluator_output.get("revision_instructions", []),
        reasoning_model=reasoning_model,
    )
    return {
        "kpi_id": kpi_id,
        "kpi_name": kpi_name,
        "start_year": start_year,
        "end_year": end_year,
        "signal_output": signal_output,
        "hypotheses_output": hypotheses_output,
        "news_output": news_output,
        "final_insights": final_insights,
    }


def _build_news_catalog(
    evidence_items: list[dict[str, Any]],
    hypothesis_titles: dict[str, str],
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for idx, item in enumerate(evidence_items[:12], start=1):
        hypothesis_id = _norm_text(item.get("hypothesis_id"))
        title_prefix = _norm_text(hypothesis_titles.get(hypothesis_id))
        stance = _norm_text(item.get("stance"))
        title_parts = [part for part in [title_prefix, stance.capitalize()] if part]
        title = " - ".join(title_parts) if title_parts else f"Evidence {idx}"
        catalog.append(
            {
                "index": idx,
                "id": _norm_text(item.get("id")) or f"ev_{idx}",
                "title": title,
                "snippet": _norm_text(item.get("summary") or item.get("title")),
                "source": _norm_text(item.get("source")),
                "date": _norm_text(item.get("date")),
                "url": _norm_text(item.get("url")),
                "hypothesis_id": hypothesis_id,
            }
        )
    return catalog


def _compose_summary_line(insights: list[dict[str, Any]], fallback: str) -> str:
    if not insights:
        return fallback
    headline = _norm_text(insights[0].get("headline"))
    analysis = _norm_text(insights[0].get("analysis"))
    if headline and analysis:
        return f"{headline}: {analysis}"
    return headline or analysis or fallback


def _compose_country_markdown(
    *,
    country: str,
    kpi_name: str,
    final_insights: dict[str, Any],
    signal_output: dict[str, Any],
    news_count: int,
) -> str:
    insights = _dict_list(final_insights.get("insights"))
    predictions = final_insights.get("predictions", [])
    selected_signals = _dict_list(signal_output.get("selected_signals"))

    summary = _compose_summary_line(
        insights,
        fallback=f"{country}: evidence-backed insight generation returned limited structured output for {kpi_name}.",
    )

    findings: list[str] = []
    for idx, insight in enumerate(insights[:3], start=1):
        headline = _norm_text(insight.get("headline"))
        analysis = _norm_text(insight.get("analysis"))
        line = f"**{headline}**: {analysis}" if headline else analysis
        if line:
            marker = f" [src:{idx}]" if idx <= news_count else ""
            findings.append(f"{line}{marker}")
    if not findings:
        for signal in selected_signals[:3]:
            pattern = _norm_text(signal.get("pattern")) or "material"
            summary_line = _norm_text(signal.get("period_summary") or signal.get("description"))
            if summary_line:
                findings.append(f"**{pattern.capitalize()} pattern**: {summary_line}")

    implications: list[str] = []
    if isinstance(predictions, list):
        for idx, item in enumerate(predictions[:3], start=1):
            if isinstance(item, dict):
                headline = _norm_text(item.get("headline"))
                rationale = _norm_text(item.get("rationale") or item.get("analysis"))
                text = f"**{headline}**: {rationale}" if headline else rationale
            else:
                text = _norm_text(item)
            if not text:
                continue
            marker_idx = min(news_count, idx + 3)
            marker = f" [src:{marker_idx}]" if marker_idx > 0 else ""
            implications.append(f"{text}{marker}")
    if not implications:
        implications.append(
            "Evidence coverage is limited; validate directional inferences with the latest policy and market updates."
        )

    findings_block = "\n".join(f"- {line}" for line in findings[:3]) or "- No notable findings generated."
    implications_block = "\n".join(f"- {line}" for line in implications[:3])
    return (
        "## Summary\n"
        f"{summary}\n\n"
        "## Key Findings\n"
        f"{findings_block}\n\n"
        "## Implications\n"
        f"{implications_block}\n"
    )


def _compose_cross_markdown(
    *,
    countries: list[str],
    kpi_name: str,
    final_insights: dict[str, Any],
    signal_output: dict[str, Any],
    news_count: int,
) -> str:
    insights = _dict_list(final_insights.get("insights"))
    predictions = final_insights.get("predictions", [])
    selected_signals = _dict_list(signal_output.get("selected_signals"))
    country_label = ", ".join(countries)
    summary = _compose_summary_line(
        insights,
        fallback=f"Cross-country view ({country_label}) identified mixed signals for {kpi_name}.",
    )

    findings: list[str] = []
    for idx, signal in enumerate(selected_signals[:3], start=1):
        signal_country = _norm_text(signal.get("country")) or "Series"
        pattern = _norm_text(signal.get("pattern")) or "mixed"
        period_summary = _norm_text(signal.get("period_summary") or signal.get("description"))
        if period_summary:
            findings.append(
                f"**{signal_country} ({pattern})**: {period_summary}"
                + (f" [src:{idx}]" if idx <= news_count else "")
            )
    if not findings:
        for idx, insight in enumerate(insights[:3], start=1):
            headline = _norm_text(insight.get("headline"))
            analysis = _norm_text(insight.get("analysis"))
            text = f"**{headline}**: {analysis}" if headline else analysis
            if text:
                findings.append(text + (f" [src:{idx}]" if idx <= news_count else ""))

    implications: list[str] = []
    if isinstance(predictions, list):
        for idx, item in enumerate(predictions[:3], start=1):
            text = _norm_text(item if not isinstance(item, dict) else item.get("headline") or item.get("rationale"))
            if text:
                marker_idx = min(news_count, idx + 3)
                marker = f" [src:{marker_idx}]" if marker_idx > 0 else ""
                implications.append(f"{text}{marker}")
    if not implications:
        implications.append(
            "Cross-country divergence should be interpreted alongside fiscal policy stance, external exposure, and data revisions."
        )

    findings_block = "\n".join(f"- {line}" for line in findings[:3]) or "- No notable findings generated."
    implications_block = "\n".join(f"- {line}" for line in implications[:3])
    return (
        "## Summary\n"
        f"{summary}\n\n"
        "## Key Findings\n"
        f"{findings_block}\n\n"
        "## Implications\n"
        f"{implications_block}\n"
    )


def generate_country_insight(
    *,
    country: str,
    kpi_result: dict[str, Any],
    reasoning_model: str | None = None,
) -> dict[str, Any]:
    """Generate one-country dashboard insight payload from stage outputs."""
    selected_country = country.upper().strip()
    payload = _filter_payload_to_countries(kpi_result, [selected_country])
    model = (reasoning_model or REASONING_MODEL).strip() or REASONING_MODEL
    stage_output = _stage_chain_for_payload(
        country_label=selected_country,
        kpi_payload=payload,
        reasoning_model=model,
    )
    hypotheses = _dict_list(stage_output["hypotheses_output"].get("hypotheses"))
    hypothesis_titles = {
        _norm_text(item.get("id")): _norm_text(item.get("title"))
        for item in hypotheses
        if _norm_text(item.get("id"))
    }
    news_catalog = _build_news_catalog(
        _dict_list(stage_output["news_output"].get("evidence_items")),
        hypothesis_titles,
    )
    text = _compose_country_markdown(
        country=selected_country,
        kpi_name=stage_output["kpi_name"],
        final_insights=stage_output["final_insights"],
        signal_output=stage_output["signal_output"],
        news_count=len(news_catalog),
    )
    return {
        "text": text,
        "newsCatalog": news_catalog,
    }


def generate_cross_country_insight(
    *,
    countries: list[str],
    kpi_result: dict[str, Any],
    reasoning_model: str | None = None,
) -> dict[str, Any]:
    """Generate cross-country dashboard insight payload from stage outputs."""
    normalized = []
    seen: set[str] = set()
    for country in countries:
        code = str(country).upper().strip()
        if len(code) == 3 and code not in seen:
            seen.add(code)
            normalized.append(code)
    payload = _filter_payload_to_countries(kpi_result, normalized)
    model = (reasoning_model or REASONING_MODEL).strip() or REASONING_MODEL
    stage_output = _stage_chain_for_payload(
        country_label=", ".join(normalized),
        kpi_payload=payload,
        reasoning_model=model,
    )
    hypotheses = _dict_list(stage_output["hypotheses_output"].get("hypotheses"))
    hypothesis_titles = {
        _norm_text(item.get("id")): _norm_text(item.get("title"))
        for item in hypotheses
        if _norm_text(item.get("id"))
    }
    news_catalog = _build_news_catalog(
        _dict_list(stage_output["news_output"].get("evidence_items")),
        hypothesis_titles,
    )
    text = _compose_cross_markdown(
        countries=normalized,
        kpi_name=stage_output["kpi_name"],
        final_insights=stage_output["final_insights"],
        signal_output=stage_output["signal_output"],
        news_count=len(news_catalog),
    )
    return {
        "text": text,
        "newsCatalog": news_catalog,
    }

