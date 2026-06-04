"""Country Brief pipeline orchestrator backed by lab workflow stages.

Flow:
  1. Fetch KPI data from Oxford Economics               (deterministic)
  2. Compute derived facts + triage + signals           (deterministic math)
  3. Aggregated insights composition via stage library  (aggregated)
  4. News research — if deep_analysis                   (aggregated)
  5. Stream the brief                                   (1 GPT call, streamed)
  6. Parse blocks + override metrics ribbon             (deterministic)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Iterator

from backend.models.kpi_registry import SPECS
from backend.models.schemas import CountryBriefGenerateRequest, KpiResult
from backend.services.derived_facts import compute_derived_facts
from backend.services.knoema_client import fetch_kpi_data, fetch_oil_price_data
from backend.country_brief.kpi_triage import triage_kpis
from backend.country_brief.metrics_ribbon import compute_ribbon_metrics

from backend.country_brief.benchmark_selector import select_benchmark_countries
from backend.country_brief.brief_writer import stream_brief, parse_brief_blocks
from backend.country_brief.composition.aggregated_insights import run_for_country
from backend.country_brief.fdi_benchmark import build_fdi_benchmark_payload
from backend.country_brief.prompts import build_brief_prompt

log = logging.getLogger(__name__)

# GCC economies — matches frontend region grouping (CountryBrief / Dashboard).
_GCC_CODES = frozenset({"SAU", "ARE", "QAT", "KWT", "BHR", "OMN"})
_OIL_NON_OIL_KPI = "2"
_TRADE_KPI = "13"

# In-memory cache so the frontend can re-slice FDI benchmarks by year
# without re-fetching from Oxford Economics. Keyed by a random UUID.
_fdi_benchmark_cache: dict[str, dict[str, Any]] = {}


def _ndjson(obj: dict[str, Any]) -> str:
    return json.dumps(obj, default=str) + "\n"


def _analysis_ready_results(results_raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return KPI payloads with a usable `series` list for analysis stages.

    Country-brief analysis code consumes `series`; however, some economies only
    publish annual observations for KPI families that are natively quarterly.
    In those cases `fetch_kpi_data(..., dual_fetch=True)` leaves `series` empty
    and places usable rows in `series_annual`.
    """
    normalized: list[dict[str, Any]] = []
    annual_fallback_kpis: list[str] = []
    for raw in results_raw:
        item = dict(raw)
        series = item.get("series")
        annual_series = item.get("series_annual")
        has_native = isinstance(series, list) and bool(series)
        has_annual = isinstance(annual_series, list) and bool(annual_series)

        if not has_native and has_annual:
            item["series"] = list(annual_series)
            item["frequency"] = "A"
            annual_fallback_kpis.append(str(item.get("kpi_id", "")).strip())

        if isinstance(item.get("series"), list) and item.get("series"):
            normalized.append(item)

    return normalized, annual_fallback_kpis


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


_PROFILE_SECTION_ORDER: dict[str, dict[str, int]] = {
    # Default flat sequence:
    #   2 → 12 → 11 → 7 → 6 → 13 → 4 → 14 → 8 → 5 → 9
    "default": {
        "2": 1, "12": 1, "11": 1,
        "7": 2, "6": 2,
        "13": 3, "4": 3,
        "14": 4, "8": 4,
        "5": 5, "9": 5,
    },
    "legacy": {
        "3": 1, "2": 1, "11": 1,
        "2-oil": 1,
        "4": 2, "8": 2,
        "7": 3,
        "5": 4, "6": 4,
        "9": 5,
    },
}

_PROFILE_DISPLAY_ORDER: dict[str, dict[str, int]] = {
    "default": {
        "2": 0, "12": 1, "11": 2,
        "7": 0, "6": 1,
        "13": 0, "4": 1,
        "14": 0, "8": 1,
        "5": 0, "9": 1,
    },
    "legacy": {
        "3": 0, "2": 1, "2-oil": 2, "11": 3,
        "4": 0, "8": 1,
        "7": 0,
        "5": 0, "6": 1,
        "9": 0,
    },
}

