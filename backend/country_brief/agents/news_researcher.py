"""Agent 2 — News Researcher.

Single Perplexity Sonar call to find real-world news/events that
explain the detected signals.  Only invoked when deep_analysis=True.

When signal interpretation is available (from Agent 1), the search is
targeted around specific hypothesized drivers and causal chains rather
than a generic list of signal descriptions.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.services.research import research_country_overview

log = logging.getLogger(__name__)


def _extract_search_targets(interpretation: dict[str, Any]) -> list[str]:
    """Extract focused search targets from Agent 1's thematic interpretation.

    Pulls theme titles, triggers and mechanisms from causal_chains, plus
    key_drivers, to give Perplexity specific hypotheses to find evidence for.
    """
    targets: list[str] = []
    for theme in interpretation.get("themes", []):
        title = theme.get("title", "").strip()
        if title:
            targets.append(title)
        for chain in theme.get("causal_chains", []):
            trigger = chain.get("trigger", "").strip()
            if trigger:
                targets.append(trigger)
            mechanism = chain.get("mechanism", "").strip()
            if mechanism:
                targets.append(mechanism)
        for driver in theme.get("key_drivers", []):
            d = str(driver).strip()
            if d and d not in targets:
                targets.append(d)
    return targets


def research_signals(
    signals_data: list[dict[str, Any]],
    country: str,
    start_year: int,
    end_year: int,
    *,
    signal_interpretation: dict[str, Any] | None = None,
    all_kpi_signals: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Single Perplexity call to find news that explains the signals.

    When signal_interpretation is provided, the search focuses on the
    specific drivers and causal chains identified by Agent 1. Otherwise
    falls back to grouping signal descriptions by KPI name.

    Args:
        all_kpi_signals: Full KPI->descriptions mapping from *all* signals
            (pre-filter). Gives Perplexity broader topic awareness than the
            filtered signals_data alone.

    Returns (articles_flat, prompt_bundle) for the brief writer.
    """
    search_targets: list[str] = []
    if signal_interpretation:
        search_targets = _extract_search_targets(signal_interpretation)

    kpi_signals: dict[str, list[str]] = {}
    if all_kpi_signals:
        kpi_signals = all_kpi_signals
    else:
        for sig in signals_data:
            kpi_signals.setdefault(sig.get("kpi_name", "Unknown"), []).append(
                sig.get("description", "")
            )

    if not kpi_signals:
        return [], None

    theme_titles: list[str] = []
    if signal_interpretation:
        theme_titles = [
            t.get("title", "") for t in signal_interpretation.get("themes", [])
            if t.get("title")
        ]

    findings = research_country_overview(
        country_iso3=country,
        kpi_signals=kpi_signals,
        start_year=start_year,
        end_year=end_year,
        search_targets=search_targets or None,
        theme_titles=theme_titles or None,
    )

    if not findings:
        return [], None

    articles_flat = []
    prompt_articles = []
    for i, f in enumerate(findings, 1):
        row: dict[str, Any] = {
            "index": i,
            "id": f"perplexity-{i}",
            "title": f.get("title", ""),
            "snippet": f.get("snippet", ""),
            "source": f.get("source_domain", ""),
            "date": f.get("date", ""),
            "url": f.get("url", ""),
        }
        related = f.get("related_theme", "")
        if related:
            row["related_theme"] = related
        articles_flat.append(row)
        prompt_articles.append({"n": i, **row})

    return articles_flat, {"articles": prompt_articles}
