"""Composite news search query builder for the country-brief pipeline.

This stage runs a single small LLM call that turns the target country name and
the list of KPI names being analysed into one Perplexity-style search string
plus a flat keyword list. The same query string is reused across every per-slice
Sonar call in :mod:`backend.insights_pipeline.stages.news_researcher`; the slice
caller is responsible for anchoring each call with an explicit date range.

The query is deliberately shaped around causal events (policy decisions,
corporate moves, geopolitical shocks) rather than KPI names, because Sonar
otherwise surfaces statistical agency commentary (GASTAT, IMF Article IV,
World Bank country reports) that describes outcomes for those KPIs.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_json_model

log = logging.getLogger(__name__)

EVENT_CATEGORIES: list[str] = [
    "monetary_policy",
    "fiscal_policy",
    "trade_policy",
    "regulatory_reform",
    "sovereign_deal",
    "corporate_ma_capex",
    "mega_project",
    "commodity_shock",
    "geopolitical_event",
    "sanction_or_tariff",
    "election_or_leadership_change",
]


def _fallback_query(country_name: str, kpi_names: list[str]) -> dict[str, Any]:
    keywords = [
        "policy decision",
        "central bank rate",
        "sovereign deal",
        "regulatory reform",
        "M&A announcement",
        "mega-project",
        "OPEC decision",
        "sanctions",
    ]
    label = country_name.strip() or "the country"
    query = (
        f"{label}: government decisions, central-bank moves, sovereign deals, "
        "major corporate announcements, mega-project milestones, OPEC/commodity "
        "supply decisions, sanctions and trade-policy actions, geopolitical events."
    )
    return {
        "query": query,
        "keywords": keywords,
        "event_categories": list(EVENT_CATEGORIES),
    }


def run_step(
    *,
    country_name: str,
    kpi_names: list[str],
    reasoning_model: str = REASONING_MODEL,
) -> dict[str, Any]:
    """Build one composite search query for the news researcher.

    Returns a dict with keys ``query`` (str), ``keywords`` (list[str]),
    ``event_categories`` (list[str]) and ``call_meta`` (dict | None). On model
    failure the function returns a deterministic fallback so the pipeline can
    still proceed.
    """
    cleaned_kpi_names = [str(name).strip() for name in kpi_names if str(name).strip()]
    label = str(country_name or "").strip()
    if not label:
        fallback = _fallback_query(label or "the country", cleaned_kpi_names)
        fallback["call_meta"] = None
        return fallback

    categories_csv = ", ".join(EVENT_CATEGORIES)
    system_prompt = (
        "You are a macro news query builder. Given a target country and a list of "
        "macroeconomic KPI names, produce ONE Perplexity-style search string that "
        "will surface real-world EVENTS - decisions, announcements, deals, shocks - "
        "that MOVE those KPIs. The KPIs themselves are outcomes; we want the causes.\n\n"
        "Hard rules:\n"
        "- Use the country name (not an ISO code).\n"
        "- Do NOT mention KPI names, statistical concepts, or measurement terms in the "
        "query (no 'GDP', 'inflation rate', 'fiscal balance', 'CPI', etc.). Those words "
        "drag Sonar toward statistical bulletins.\n"
        "- Instead, name the underlying CAUSES. Examples by KPI family:\n"
        "  * For FDI: licensing reforms, M&A deals, sovereign-fund partnerships, free-zone openings.\n"
        "  * For real GDP growth: reform programs, mega-projects, oil-production decisions, "
        "elections/leadership changes, sanctions.\n"
        "  * For inflation/CPI: subsidy reforms, VAT/excise changes, central-bank rate moves, "
        "import bans, currency-regime changes.\n"
        "  * For fiscal balance: budget announcements, debt issuances, asset sales, oil-price events.\n"
        "  * For trade balance: tariff changes, trade-bloc accessions, export bans, supply shocks.\n"
        "- Aim the query at: government decrees, central-bank policy moves, sovereign deals, "
        "large corporate M&A/capex, mega-project milestones, OPEC/commodity decisions, "
        "sanctions/tariffs, elections, geopolitical events.\n"
        "- Keep the query under ~40 words; it will be sent to Perplexity Sonar verbatim.\n"
        "- Do NOT add a date range; the caller will add one per time slice.\n"
        "- Aim for high recall over precision; we will filter events later.\n\n"
        f"Return strict JSON with keys:\n"
        f"  - `query` (string)\n"
        f"  - `keywords` (array of 6-12 evocative cause-side phrases, e.g. 'rate hike', "
        f"'sovereign IPO', 'OPEC+ cut', 'tariff', 'mega-project')\n"
        f"  - `event_categories` (array, subset of: {categories_csv})"
    )
    kpi_block = "\n".join(f"- {name}" for name in cleaned_kpi_names) or "- (none)"
    user_prompt = (
        f"Country: {label}\n"
        f"KPIs in scope (use ONLY to inform which causes matter; do NOT name them in the query):\n"
        f"{kpi_block}\n\n"
        "Build the search query now."
    )
    try:
        parsed, call_meta = call_json_model(
            model=reasoning_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            caller="insights_pipeline.query_builder",
            max_completion_tokens=400,
            include_call_meta=True,
        )
    except Exception:  # noqa: BLE001
        log.exception("query_builder LLM call failed; using deterministic fallback")
        fallback = _fallback_query(label, cleaned_kpi_names)
        fallback["call_meta"] = None
        return fallback

    query = str(parsed.get("query") or "").strip()
    keywords_raw = parsed.get("keywords") or []
    keywords: list[str] = []
    if isinstance(keywords_raw, list):
        for item in keywords_raw:
            text = str(item).strip()
            if text:
                keywords.append(text)
    categories_raw = parsed.get("event_categories") or []
    event_categories: list[str] = []
    valid_categories = set(EVENT_CATEGORIES)
    if isinstance(categories_raw, list):
        for item in categories_raw:
            text = str(item).strip()
            if text and text in valid_categories and text not in event_categories:
                event_categories.append(text)
    if not event_categories:
        event_categories = list(EVENT_CATEGORIES)
    if not query:
        fallback = _fallback_query(label, cleaned_kpi_names)
        fallback["call_meta"] = call_meta
        return fallback
    return {
        "query": query,
        "keywords": keywords,
        "event_categories": event_categories,
        "call_meta": call_meta,
    }