_PROFILE_SECTION_KPI_REQUIREMENTS: dict[str, list[tuple[str, set[str]]]] = {
    "default": [
        ("Growth & Economic Structure", {"2", "11", "12"}),
        ("Inflation & Consumption", {"6", "7"}),
        ("External Position & Trade", {"4", "13"}),
        ("Fiscal & External Debt", {"8", "14"}),
        ("Labour & Demographics", {"5", "9"}),
    ],
    "legacy": [
        ("Economic Performance & Growth", {"2", "3", "11"}),
        ("Investment & External Position", {"4", "8"}),
        ("Inflation & Monetary Conditions", {"7"}),
        ("Labour Market & Domestic Demand", {"5", "6"}),
        ("Demographics & Structural Factors", {"9"}),
    ],
}


def _get_pipeline_profile(profile: str) -> tuple[
    dict[str, int], dict[str, int], list[tuple[str, set[str]]]
]:
    p = profile if profile in _PROFILE_SECTION_ORDER else "default"
    return (
        _PROFILE_SECTION_ORDER[p],
        _PROFILE_DISPLAY_ORDER[p],
        _PROFILE_SECTION_KPI_REQUIREMENTS[p],
    )

_SRC_CITATION_RE = re.compile(r"\[src:(\d+)\]", re.IGNORECASE)

# Subset of `signal_interpretation` keys actually referenced by the brief-writer
# prompt. The remaining keys (hypothesis_document, planned_queries,
# news_by_query, signal_event_links, unlinked_signals, unlinked_events) are
# internal pipeline plumbing; shipping them into the writer's JSON injection
# pushes reasoning-token-heavy models past their completion budget and produces
# briefs with empty body sections.
_WRITER_INTERPRETATION_KEYS: tuple[str, ...] = (
    "period_highlight",
    "themes",
    "noise_signals",
    "cross_kpi_connections",
    "composition_shifts",
)


def _required_section_titles(
    ids_with_data: set[str],
    profile: str = "default",
) -> list[str]:
    _, _, section_reqs = _get_pipeline_profile(profile)
    required: list[str] = []
    for title, kpis in section_reqs:
        if not ids_with_data or any(k in ids_with_data for k in kpis):
            required.append(title)
    return required or [title for title, _ in section_reqs]


def _has_tagged_section(raw_text: str, title: str) -> bool:
    pattern = re.compile(rf"\[SECTION:\s*{re.escape(title)}\s*\]", re.IGNORECASE)
    return bool(pattern.search(raw_text))


def _inject_fallback_sources(raw_text: str, fallback_markers: list[str]) -> str:
    if not fallback_markers:
        return raw_text
    source_line = f"\n\nSources: {' '.join(fallback_markers)}"
    outlook_close = raw_text.find("[/OUTLOOK]")
    if outlook_close >= 0:
        return raw_text[:outlook_close] + source_line + "\n" + raw_text[outlook_close:]
    return raw_text + source_line


