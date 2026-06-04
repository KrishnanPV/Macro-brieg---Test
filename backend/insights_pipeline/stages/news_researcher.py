"""News corroboration step for insights workflow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
from typing import Any

from backend.insights_pipeline.stages.common import NEWS_MODEL, call_json_model

log = logging.getLogger(__name__)

MAX_PARALLEL_SONAR_CALLS = 8

# URL host substrings whose articles describe statistical outcomes rather than
# the causal events we want. Matches are checked as case-insensitive substrings
# anywhere in the event URL. Keep the list narrow - it should catch the most
# common statistical aggregators without nuking legitimate reporting that
# happens to cite these sources.
# ---------------------------------------------------------------------------
# Sonar structured-output schema
# ---------------------------------------------------------------------------
# Perplexity Sonar supports response_format={"type": "json_schema", ...} on
# the chat-completions endpoint, with the same hard constraints OpenAI uses:
# every object must set additionalProperties=False, every property should be
# in `required`, and the schema must include a 1-64 char alphanumeric name
# (provided at call site via response_schema_name).
#
# Without this schema (and without explicit "return JSON" instructions in the
# prompt), Sonar frequently returns prose with embedded citation markers
# (e.g. "Here are 15 events:\n```json\n[...]\n```"). Those calls succeed at
# the HTTP level, get billed, but produce zero usable events downstream.
#
# Pairing this schema with the prompt-level "return JSON only" instruction and
# the embedded-JSON recovery in common.call_json_model gives a three-layer
# guarantee: schema enforcement -> explicit prompt -> regex salvage.

_SONAR_EVENT_TYPE_ENUM: tuple[str, ...] = (
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
)

_SONAR_EVENT_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "title",
        "date",
        "country",
        "summary",
        "source",
        "url",
        "event_type",
        "actor",
        "action",
        "kpi_keywords",
    ],
    "properties": {
        "title": {"type": "string"},
        "date": {"type": "string"},
        "country": {"type": "string"},
        "summary": {"type": "string"},
        "source": {"type": "string"},
        "url": {"type": "string"},
        "event_type": {"type": "string", "enum": list(_SONAR_EVENT_TYPE_ENUM)},
        "actor": {"type": "string"},
        "action": {"type": "string"},
        "kpi_keywords": {"type": "array", "items": {"type": "string"}},
    },
}

SONAR_EVENTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["events"],
    "properties": {
        "events": {"type": "array", "items": _SONAR_EVENT_OBJECT_SCHEMA},
    },
}


STATISTICAL_HOST_DENYLIST: tuple[str, ...] = (
    "gastat.gov.sa",
    "stats.gov.cn",
    "psa.gov.ph",
    "imf.org/en/publications/cr/",
    "imf.org/en/countries/",
    "worldbank.org/en/country/",
    "data.worldbank.org",
    "oecd.org/economy/surveys/",
    "stats.oecd.org",
    "data.un.org",
    "unstats.un.org",
    "tradingeconomics.com",
)


# Shared system prompt used by both ``run_step_sliced`` and
# ``run_planned_queries`` so the actor/action event-extraction discipline stays
# in one place.
_EVENTS_EXTRACTION_SYSTEM_PROMPT: str = (
    "You are a macro events researcher using web search.\n"
    "Goal: return real-world EVENTS that have an identifiable actor and a "
    "specific action - causes that move macro outcomes. Do NOT return "
    "statistical commentary that merely describes what happened.\n\n"
    "INCLUDE - events with a clear actor and action:\n"
    "- Government policy decisions, decrees, regulatory changes, budget announcements\n"
    "- Central-bank rate moves, FX-regime changes, reserve interventions\n"
    "- Sovereign deals: debt issuance, sovereign-fund partnerships, IPOs of state assets\n"
    "- Corporate moves: large M&A, capex commitments, factory openings, listings\n"
    "- Mega-project milestones (NEOM, Red Sea, Vision-2030-style programs, infra mega-deals)\n"
    "- OPEC/OPEC+ production decisions and commodity supply shocks\n"
    "- Sanctions, tariffs, trade-bloc accessions, export bans\n"
    "- Elections and leadership changes that materially shift policy\n"
    "- Geopolitical events: conflicts, embargoes, peace deals, attacks on infrastructure\n\n"
    "EXCLUDE - articles that only describe outcomes, not causes:\n"
    "- IMF Article IV, World Bank country reports, OECD economic surveys\n"
    "- Statistical agency releases (GASTAT, PSA, ONS, BEA-style bulletins)\n"
    "- Central-bank statistical bulletins or data dashboards (these are data, not policy)\n"
    "- Generic 'GDP grew by X%' or 'inflation rose to Y%' reporting unless attributed "
    "to a specific decision\n"
    "- Data revisions, methodology updates, back-cast analyses, or forecasting research notes\n\n"
    "Each event MUST include the following fields:\n"
    "- `title`\n"
    "- `date` (YYYY-MM-DD, or YYYY-MM if exact day unknown)\n"
    "- `country`\n"
    "- `summary` (1-3 sentences)\n"
    "- `source` (publisher name)\n"
    "- `url`\n"
    "- `event_type` (one of: monetary_policy, fiscal_policy, trade_policy, "
    "regulatory_reform, sovereign_deal, corporate_ma_capex, mega_project, "
    "commodity_shock, geopolitical_event, sanction_or_tariff, election_or_leadership_change)\n"
    "- `actor` (the entity that took the action - e.g. 'Saudi Cabinet', 'SAMA', "
    "'Aramco', 'OPEC+', 'US Treasury')\n"
    "- `action` (one short verb phrase describing what was done - e.g. "
    "'raised reverse-repo by 25bps', 'announced $100B partnership', 'cut output by 1mb/d')\n"
    "- `kpi_keywords` (array of which provided keywords/themes the event relates to)\n\n"
    "If you cannot identify both a clear actor AND a clear action, do NOT include the "
    "item. Statistical bulletins and data releases must fail this rule.\n"
    "Only include events that fall inside the specified time window.\n"
    "Aim for breadth - 25-35 events per call - but every event must satisfy the "
    "actor/action rule above.\n\n"
    "OUTPUT FORMAT (strict):\n"
    "Return ONLY a JSON object of the form `{\"events\": [ ...event objects... ]}` "
    "matching the json_schema constraint. Do NOT wrap the JSON in markdown code "
    "fences. Do NOT include any prose, preamble, postamble, or citation markers "
    "outside the JSON. Every event object must contain ALL of: title, date, "
    "country, summary, source, url, event_type, actor, action, kpi_keywords."
)


def _is_statistical_host(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    return any(host in lowered for host in STATISTICAL_HOST_DENYLIST)


def _empty_call_meta() -> dict[str, Any]:
    return {
        "model": NEWS_MODEL,
        "input_tokens": 0,
        "output_tokens": 0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0,
        "calls": 0,
    }


def _accumulate_call_meta(total: dict[str, Any], call_meta: dict[str, Any] | None) -> None:
    if not call_meta:
        return
    total["input_tokens"] += int(call_meta.get("input_tokens", 0) or 0)
    total["output_tokens"] += int(call_meta.get("output_tokens", 0) or 0)
    total["input_cost"] += float(call_meta.get("input_cost", 0.0) or 0.0)
    total["output_cost"] += float(call_meta.get("output_cost", 0.0) or 0.0)
    total["total_cost"] += float(call_meta.get("total_cost", 0.0) or 0.0)
    total["calls"] += 1


def _run_hypothesis_search(
    *,
    hypothesis: dict[str, Any],
    hypothesis_id: str,
    hypothesis_title: str,
    country: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    system_prompt: str,
) -> dict[str, Any]:
    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name}\n"
        f"Window: {start_year}-{end_year}\n\n"
        "Hypothesis:\n"
        f"{json.dumps(hypothesis, indent=2, default=str)}\n\n"
        "Use high-quality sources. Return 3-4 evidence items for this hypothesis only."
    )
    parsed, call_meta = call_json_model(
        model=NEWS_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.news_researcher",
        use_perplexity=True,
        include_call_meta=True,
    )
    return {
        "hypothesis_id": hypothesis_id,
        "hypothesis_title": hypothesis_title,
        "parsed": parsed,
        "call_meta": call_meta,
    }


def run_step(
    *,
    country: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Use Perplexity Sonar to find evidence for generated hypotheses."""
    if not hypotheses:
        return {"evidence_items": [], "research_notes": "No hypotheses to validate.", "call_meta": None}

    system_prompt = (
        "You are a macro news researcher using web search evidence.\n"
        "Find concrete corroborating or contradicting evidence for one hypothesis.\n"
        "Return JSON with keys: `evidence_items` (array) and `research_notes` (string).\n"
        "Each evidence item must include `hypothesis_id`, `stance`, `summary`, `date`, "
        "`source`, and `url`."
    )
    aggregated_meta = _empty_call_meta()
    evidence_items: list[dict[str, Any]] = []
    note_parts: list[str] = []
    max_workers = min(MAX_PARALLEL_SONAR_CALLS, len(hypotheses))
    ordered_results: list[dict[str, Any] | None] = [None] * len(hypotheses)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for index, hypothesis in enumerate(hypotheses, start=1):
            hypothesis_id = str(hypothesis.get("id") or f"hyp_{index}")
            hypothesis_title = str(hypothesis.get("title") or hypothesis_id)
            futures.append(
                (
                    index - 1,
                    executor.submit(
                        _run_hypothesis_search,
                        hypothesis=hypothesis,
                        hypothesis_id=hypothesis_id,
                        hypothesis_title=hypothesis_title,
                        country=country,
                        kpi_name=kpi_name,
                        start_year=start_year,
                        end_year=end_year,
                        system_prompt=system_prompt,
                    ),
                )
            )
        for idx, future in futures:
            ordered_results[idx] = future.result()

    for result in ordered_results:
        if not result:
            continue
        parsed = result["parsed"]
        call_meta = result["call_meta"]
        hypothesis_id = str(result["hypothesis_id"])
        hypothesis_title = str(result["hypothesis_title"])
        _accumulate_call_meta(aggregated_meta, call_meta)

        call_items = parsed.get("evidence_items", [])
        if not call_items and parsed.get("items"):
            call_items = parsed["items"]
        call_items = call_items[:4]
        for item in call_items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("hypothesis_id", hypothesis_id)
            evidence_items.append(normalized)

        notes = str(parsed.get("research_notes", "")).strip()
        if notes:
            note_parts.append(f"{hypothesis_title}: {notes}")

    research_notes = "\n\n".join(note_parts)
    call_meta = aggregated_meta if aggregated_meta["calls"] else None
    return {
        "evidence_items": evidence_items,
        "research_notes": research_notes,
        "call_meta": call_meta,
    }


