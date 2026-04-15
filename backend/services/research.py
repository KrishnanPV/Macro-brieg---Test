"""Perplexity Sonar research via OpenAI-compatible chat completions."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from openai import OpenAI

from backend.config import PERPLEXITY_API_KEY, PERPLEXITY_URL, PERPLEXITY_MODEL
from backend.services.cost_tracker import record_usage
from backend.models.insights import SignalHypotheses
from backend.models.kpi_registry import ISO3_TO_NAME

log = logging.getLogger(__name__)

_RESEARCH_SYSTEM = """\
You are a macroeconomic research assistant. You will receive a search query about \
economic events, policies, and data movements for a specific country and time period.

Search the web thoroughly and return a structured JSON array of findings. Each finding \
should be a distinct event, policy, report, or development you found. For each, provide:
- "title": short headline of the finding
- "snippet": 2-4 sentence summary with key facts and figures
- "date": approximate date or date range (e.g. "2023-03", "Q4 2022", "2021")
- "url": source URL if available, otherwise ""
- "source_domain": the publication or source name

Return between 8 and 20 findings, prioritizing the most significant and well-sourced ones.

Respond with ONLY a JSON array of finding objects, no other text."""


def _get_client() -> OpenAI:
    if not PERPLEXITY_API_KEY or PERPLEXITY_API_KEY == "your_perplexity_api_key_here":
        raise RuntimeError(
            "PERPLEXITY_API_KEY is not configured. "
            "Set it in .env to use the insights pipeline."
        )
    return OpenAI(api_key=PERPLEXITY_API_KEY, base_url=PERPLEXITY_URL)


def _search_single(
    client: OpenAI,
    sh: SignalHypotheses,
    country_name: str,
) -> list[dict[str, Any]]:
    """Execute a single Perplexity Sonar call for one signal's consolidated query."""
    query = sh.consolidated_search_query.strip()
    if not query:
        return []

    user_prompt = (
        f"Country focus: {country_name}\n\n"
        f"Research query:\n{query}\n\n"
        f"Find relevant news articles, policy announcements, economic reports, "
        f"and events. Return JSON array of findings."
    )

    log.info(
        "Perplexity Sonar query for signal %s: %s",
        sh.signal_id, query[:120],
    )

    try:
        response = client.chat.completions.create(
            model=PERPLEXITY_MODEL,
            messages=[
                {"role": "system", "content": _RESEARCH_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
        )
        record_usage(PERPLEXITY_MODEL, response.usage, caller="research.search_for_evidence")

        raw_text = response.choices[0].message.content or ""
        findings = _parse_findings(raw_text)

        log.info(
            "Sonar returned %d findings for signal %s",
            len(findings), sh.signal_id,
        )
        return findings

    except Exception:
        log.exception(
            "Perplexity Sonar failed for signal %s", sh.signal_id
        )
        return []


def search_for_evidence(
    signal_hypotheses: list[SignalHypotheses],
    country_iso3: str,
) -> dict[str, list[dict[str, Any]]]:
    """Execute Perplexity Sonar calls in parallel using consolidated queries.

    One call per signal, all dispatched concurrently. Returns a dict keyed by
    signal_id -> list of finding dicts.
    """
    if not signal_hypotheses:
        return {}

    country_name = ISO3_TO_NAME.get(country_iso3, country_iso3)
    client = _get_client()
    results: dict[str, list[dict[str, Any]]] = {}

    searchable = [sh for sh in signal_hypotheses if sh.consolidated_search_query.strip()]
    empty = [sh for sh in signal_hypotheses if not sh.consolidated_search_query.strip()]
    for sh in empty:
        results[sh.signal_id] = []

    if not searchable:
        return results

    with ThreadPoolExecutor(max_workers=len(searchable)) as pool:
        futures = {
            pool.submit(_search_single, client, sh, country_name): sh.signal_id
            for sh in searchable
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results[sid] = future.result()
            except Exception:
                log.exception("Perplexity future failed for signal %s", sid)
                results[sid] = []

    total = sum(len(v) for v in results.values())
    log.info(
        "Perplexity returned %d total findings across %d signals",
        total, len(results),
    )
    return results


def research_country_overview(
    country_iso3: str,
    kpi_signals: dict[str, list[str]],
    start_year: int,
    end_year: int,
) -> list[dict[str, Any]]:
    """Single Perplexity Sonar call for a consolidated country macro overview.

    Used by the country_brief 3-agent pipeline (Agent 2) to find news/events
    that explain detected signals across all KPIs in one call.

    Args:
        country_iso3: ISO-3166 alpha-3 country code.
        kpi_signals: Mapping of KPI name -> list of signal description strings.
        start_year: Start of the analysis window.
        end_year: End of the analysis window.

    Returns:
        List of finding dicts with keys: title, snippet, date, url, source_domain.
    """
    if not kpi_signals:
        return []

    country_name = ISO3_TO_NAME.get(country_iso3, country_iso3)

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
        f"data movements for {country_name}. Return JSON array of findings."
    )

    log.info(
        "Perplexity country overview for %s (%d KPIs, %d signals)",
        country_iso3, len(kpi_signals), len(signal_lines),
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
        findings.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", ""),
            "date": item.get("date", ""),
            "source_domain": item.get("source_domain", ""),
        })

    return findings
