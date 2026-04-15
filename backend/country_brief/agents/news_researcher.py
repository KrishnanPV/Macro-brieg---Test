"""Agent 2 — News Researcher.

Single Perplexity Sonar call to find real-world news/events that
explain the detected signals.  Only invoked when deep_analysis=True.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.services.research import research_country_overview

log = logging.getLogger(__name__)


def research_signals(
    signals_data: list[dict[str, Any]],
    country: str,
    start_year: int,
    end_year: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Single Perplexity call to find news that explains the signals.

    Returns (articles_flat, prompt_bundle) for the brief writer.
    """
    kpi_signals: dict[str, list[str]] = {}
    for sig in signals_data:
        kpi_signals.setdefault(sig.get("kpi_name", "Unknown"), []).append(
            sig.get("description", "")
        )

    if not kpi_signals:
        return [], None

    findings = research_country_overview(
        country_iso3=country,
        kpi_signals=kpi_signals,
        start_year=start_year,
        end_year=end_year,
    )

    if not findings:
        return [], None

    articles_flat = []
    prompt_articles = []
    for i, f in enumerate(findings, 1):
        row = {
            "index": i,
            "id": f"perplexity-{i}",
            "title": f.get("title", ""),
            "snippet": f.get("snippet", ""),
            "source": f.get("source_domain", ""),
            "date": f.get("date", ""),
            "url": f.get("url", ""),
        }
        articles_flat.append(row)
        prompt_articles.append({"n": i, **row})

    return articles_flat, {"articles": prompt_articles}