def _apply_brief_contract_guardrails(
    raw_text: str,
    *,
    required_sections: list[str],
    deep_analysis: bool,
    articles_flat: list[dict[str, Any]],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    text = (raw_text or "").strip()

    if not text:
        text = (
            "[EXEC_SUMMARY]\n"
            "Macro conditions are mixed across the selected window; the section analysis below "
            "summarizes key drivers, inflections, and outlook.\n"
            "[/EXEC_SUMMARY]\n"
        )
        issues.append("empty_model_output")

    if "[EXEC_SUMMARY]" not in text:
        text = (
            "[EXEC_SUMMARY]\n"
            "The selected indicators show a meaningful macro shift; section analysis below "
            "details transmission channels and implications.\n"
            "[/EXEC_SUMMARY]\n\n"
            f"{text}"
        )
        issues.append("missing_exec_summary")

    if "[OUTLOOK]" not in text:
        text += (
            "\n\n[OUTLOOK]\n"
            "**Tailwinds**\n"
            "- Policy and demand resilience can support activity if momentum is sustained.\n\n"
            "**Headwinds**\n"
            "- External volatility and financing conditions remain downside risks.\n\n"
            "**Net Assessment**\n"
            "The near-term balance is mixed; persistence depends on policy execution and global conditions.\n"
            "[/OUTLOOK]"
        )
        issues.append("missing_outlook")

    missing_sections = [title for title in required_sections if not _has_tagged_section(text, title)]
    if missing_sections:
        section_stubs = [
            (
                f"[SECTION:{title}]\n"
                "- Data is limited for this theme in the selected window; prioritize available trend "
                "signals and chart evidence.\n"
                "[/SECTION]"
            )
            for title in missing_sections
        ]
        insert_at = text.find("[OUTLOOK]")
        if insert_at >= 0:
            text = text[:insert_at].rstrip() + "\n\n" + "\n\n".join(section_stubs) + "\n\n" + text[insert_at:]
        else:
            text = text.rstrip() + "\n\n" + "\n\n".join(section_stubs)
        issues.extend([f"missing_section:{title}" for title in missing_sections])

    if deep_analysis and articles_flat:
        existing_markers = set(_SRC_CITATION_RE.findall(text))
        required_citations = min(2, len(articles_flat))
        if len(existing_markers) < required_citations:
            fallback_markers: list[str] = []
            for article in articles_flat:
                idx = article.get("index")
                if idx is None:
                    idx = article.get("n")
                if idx is None:
                    continue
                marker = str(idx)
                if marker in existing_markers or marker in fallback_markers:
                    continue
                fallback_markers.append(marker)
                if len(existing_markers) + len(fallback_markers) >= required_citations:
                    break
            if fallback_markers:
                text = _inject_fallback_sources(text, [f"[src:{n}]" for n in fallback_markers])
                issues.append("citation_fallback_added")

    return text, issues


def _compute_exhibit_map(
    notable_kpi_ids: list[str],
    profile: str = "default",
) -> dict[str, str]:
    """Pre-compute deterministic exhibit labels (e.g. '1A', '2A') from notable KPIs."""
    section_order, display_order, _ = _get_pipeline_profile(profile)
    section_kpis: dict[int, list[str]] = {}
    for kid in notable_kpi_ids:
        sec = section_order.get(kid)
        if sec:
            section_kpis.setdefault(sec, []).append(kid)
    exhibit_map: dict[str, str] = {}
    for sec in sorted(section_kpis):
        kpis = sorted(section_kpis[sec], key=lambda k: display_order.get(k, 99))
        for i, kid in enumerate(kpis):
            letter = chr(ord("A") + i)
            exhibit_map[kid] = f"{sec}{letter}"
    return exhibit_map


def _build_exhibit_kpi_ids(*, notable_kpi_ids: list[str], is_gcc: bool) -> list[str]:
    """Build KPI IDs used for exhibit numbering.

    ``is_gcc`` is currently unused but kept so future GCC-only exhibits can
    plug in without changing call sites.
    """
    del is_gcc  # reserved for future GCC-only exhibits
    return [str(k).strip() for k in notable_kpi_ids if str(k).strip()]


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


def _check_exhibit_label_sequence(blocks: list[dict[str, Any]]) -> list[str]:
    """Validate section exhibit labels are contiguous (A, B, C...) without gaps."""
    issues: list[str] = []
    for block in blocks:
        if block.get("type") != "section":
            continue
        labels = [
            str(child.get("exhibit_label", "")).strip()
            for child in block.get("children") or []
            if child.get("type") == "chart_ref"
        ]
        if not labels:
            continue
        expected_prefix = labels[0][:-1]
        for idx, label in enumerate(labels):
            expected_label = f"{expected_prefix}{chr(ord('A') + idx)}"
            if label != expected_label:
                issues.append(f"{block.get('title', 'section')}:{label}->{expected_label}")
    return issues


def _is_demographics_section_title(title: str) -> bool:
    """Match demographics section even if the model shortens the heading.

    Must match across all chart_order_profile variants — "Debt, Labour Market
    & Demographics" (default), "Labour Market & Demographics" (older default),
    and "Demographics & Structural Factors" (legacy).
    """
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
            "title": "Labour & Demographics",
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


def _reorder_section_charts(
    blocks: list[dict[str, Any]],
    profile: str = "default",
) -> list[dict[str, Any]]:
    """Sort chart_ref children within each section by the profile's display order.

    The LLM may emit [CHART:kpi_id] markers in any order; this step enforces
    the canonical chart sequence so the frontend renders them correctly.
    Narrative children keep their relative positions between charts.
    """
    _, display_order, _ = _get_pipeline_profile(profile)
    for block in blocks:
        if block.get("type") != "section":
            continue
        children = block.get("children") or []
        charts = [c for c in children if c.get("type") == "chart_ref"]
        non_charts = [c for c in children if c.get("type") != "chart_ref"]
        if len(charts) <= 1:
            continue
        charts.sort(key=lambda c: display_order.get(str(c.get("kpi_id", "")), 99))
        block["children"] = [*charts, *non_charts]
    return blocks


def _ensure_required_section_charts(
    blocks: list[dict[str, Any]],
    *,
    profile: str,
    notable_set: set[str],
    ids_with_data: set[str],
) -> list[dict[str, Any]]:
    """Inject any notable KPI mapped to a section that the LLM omitted.

    The LLM is unreliable about emitting every ``[CHART:kpi_id]`` it should.
    For each section in the profile's KPI requirement map, we add a chart_ref
    for any notable KPI that has data but wasn't already referenced anywhere in
    the brief. ``_reorder_section_charts`` will then sort them into canonical
    position (e.g. KPI 12 lands at 1B).
    """
    _, _, section_kpi_map = _get_pipeline_profile(profile)
    # All chart_refs anywhere in the brief — avoid double-inserting a KPI
    # that the LLM placed in the "wrong" section.
    already_referenced: set[str] = set()
    for block in blocks:
        if block.get("type") != "section":
            continue
        for child in block.get("children") or []:
            if child.get("type") == "chart_ref":
                already_referenced.add(str(child.get("kpi_id", "")))

    for section_title, required_kpis in section_kpi_map:
        target_block = None
        for block in blocks:
            if block.get("type") == "section" and block.get("title") == section_title:
                target_block = block
                break
        if target_block is None:
            continue
        missing = [
            kid for kid in required_kpis
            if kid in notable_set
            and kid in ids_with_data
            and kid not in already_referenced
        ]
        if not missing:
            continue
        log.info(
            "Injecting missing chart_refs %s into section %r (LLM omitted)",
            missing, section_title,
        )
        inserts = [{"type": "chart_ref", "kpi_id": kid} for kid in missing]
        existing_children = list(target_block.get("children") or [])
        target_block["children"] = [*inserts, *existing_children]
        already_referenced.update(missing)
    return blocks


def run_pipeline(
    req: CountryBriefGenerateRequest,
    *,
    deep_analysis: bool = False,
) -> Iterator[str]:
    """Generate a country brief using insights stage building blocks.

    Analysis stages (aggregated over selected KPIs): signal extraction,
    hypotheses, optional evidence research, and insight refinement from
    `backend.insights_pipeline.stages`.
    Final stage: stream country brief markdown and parse into frontend blocks.
    """
    profile = getattr(req, "chart_order_profile", "default") or "default"
    all_oxford_ids = [s.id for s in SPECS if s.source == "oxford"]
    manual_selection = bool(req.kpi_ids)
    available_ids = req.kpi_ids if req.kpi_ids else all_oxford_ids
    available_ids = [kid for kid in available_ids if kid in {s.id for s in SPECS if s.source == "oxford"}]
    if not available_ids:
        available_ids = all_oxford_ids
    is_gcc = req.country.upper() in _GCC_CODES
    # Automatic + GCC: always fetch oil/non-oil; other economies rely on triage-only selection.
    if not manual_selection and is_gcc:
        if _OIL_NON_OIL_KPI not in available_ids:
            available_ids.append(_OIL_NON_OIL_KPI)
    # KPI 3 (Real GDP Growth YoY) is hidden from the selector but still required
    # internally: the metrics ribbon expects it (see metrics_ribbon.order) and
    # L2 GDP context in aggregated_insights.py uses it. Force-include for fetching;
    # it gets stripped from notable_ids below so it never renders as its own chart.
    if "3" not in available_ids and "3" in {s.id for s in SPECS if s.source == "oxford"}:
        available_ids.append("3")
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
    # Oil price overlay for KPI 13 (Trade — Exports & Imports).
    # Only fetched when the Trade KPI is in scope; the overlay never appears
    # on any other chart.
    if _TRADE_KPI in available_ids:
        yield _ndjson({"type": "status", "content": "Fetching Brent oil price overlay..."})
        try:
            oil_overlay = fetch_oil_price_data(
                country=req.country,
                timerange=timerange,
                frequency="A",
            )
            if oil_overlay:
                for r in fetch_resp.results:
                    if r.kpi_id == _TRADE_KPI:
                        r.oil_price_overlay = oil_overlay
                        break
                log.info("Oil price overlay attached to Trade chart for %s", req.country)
            else:
                log.info("Oil price overlay unavailable for %s — skipping.", req.country)
        except Exception as exc:
            log.warning("Oil price overlay failed for %s: %s", req.country, exc)

    results_raw = [r.model_dump() for r in fetch_resp.results]
    yield _ndjson({"type": "kpi_data", "content": results_raw})

    valid_results, annual_fallback_kpis = _analysis_ready_results(results_raw)
    if annual_fallback_kpis:
        log.info(
            "Country brief analysis using annual fallback series for %s (country=%s)",
            ", ".join(annual_fallback_kpis),
            req.country,
        )

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

    # ── Phase 2: KPI triage + lab workflow analysis ──────────────────────
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

    # KPI 12 already plots total real GDP growth alongside oil/non-oil splits,
    # so KPI 3 is redundant as a standalone chart in the default profile. Keep
    # it fetched for the metrics ribbon and L2 GDP context; just exclude it
    # from notable_ids so the brief writer never emits [CHART:3]. Unconditional
    # in the default profile — even manual selection cannot bring KPI 3 back
    # because the selector itself no longer exposes it.
    if profile == "default":
        notable_ids = [kid for kid in notable_ids if kid != "3"]
        for s in scores:
            if s.kpi_id == "3":
                s.notable = False

    yield _ndjson({
        "type": "triage",
        "content": [
            {"kpi_id": s.kpi_id, "kpi_name": s.kpi_name,
             "score": s.score, "notable": s.notable, "reasons": s.reasons}
            for s in scores
        ],
    })

    selected_kpi_ids = [kid for kid in notable_ids if kid in ids_with_data]
    if not selected_kpi_ids:
        selected_kpi_ids = [kid for kid in available_ids if kid in ids_with_data]
    notable_ids = selected_kpi_ids

    yield _ndjson({
        "type": "status",
        "content": (
            f"Running {'deep' if deep_analysis else 'light'} insights workflow "
            f"for {len(selected_kpi_ids)} selected KPIs..."
        ),
    })
    if deep_analysis:
        yield _ndjson({"type": "status", "content": "Searching for correlated news..."})

    kpi_results_by_id = {str(r.get("kpi_id", "")): r for r in valid_results}
    signal_interpretation, articles_flat, prompt_bundle = run_for_country(
        country=req.country,
        start_year=req.start_year,
        end_year=req.end_year,
        selected_kpi_ids=selected_kpi_ids,
        kpi_results=kpi_results_by_id,
        deep_analysis=deep_analysis,
    )

    if deep_analysis:
        hypothesis_doc = signal_interpretation.get("hypothesis_document") or {}
        hypothesis_groups = hypothesis_doc.get("hypothesis_groups") or []
        planned_queries = signal_interpretation.get("planned_queries") or []
        news_by_query = signal_interpretation.get("news_by_query") or []
        log.info(
            "Deep-mode counts | hypothesis_groups=%d planned_queries=%d events=%d articles=%d",
            len(hypothesis_groups),
            len(planned_queries),
            len(news_by_query),
            len(articles_flat),
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
        chart_order_profile=profile,
        is_gcc=is_gcc,
    )

    writer_interpretation: dict[str, Any] = {}
    if isinstance(signal_interpretation, dict):
        for key in _WRITER_INTERPRETATION_KEYS:
            if key in signal_interpretation:
                writer_interpretation[key] = signal_interpretation[key]
    interpretation_json = json.dumps(writer_interpretation, indent=2, default=str)

    period_highlight = ""
    if isinstance(signal_interpretation, dict):
        period_highlight = signal_interpretation.get("period_highlight", "")

    injection = (
        "SIGNAL INTERPRETATION (from aggregated insights workflow):\n"
        f"```json\n{interpretation_json}\n```\n\n"
    )

    if period_highlight:
        injection += (
            f"PERIOD HIGHLIGHT (use this as the governing thought for the executive summary):\n"
            f"{period_highlight}\n\n"
        )

    exhibit_kpi_ids = _build_exhibit_kpi_ids(notable_kpi_ids=notable_ids, is_gcc=is_gcc)
    exhibit_map = _compute_exhibit_map(exhibit_kpi_ids, profile=profile)
    if exhibit_map:
        exhibit_lines = ", ".join(f"KPI {k} = ({v})" for k, v in sorted(exhibit_map.items()))
        injection += (
            "EXHIBIT MAP — use these labels when you reference chart data in prose:\n"
            f"{exhibit_lines}\n"
            "- When you state a chart-sourced number in prose, append the exhibit label "
            "in parentheses, e.g. 'real GDP grew 3.1% (1B)'. Just the code, no 'Exhibit'.\n"
            "- Keep [CHART:kpi_id] markers inside [SECTION:...] bodies only — they are "
            "chart-placement directives, not prose references. Avoid them in "
            "[EXEC_SUMMARY] and [OUTLOOK]; the parser strips them there anyway.\n\n"
        )

    injection += (
        "HOW TO USE THIS INTERPRETATION:\n"
        "Each causal_chain has a trigger, mechanism, and kpi_impact. "
        "Translate each into a natural prose bullet — name the trigger and the data outcome, "
        "and describe the channel only when the mechanism is directly evidenced. "
        "When the mechanism is inferred rather than proven, use cautious connectors such as "
        "'is consistent with', 'may reflect', 'coincides with', 'partly attributable to', "
        "or 'against a backdrop of' instead of asserting causation. "
        "Do not adopt strong upstream wording verbatim — rephrase any assertive language from "
        "the interpretation (e.g. 'swung decisively', 'dominant engine', 'tightened') into "
        "neutral, evidence-led prose. "
        "Do NOT use arrow symbols or template notation in your prose. "
        "Ignore noise_signals. Use cross_kpi_connections to synthesize.\n\n"
    )

    if deep_analysis and articles_flat:
        injection += (
            "DEEP-MODE CITATION GUIDANCE (NEWS_CONTEXT is present):\n"
            "- When a structural claim about policy, events, or institutional decisions "
            "draws from NEWS_CONTEXT, append [src:N] using the article's `n` field.\n"
            "- Aim to place citations in 3+ different sections rather than clustering them "
            "in one bullet.\n"
            "- Only cite articles you actually drew from; never invent `n` values that are "
            "not in NEWS_CONTEXT.\n\n"
        )

    messages.append({"role": "user", "content": injection})

    full_text = ""
    for event_type, payload in stream_brief(messages):
        if event_type == "text_delta":
            yield _ndjson({"type": "text_delta", "content": payload})
        elif event_type == "full_text":
            full_text = payload

    # ── Phase 5: Parse and finalize ──────────────────────────────────────
    required_sections = _required_section_titles(ids_with_data, profile=profile)
    guarded_text, guardrail_issues = _apply_brief_contract_guardrails(
        full_text,
        required_sections=required_sections,
        deep_analysis=deep_analysis,
        articles_flat=articles_flat,
    )
    if guardrail_issues:
        log.warning("Applied brief contract guardrails: %s", ", ".join(guardrail_issues))
        yield _ndjson({"type": "status", "content": "Applying output contract guardrails..."})

    blocks = parse_brief_blocks(guarded_text)
    blocks = _ensure_kpi9_demographics_chart(blocks, ids_with_data)
    blocks = _ensure_required_section_charts(
        blocks,
        profile=profile,
        notable_set=set(notable_ids),
        ids_with_data=ids_with_data,
    )
    fallback_chart_ids = [kid for kid in available_ids if kid in ids_with_data]
    blocks = _ensure_chart_blocks(blocks, preferred_chart_ids=fallback_chart_ids)
    _assign_exhibit_labels(blocks, exhibit_map)
    blocks = _reorder_section_charts(blocks, profile=profile)
    exhibit_issues = _check_exhibit_label_sequence(blocks)
    if exhibit_issues:
        log.warning("Non-sequential exhibit labels detected: %s", "; ".join(exhibit_issues))
    computed_metrics = compute_ribbon_metrics(derived_facts)
    if computed_metrics:
        blocks = [b for b in blocks if b.get("type") != "metrics_ribbon"]
        blocks.insert(0, {"type": "metrics_ribbon", "metrics": computed_metrics})

    yield _ndjson({"type": "blocks", "content": blocks})
    yield _ndjson({"type": "done"})