def run_step_bulk(
    *,
    country: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run one Sonar call for all hypotheses together (cost-efficient mode)."""
    if not hypotheses:
        return {"evidence_items": [], "research_notes": "No hypotheses to validate.", "call_meta": None}

    normalized_hypotheses: list[dict[str, Any]] = []
    for index, hypothesis in enumerate(hypotheses, start=1):
        if not isinstance(hypothesis, dict):
            continue
        hyp = dict(hypothesis)
        hyp.setdefault("id", f"hyp_{index}")
        normalized_hypotheses.append(hyp)

    if not normalized_hypotheses:
        return {"evidence_items": [], "research_notes": "No valid hypotheses to validate.", "call_meta": None}

    system_prompt = (
        "You are a macro news researcher using web search evidence.\n"
        "Find concrete corroborating or contradicting evidence across all provided hypotheses.\n"
        "Return JSON with keys: `evidence_items` (array) and `research_notes` (string).\n"
        "Each evidence item must include `hypothesis_id`, `stance`, `summary`, `date`, "
        "`source`, and `url`."
    )
    user_prompt = (
        f"Country: {country}\n"
        f"KPI scope: {kpi_name}\n"
        f"Window: {start_year}-{end_year}\n\n"
        "Hypotheses:\n"
        f"{json.dumps(normalized_hypotheses, indent=2, default=str)}\n\n"
        "Return 8-12 high-quality evidence items total, spread across hypotheses."
    )
    parsed, call_meta = call_json_model(
        model=NEWS_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.news_researcher.bulk",
        use_perplexity=True,
        include_call_meta=True,
    )

    evidence_items = parsed.get("evidence_items", [])
    if not evidence_items and parsed.get("items"):
        evidence_items = parsed["items"]
    normalized_items: list[dict[str, Any]] = []
    valid_hypothesis_ids = {
        str(hyp.get("id")).strip()
        for hyp in normalized_hypotheses
        if str(hyp.get("id", "")).strip()
    }
    fallback_ids = sorted(valid_hypothesis_ids)
    fallback_idx = 0
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        normalized = dict(item)
        hyp_id = str(normalized.get("hypothesis_id", "")).strip()
        if not hyp_id or hyp_id not in valid_hypothesis_ids:
            if fallback_ids:
                normalized["hypothesis_id"] = fallback_ids[fallback_idx % len(fallback_ids)]
                fallback_idx += 1
        normalized_items.append(normalized)

    return {
        "evidence_items": normalized_items[:12],
        "research_notes": str(parsed.get("research_notes", "")).strip(),
        "call_meta": call_meta,
    }


def _build_year_slices(start_year: int, end_year: int, slice_years: int = 2) -> list[tuple[int, int]]:
    """Split [start_year, end_year] into contiguous slices of ``slice_years``.

    The final slice covers any leftover years (1 to slice_years-1) so we never
    emit a zero-year stub. ``end_year`` is inclusive.
    """
    if slice_years < 1:
        slice_years = 1
    if end_year < start_year:
        start_year, end_year = end_year, start_year
    slices: list[tuple[int, int]] = []
    cursor = start_year
    while cursor <= end_year:
        slice_end = min(cursor + slice_years - 1, end_year)
        slices.append((cursor, slice_end))
        cursor = slice_end + 1
    return slices


def _run_slice_search(
    *,
    query: str,
    country_name: str,
    slice_start: int,
    slice_end: int,
    slice_id: str,
    system_prompt: str,
) -> dict[str, Any]:
    user_prompt = (
        f"Country: {country_name}\n"
        f"Time window: {slice_start}-01-01 to {slice_end}-12-31 (inclusive).\n"
        "Return events that occurred WITHIN this window only. Reject anything outside it.\n\n"
        f"Search query:\n{query}\n\n"
        "Return 10-15 high-recall events. Breadth is more important than precision; "
        "we will filter later.\n\n"
        "Respond with ONLY a JSON object: {\"events\": [ ...event objects... ]}. "
        "No prose, no markdown fences, no citations outside the JSON."
    )
    try:
        parsed, call_meta = call_json_model(
            model=NEWS_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            caller=f"insights_pipeline.news_researcher.sliced[{slice_id}]",
            use_perplexity=True,
            include_call_meta=True,
            max_completion_tokens=8000,
            response_schema=SONAR_EVENTS_SCHEMA,
            response_schema_name="sonar_events",
        )
    except Exception:  # noqa: BLE001
        log.exception("Sliced Sonar call failed for slice %s", slice_id)
        return {"slice_id": slice_id, "parsed": {}, "call_meta": None}
    return {"slice_id": slice_id, "parsed": parsed, "call_meta": call_meta}


def run_step_sliced(
    *,
    country_name: str,
    query: str,
    start_year: int,
    end_year: int,
    slice_years: int = 2,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Run parallel Perplexity Sonar searches over fixed-width year slices.

    The same composite ``query`` is reused for every slice; each per-slice call
    anchors its own date range in the user prompt so Sonar can scope events to
    the slice window. Results are aggregated, deduped on ``url`` (or lowercase
    title fallback), and tagged with their originating ``slice_id``.
    """
    slices = _build_year_slices(start_year, end_year, slice_years=slice_years)
    if not slices or not query.strip():
        return {
            "events": [],
            "query": query,
            "slices": [],
            "call_meta": _empty_call_meta(),
        }

    workers = max_workers if max_workers is not None else MAX_PARALLEL_SONAR_CALLS
    workers = max(1, min(workers, len(slices)))

    system_prompt = _EVENTS_EXTRACTION_SYSTEM_PROMPT

    ordered_results: list[dict[str, Any] | None] = [None] * len(slices)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for idx, (slice_start, slice_end) in enumerate(slices):
            slice_id = f"{slice_start}-{slice_end}"
            futures.append(
                (
                    idx,
                    executor.submit(
                        _run_slice_search,
                        query=query,
                        country_name=country_name,
                        slice_start=slice_start,
                        slice_end=slice_end,
                        slice_id=slice_id,
                        system_prompt=system_prompt,
                    ),
                )
            )
        for idx, future in futures:
            ordered_results[idx] = future.result()

    aggregated_meta = _empty_call_meta()
    seen_keys: set[str] = set()
    events: list[dict[str, Any]] = []
    slice_summaries: list[dict[str, Any]] = []
    event_idx = 1

    for result in ordered_results:
        if not result:
            continue
        slice_id = result["slice_id"]
        parsed = result.get("parsed") or {}
        call_meta = result.get("call_meta")
        _accumulate_call_meta(aggregated_meta, call_meta)

        raw_events = parsed.get("events")
        if not isinstance(raw_events, list):
            raw_events = parsed.get("items") if isinstance(parsed.get("items"), list) else []
        slice_kept = 0
        slice_dropped_host = 0
        slice_dropped_shape = 0
        slice_dropped_dupe = 0
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            title = str(item.get("title") or "").strip().lower()
            dedupe_key = url or title
            if not dedupe_key or dedupe_key in seen_keys:
                slice_dropped_dupe += 1
                continue
            if _is_statistical_host(url):
                slice_dropped_host += 1
                continue
            actor = str(item.get("actor") or "").strip()
            action = str(item.get("action") or "").strip()
            if not actor or not action:
                slice_dropped_shape += 1
                continue
            seen_keys.add(dedupe_key)
            normalized = dict(item)
            normalized["id"] = f"ev_{event_idx}"
            normalized["slice_id"] = slice_id
            normalized["actor"] = actor
            normalized["action"] = action
            event_type = str(normalized.get("event_type") or "").strip()
            if event_type:
                normalized["event_type"] = event_type
            keywords = normalized.get("kpi_keywords")
            if not isinstance(keywords, list):
                normalized["kpi_keywords"] = []
            else:
                normalized["kpi_keywords"] = [str(kw).strip() for kw in keywords if str(kw).strip()]
            events.append(normalized)
            event_idx += 1
            slice_kept += 1
        slice_summaries.append(
            {
                "slice_id": slice_id,
                "dropped_host": slice_dropped_host,
                "dropped_missing_actor_or_action": slice_dropped_shape,
                "dropped_duplicate": slice_dropped_dupe,
                "kept": slice_kept,
                "raw_count": len(raw_events) if isinstance(raw_events, list) else 0,
            }
        )

    return {
        "events": events,
        "query": query,
        "slices": slice_summaries,
        "call_meta": aggregated_meta if aggregated_meta["calls"] else None,
    }


def _run_single_planned_query(
    *,
    planned: dict[str, Any],
    country_name: str,
    start_year: int,
    end_year: int,
    system_prompt: str,
) -> dict[str, Any]:
    """One Sonar call for one planned query, full window in the user prompt."""
    query_id = str(planned.get("query_id") or "")
    query = str(planned.get("query") or "").strip()
    user_prompt = (
        f"Country: {country_name}\n"
        f"Time window: {start_year}-01-01 to {end_year}-12-31 (inclusive).\n"
        "Return events that occurred WITHIN this window only. Reject anything outside it.\n\n"
        f"Search query:\n{query}\n\n"
        "Return 15-25 high-recall events. Breadth is more important than precision; "
        "we will filter later.\n\n"
        "Respond with ONLY a JSON object: {\"events\": [ ...event objects... ]}. "
        "No prose, no markdown fences, no citations outside the JSON."
    )
    try:
        parsed, call_meta = call_json_model(
            model=NEWS_MODEL,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            caller=f"insights_pipeline.news_researcher.planned[{query_id}]",
            use_perplexity=True,
            include_call_meta=True,
            max_completion_tokens=8000,
            response_schema=SONAR_EVENTS_SCHEMA,
            response_schema_name="sonar_events",
        )
    except Exception:  # noqa: BLE001
        log.exception("Planned Sonar call failed for query %s", query_id)
        return {"planned": planned, "parsed": {}, "call_meta": None}
    return {"planned": planned, "parsed": parsed, "call_meta": call_meta}


def run_planned_queries(
    *,
    planned_queries: list[dict[str, Any]],
    country_name: str,
    start_year: int,
    end_year: int,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Run one Sonar call per planned query and attribute results back.

    Each emitted event carries ``query_id`` (from the planned query),
    ``hypothesis_id``, and ``group_ids`` so downstream consumers can map
    evidence to the originating hypothesis or cross-group entry.

    Returns ``{events, by_query, call_meta}``. Empty input -> empty result with
    a zeroed ``call_meta``.
    """
    cleaned: list[dict[str, Any]] = []
    for planned in planned_queries or []:
        if not isinstance(planned, dict):
            continue
        if not str(planned.get("query") or "").strip():
            continue
        cleaned.append(planned)
    if not cleaned:
        return {
            "events": [],
            "by_query": [],
            "call_meta": _empty_call_meta(),
        }

    workers = max_workers if max_workers is not None else MAX_PARALLEL_SONAR_CALLS
    workers = max(1, min(workers, len(cleaned)))

    system_prompt = _EVENTS_EXTRACTION_SYSTEM_PROMPT

    ordered_results: list[dict[str, Any] | None] = [None] * len(cleaned)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for idx, planned in enumerate(cleaned):
            futures.append(
                (
                    idx,
                    executor.submit(
                        _run_single_planned_query,
                        planned=planned,
                        country_name=country_name,
                        start_year=start_year,
                        end_year=end_year,
                        system_prompt=system_prompt,
                    ),
                )
            )
        for idx, future in futures:
            ordered_results[idx] = future.result()

    aggregated_meta = _empty_call_meta()
    seen_keys: set[str] = set()
    events: list[dict[str, Any]] = []
    by_query: list[dict[str, Any]] = []
    event_idx = 1

    for result in ordered_results:
        if not result:
            continue
        planned = result["planned"]
        parsed = result.get("parsed") or {}
        call_meta = result.get("call_meta")
        _accumulate_call_meta(aggregated_meta, call_meta)

        raw_events = parsed.get("events")
        if not isinstance(raw_events, list):
            raw_events = parsed.get("items") if isinstance(parsed.get("items"), list) else []

        kept = 0
        dropped_host = 0
        dropped_shape = 0
        dropped_dupe = 0

        query_id = str(planned.get("query_id") or "")
        hypothesis_id = str(planned.get("hypothesis_id") or "")
        group_ids = [str(g) for g in (planned.get("group_ids") or []) if str(g).strip()]

        for item in raw_events:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip().lower()
            title = str(item.get("title") or "").strip().lower()
            dedupe_key = url or title
            if not dedupe_key or dedupe_key in seen_keys:
                dropped_dupe += 1
                continue
            if _is_statistical_host(url):
                dropped_host += 1
                continue
            actor = str(item.get("actor") or "").strip()
            action = str(item.get("action") or "").strip()
            if not actor or not action:
                dropped_shape += 1
                continue
            seen_keys.add(dedupe_key)
            normalized = dict(item)
            normalized["id"] = f"ev_{event_idx}"
            normalized["query_id"] = query_id
            normalized["hypothesis_id"] = hypothesis_id
            normalized["group_ids"] = list(group_ids)
            normalized["actor"] = actor
            normalized["action"] = action
            event_type = str(normalized.get("event_type") or "").strip()
            if event_type:
                normalized["event_type"] = event_type
            keywords = normalized.get("kpi_keywords")
            if not isinstance(keywords, list):
                normalized["kpi_keywords"] = []
            else:
                normalized["kpi_keywords"] = [
                    str(kw).strip() for kw in keywords if str(kw).strip()
                ]
            events.append(normalized)
            event_idx += 1
            kept += 1

        by_query.append(
            {
                "query_id": query_id,
                "query": str(planned.get("query") or ""),
                "hypothesis_id": hypothesis_id,
                "group_ids": list(group_ids),
                "raw_count": len(raw_events) if isinstance(raw_events, list) else 0,
                "kept": kept,
                "dropped_host": dropped_host,
                "dropped_missing_actor_or_action": dropped_shape,
                "dropped_duplicate": dropped_dupe,
            }
        )

    return {
        "events": events,
        "by_query": by_query,
        "call_meta": aggregated_meta if aggregated_meta["calls"] else _empty_call_meta(),
    }
