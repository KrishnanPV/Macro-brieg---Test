"""Perplexity Sonar research via OpenAI-compatible chat completions."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from backend.config import PERPLEXITY_API_KEY, PERPLEXITY_URL, PERPLEXITY_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.kpi_registry import ISO3_TO_NAME

log = logging.getLogger(__name__)

_RESEARCH_SYSTEM = """\
You are a macroeconomic research assistant finding EVIDENCE for specific hypothesized \
drivers of economic data movements. You are NOT writing a general country overview — you \
are searching for specific events, decisions, and policies that CAUSED observed data changes.

Search the web thoroughly and return a structured JSON array of findings. Each finding \
should be a distinct, specific event — not a general economic summary or outlook piece.

QUALITY BAR for each finding:
- Must describe a SPECIFIC event with a date (policy announcement, rate decision, \
production quota change, reform law, institutional report, investment commitment)
- Snippet must include at least one concrete fact (a number, a named actor, a specific \
date, a quoted projection)
- Generic macro summaries ("the economy grew steadily") are NOT acceptable findings

PRIORITY ORDER for sources:
1. Primary sources: central bank statements, ministry announcements, OPEC communiques, \
IMF/World Bank reports, official statistics bureaus
2. Authoritative analysis: Reuters, Bloomberg, Financial Times, The Economist, Oxford \
Economics publications
3. Regional specialist outlets with domain expertise
4. General business media (lowest priority)

For each finding, provide:
- "title": short headline (max 15 words)
- "snippet": 2-4 sentences with key facts, figures, and named actors
- "date": specific date or quarter (e.g. "2023-06", "Q4 2022"). REQUIRED — do not \
return undated findings
- "url": source URL if available, otherwise ""
- "source_domain": the publication or source name
- "related_theme": which analytical theme this finding most closely supports (from the \
list provided, or "" if none)

Return between 12 and 25 findings, prioritizing the most significant and well-sourced ones. \
Prioritize findings from within 2 years of the detected signal dates.

Respond with ONLY a JSON array of finding objects, no other text."""


def _get_client() -> OpenAI:
    if not PERPLEXITY_API_KEY or PERPLEXITY_API_KEY == "your_perplexity_api_key_here":
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not configured. "
            "Set it in .env to use the insights pipeline."
        )
    return OpenAI(api_key=PERPLEXITY_API_KEY, base_url=PERPLEXITY_URL)


def research_country_overview(
    country_iso3: str,
    kpi_signals: dict[str, list[str]],
    start_year: int,
    end_year: int,
    *,
    search_targets: list[str] | None = None,
    theme_titles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Single Perplexity Sonar call for a consolidated country macro overview.

    Used by the country_brief 3-agent pipeline (Agent 2) to find news/events
    that explain detected signals across all KPIs in one call.

    Args:
        country_iso3: ISO-3166 alpha-3 country code.
        kpi_signals: Mapping of KPI name -> list of signal description strings.
        start_year: Start of the analysis window.
        end_year: End of the analysis window.
        search_targets: Focused hypotheses from Agent 1 (triggers and mechanisms).
        theme_titles: Analytical theme names from Agent 1 for article mapping.

    Returns:
        List of finding dicts with keys: title, snippet, date, url, source_domain,
        and optionally related_theme.
    """
    if not kpi_signals:
        return []

    country_name = ISO3_TO_NAME.get(country_iso3, country_iso3)

    # Build the search query — focused if we have Agent 1's output, generic otherwise
    if search_targets:
        targets_block = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(search_targets[:15]))
        signal_lines: list[str] = []
        for kpi, descs in list(kpi_signals.items())[:12]:
            for desc in descs[:3]:
                signal_lines.append(f"- {kpi}: {desc}")
        signals_summary = "\n".join(signal_lines)
        user_prompt = (
            f"Country: {country_name} ({country_iso3})\n"
            f"Time period: {start_year}–{end_year}\n\n"
            f"An analysis agent has identified these as the most likely drivers of "
            f"recent macroeconomic data movements. Find EVIDENCE for each:\n\n"
            f"{targets_block}\n\n"
            f"Data movements being explained:\n{signals_summary}\n\n"
            f"Search for specific events, policy decisions, institutional reports, and "
            f"announcements from {start_year} to {end_year} that confirm or refute "
            f"these hypothesized drivers for {country_name}."
        )
    else:
        signal_lines: list[str] = []
        for kpi_name, descriptions in kpi_signals.items():
            for desc in descriptions:
                signal_lines.append(f"- {kpi_name}: {desc}")
        signals_block = "\n".join(signal_lines)
        user_prompt = (
            f"Country: {country_name} ({country_iso3})\n"
            f"Time period: {start_year}–{end_year}\n\n"
            f"The following macroeconomic data movements have been detected:\n"
            f"{signals_block}\n\n"
            f"Find news articles, policy announcements, economic reports, and events "
            f"from {start_year} to {end_year} that explain or are connected to these "
            f"data movements for {country_name}."
        )

    if theme_titles:
        themes_list = ", ".join(f'"{t}"' for t in theme_titles)
        user_prompt += (
            f"\n\nFor the \"related_theme\" field, map each finding to the most relevant "
            f"theme from: [{themes_list}]. Use \"\" if none apply."
        )

    user_prompt += "\n\nReturn JSON array of findings."

    total_signals = sum(len(descs) for descs in kpi_signals.values())
    log.info(
        "Perplexity country overview for %s (%d KPIs, %d signals, targeted=%s)",
        country_iso3, len(kpi_signals), total_signals, bool(search_targets),
    )

    client = _get_client()

    try:
        response = client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=[
                {"role": "system", "content": _RESEARCH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        record_usage(PERPLEXITY_MODEL, response.usage, caller="research.research_country_overview")

        raw_text = response.choices[0].message.content or ""
        findings = _parse_findings(raw_text)

        log.info(
            "Perplexity country overview returned %d findings for %s",
            len(findings), country_iso3,
        )
        return findings

    except Exception:
        log.exception("Perplexity country overview failed for %s", country_iso3)
        return []


def _parse_findings(raw_text: str) -> list[dict[str, Any]]:
    """Parse the Sonar response into a list of finding dicts."""
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning(
            "Could not parse Sonar JSON, wrapping raw text as single finding: %s",
            text[:200],
        )
        return [{
            "title": "Research summary",
            "snippet": text[:1000],
            "date": "",
            "url": "",
            "source_domain": "perplexity.ai",
        }]

    if not isinstance(parsed, list):
        parsed = [parsed]

    findings: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        finding: dict[str, Any] = {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "date": item.get("date", ""),
            "source_domain": item.get("source_domain", ""),
        }
        related = item.get("related_theme", "")
        if related:
            finding["related_theme"] = related
        findings.append(finding)

    return findings
