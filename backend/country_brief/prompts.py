"""Prompt assembly for the Country Brief 3-agent pipeline."""
from __future__ import annotations

from functools import lru_cache
import json
import logging
import re
from typing import Any

from backend.insights_pipeline.runtime import PROMPTS_DIR, load_prompt_manifest, load_prompt_text
from backend.models.kpi_registry import INSIGHT_LENSES, sorted_kpi_ids
from backend.services.news_client import flatten_news_catalog

log = logging.getLogger(__name__)

_SRC_MARKERS_RE = re.compile(r"\s*\[src:\d+\]\s*")


def strip_source_markers(text: str) -> str:
    """Remove [src:N] citation tokens (e.g. for refine prompts)."""
    return _SRC_MARKERS_RE.sub(" ", text or "").strip()


BRIEF_WRITER_SYSTEM_PROMPT = """\
You are a senior economist writing an integrated country brief.
Follow OUTPUT_CONTRACT_JSON exactly.
Write concise, causal, decision-oriented prose grounded in the provided data.
Return only the marked brief content. No preamble or meta commentary.
Never surface confidence flags (e.g. "Confidence: High", "Confidence: Medium-High") in the brief output — confidence assessments are internal and must not appear in any bullet, sub-bullet, or sentence.
"""

FOCUS_ADDENDUM_TEMPLATE = """\

USER FOCUS — the analyst has requested emphasis on:
"{focus}"

Weight your analysis toward this focus. Dedicate more depth and narrative space to KPIs and themes relevant to this focus. You may still cover other notable themes, but this focus should be the primary lens.
"""

_SECTION_SPECS: dict[str, dict] = {
    "default": {
        "titles": [
            "Economic Structure & Growth",
            "Inflation",
            "External Position & Investment",
            "Domestic Demand & Public Finances",
            "Labour Market & Demographics",
        ],
        "kpi_map": {
            "Economic Structure & Growth":       ["2", "3", "11", "1"],
            "Inflation":                         ["7"],
            "External Position & Investment":    ["4"],
            "Domestic Demand & Public Finances":  ["6", "8"],
            "Labour Market & Demographics":      ["5", "9"],
        },
    },
    "legacy": {
        "titles": [
            "Economic Performance & Growth",
            "Investment & External Position",
            "Inflation & Monetary Conditions",
            "Labour Market & Domestic Demand",
            "Demographics & Structural Factors",
        ],
        "kpi_map": {
            "Economic Performance & Growth": ["3", "2", "11", "1"],
            "Investment & External Position": ["4", "8"],
            "Inflation & Monetary Conditions": ["7"],
            "Labour Market & Domestic Demand": ["5", "6"],
            "Demographics & Structural Factors": ["9"],
        },
    },
}

BRIEF_SECTION_TITLES = _SECTION_SPECS["legacy"]["titles"]


def _get_section_spec(profile: str = "default") -> dict:
    return _SECTION_SPECS.get(profile, _SECTION_SPECS["default"])

_CORE_CONTRACT = {
    "version": "v1",
    "block_markers": {
        "metrics_ribbon": {"required": False, "start": "[METRICS_RIBBON]", "end": "[/METRICS_RIBBON]"},
        "executive_summary": {"required": True, "start": "[EXEC_SUMMARY]", "end": "[/EXEC_SUMMARY]"},
        "section": {"required": True, "start": "[SECTION:Title]", "end": "[/SECTION]"},
        "outlook": {"required": True, "start": "[OUTLOOK]", "end": "[/OUTLOOK]"},
        "chart_ref": {"format": "[CHART:kpi_id]", "max_per_kpi": 1},
    },
    "section_rules": {
        "use_exact_titles": True,
        "keep_inflation_and_labour_separate": True,
        "target_top_level_bullets_per_section": "3-5",
        "first_bullet_policy": "Start with one bolded governing sentence, then evidence.",
        "sub_bullet_policy": "Use indented sub-bullets for supporting evidence/mechanisms whenever possible; keep standalone bullets only when support detail is genuinely minimal.",
    },
    "outlook_subheads_required": ["**Tailwinds**", "**Headwinds**", "**Net Assessment**"],
}


def _required_sections_for_kpis(
    notable_kpi_ids: list[str],
    profile: str = "default",
) -> list[str]:
    spec = _get_section_spec(profile)
    titles = spec["titles"]
    kpi_map = spec["kpi_map"]
    if not notable_kpi_ids:
        return list(titles)
    notable = {str(k) for k in notable_kpi_ids}
    required: list[str] = []
    for section_title in titles:
        section_kpis = kpi_map.get(section_title, [])
        if any(k in notable for k in section_kpis):
            required.append(section_title)
    return required or list(titles)


def _compact_result_payload(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_results: list[dict[str, Any]] = []
    for result in results:
        compact_series: list[dict[str, Any]] = []
        for series in result.get("series") or []:
            numeric_points: list[dict[str, Any]] = []
            for point in series.get("points") or []:
                date = str(point.get("date", "")).strip()
                if not date:
                    continue
                try:
                    value = float(point.get("value"))
                except (TypeError, ValueError):
                    continue
                numeric_points.append({"date": date, "value": value})
            if not numeric_points:
                continue
            numeric_points.sort(key=lambda p: p["date"])
            peak = max(numeric_points, key=lambda p: p["value"])
            trough = min(numeric_points, key=lambda p: p["value"])
            compact_series.append({
                "indicator": series.get("indicator", ""),
                "unit": series.get("unit") or result.get("unit", ""),
                "start": numeric_points[0],
                "end": numeric_points[-1],
                "peak": peak,
                "trough": trough,
            })
        compact_results.append({
            "kpi_id": str(result.get("kpi_id", "")),
            "kpi_name": result.get("kpi_name", ""),
            "unit": result.get("unit", ""),
            "series": compact_series,
        })
    return compact_results


def _compact_derived_facts_payload(derived_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact_facts: list[dict[str, Any]] = []
    keep_series_keys = ("country", "indicator", "unit", "n_points", "earliest", "latest", "prior", "min", "max", "change_pct", "cagr")
    for fact in derived_facts:
        compact_fact: dict[str, Any] = {
            "kpi_id": str(fact.get("kpi_id", "")),
            "kpi_name": fact.get("kpi_name", ""),
            "unit": fact.get("unit", ""),
            "series_facts": [],
        }
        for sf in fact.get("series_facts") or []:
            compact_series_fact = {key: sf[key] for key in keep_series_keys if key in sf and sf.get(key) is not None}
            window = sf.get("window_summary")
            if isinstance(window, dict):
                compact_series_fact["window_summary"] = {
                    key: window.get(key)
                    for key in ("mean", "best", "worst")
                    if window.get(key) is not None
                }
            inflections = sf.get("inflection_points") or []
            if inflections:
                compact_series_fact["inflection_points"] = inflections[:3]
            segments = sf.get("trend_segments") or []
            if segments:
                compact_series_fact["trend_segments"] = segments[:2]
            compact_fact["series_facts"].append(compact_series_fact)
        for optional_key in ("composition", "net_flow", "growth_gap"):
            optional_val = fact.get(optional_key)
            if not isinstance(optional_val, list) or not optional_val:
                continue
            if optional_key == "composition":
                shift_rows = [
                    row for row in optional_val
                    if isinstance(row, dict) and row.get("type") == "share_shift_summary"
                ]
                compact_fact[optional_key] = shift_rows[:1] if shift_rows else optional_val[-1:]
            else:
                if len(optional_val) <= 2:
                    compact_fact[optional_key] = optional_val
                else:
                    compact_fact[optional_key] = optional_val[:2] + optional_val[-1:]
        compact_facts.append(compact_fact)
    return compact_facts


def _compact_lenses_payload(notable_kpi_ids: list[str], kpi_units: dict[str, str]) -> list[dict[str, Any]]:
    compact_lenses: list[dict[str, Any]] = []
    for kpi_id in sorted_kpi_ids(notable_kpi_ids):
        lens = INSIGHT_LENSES.get(kpi_id)
        if not lens:
            continue
        compact_lens: dict[str, Any] = {
            "kpi_id": kpi_id,
            "headline": lens.headline,
            "notability_cues": lens.notability_cues[:3],
        }
        if lens.context_hooks:
            compact_lens["context_hooks"] = lens.context_hooks[:2]
        if lens.narrative_guidance:
            compact_lens["narrative_guidance"] = lens.narrative_guidance[:2]
        data_unit = kpi_units.get(kpi_id, "")
        if data_unit:
            compact_lens["data_unit"] = data_unit
        if lens.units_note:
            compact_lens["units_note"] = lens.units_note
        compact_lenses.append(compact_lens)
    return compact_lenses


@lru_cache(maxsize=1)
def _load_lab_brief_writer_guidelines() -> str:
    """Load lab brief-writer style/system prompts from manifest."""
    manifest, manifest_error = load_prompt_manifest()
    if manifest_error:
        log.warning("Failed loading insights prompt manifest for brief guidelines: %s", manifest_error)
        return ""

    prompt_entries = manifest.get("prompts")
    if not isinstance(prompt_entries, list):
        return ""

    selected_files: list[str] = []
    for prompt_entry in prompt_entries:
        if not isinstance(prompt_entry, dict):
            continue
        used_by = prompt_entry.get("used_by")
        if not isinstance(used_by, list) or "brief_writer" not in used_by:
            continue
        file_name = str(prompt_entry.get("file", "")).strip()
        if not file_name or file_name in selected_files:
            continue
        selected_files.append(file_name)

    if not selected_files:
        return ""

    blocks: list[str] = []
    for file_name in selected_files:
        content = load_prompt_text(file_name)
        if not content:
            continue
        blocks.append(f"[{file_name}]\n{content}")

    if not blocks:
        return ""
    return (
        f"LAB BRIEF WRITER GUIDELINES (from {PROMPTS_DIR.as_posix()}/manifest.yaml):\n"
        + "\n\n".join(blocks)
    )


BENCHMARK_SELECTOR_SYSTEM_PROMPT = """\
You are selecting benchmark countries for an FDI comparison chart.

Output JSON ONLY in this exact shape:
{"global":["ISO3","ISO3"],"regional":["ISO3","ISO3"]}

Rules:
- Exactly 2 global peers and exactly 2 regional peers.
- Use only the allowed candidate pools.
- Never include the target country.
- No duplicate countries across both lists.
- Return ISO3 codes only.
- Prefer countries with reasonably comparable economy/FDI scale to the target.
- Avoid selecting extreme superpower outliers unless no comparable alternatives are available.
"""


def build_benchmark_selector_prompt(
    *,
    country: str,
    country_name: str,
    region_group: str,
    start_year: int,
    end_year: int,
    global_pool: list[str],
    regional_pool: list[str],
) -> str:
    return (
        f"Target country: {country} ({country_name})\n"
        f"Target region group: {region_group}\n"
        f"Window: {start_year}-{end_year}\n\n"
        f"Allowed global candidates: {', '.join(global_pool)}\n"
        f"Allowed regional candidates: {', '.join(regional_pool)}\n"
    )


def parse_benchmark_selector_response(
    text: str,
    *,
    target_country: str,
    global_pool: list[str],
    regional_pool: list[str],
) -> dict[str, list[str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Benchmark selector response is not a JSON object.")

    target = target_country.upper()
    global_allowed = {c.upper() for c in global_pool}
    regional_allowed = {c.upper() for c in regional_pool}

    selected_global: list[str] = []
    seen: set[str] = {target}
    for raw in parsed.get("global", []):
        code = str(raw).upper().strip()
        if not code or code in seen or code not in global_allowed:
            continue
        selected_global.append(code)
        seen.add(code)
        if len(selected_global) == 2:
            break

    selected_regional: list[str] = []
    for raw in parsed.get("regional", []):
        code = str(raw).upper().strip()
        if not code or code in seen or code not in regional_allowed:
            continue
        selected_regional.append(code)
        seen.add(code)
        if len(selected_regional) == 2:
            break

    return {"global": selected_global, "regional": selected_regional}


def build_brief_prompt(
    country: str,
    start_year: int,
    end_year: int,
    results: list[dict[str, Any]],
    derived_facts: list[dict[str, Any]],
    notable_kpi_ids: list[str],
    news_context: dict[str, Any] | None = None,
    news_prompt_bundle: dict[str, Any] | None = None,
    focus: str | None = None,
    manual_selection: bool = False,
    fdi_benchmark_context: dict[str, Any] | None = None,
    chart_order_profile: str = "default",
) -> list[dict[str, str]]:
    """Assemble the ChatCompletion messages for brief generation."""
    spec = _get_section_spec(chart_order_profile)
    kpi_map = spec["kpi_map"]

    lab_guidelines = _load_lab_brief_writer_guidelines()
    system_prompt = BRIEF_WRITER_SYSTEM_PROMPT
    if lab_guidelines:
        system_prompt = f"{system_prompt}\n\n{lab_guidelines}"

    kpi_units: dict[str, str] = {}
    for r in results:
        kid = str(r.get("kpi_id", ""))
        u = r.get("unit", "")
        if kid and u:
            kpi_units[kid] = u

    compact_lenses = _compact_lenses_payload(notable_kpi_ids, kpi_units)

    notable_set = set(notable_kpi_ids)
    filtered_results = [r for r in results if str(r.get("kpi_id", "")) in notable_set]
    filtered_facts = [f for f in derived_facts if str(f.get("kpi_id", "")) in notable_set]

    required_sections = _required_sections_for_kpis(notable_kpi_ids, profile=chart_order_profile)
    output_contract = {
        **_CORE_CONTRACT,
        "required_sections": required_sections,
        "section_kpi_map": {
            section: [kid for kid in kpi_map.get(section, []) if kid in notable_set]
            for section in required_sections
        },
    }

    data_context = {
        "country": country,
        "time_range": f"{start_year}-{end_year}",
        "notable_kpi_ids": notable_kpi_ids,
        "kpi_snapshots": _compact_result_payload(filtered_results),
        "derived_facts": _compact_derived_facts_payload(filtered_facts),
        "kpi_lenses": compact_lenses,
        "fdi_benchmark_context": fdi_benchmark_context or {},
    }

    news_block = ""
    if news_prompt_bundle is not None:
        news_json = json.dumps(news_prompt_bundle, default=str)
        news_block = (
            "\n\nNEWS_CONTEXT (JSON) — articles use 1-based \"n\" for [src:N] markers at line ends:\n"
            f"```json\n{news_json}\n```\n"
        )
    elif news_context:
        _, bundle = flatten_news_catalog(news_context)
        news_json = json.dumps(bundle, default=str)
        news_block = (
            "\n\nNEWS_CONTEXT (JSON) — articles use 1-based \"n\" for [src:N] markers at line ends:\n"
            f"```json\n{news_json}\n```\n"
        )

    focus_block = ""
    if focus and focus.strip():
        focus_block = FOCUS_ADDENDUM_TEMPLATE.format(focus=focus.strip())

    manual_block = ""
    if manual_selection:
        manual_block = (
            "\n\nMANUAL KPI SELECTION is active.\n"
            "- Every selected KPI with available data must appear in the brief body.\n"
            "- Include one [CHART:kpi_id] marker for each selected KPI.\n"
        )

    fdi_benchmark_block = ""
    if fdi_benchmark_context:
        fdi_json = json.dumps(fdi_benchmark_context, default=str)
        fdi_benchmark_block = (
            "\n\nFDI_BENCHMARK_CONTEXT (JSON) — authoritative comparator set for KPI 4:\n"
            f"```json\n{fdi_json}\n```\n"
            "If you discuss KPI 4 (FDI), use these benchmark peers consistently in prose.\n"
        )

    user_content = (
        f"Generate a country brief for **{country}** covering {start_year}–{end_year}.\n\n"
        "OUTPUT_CONTRACT_JSON (authoritative):\n"
        f"```json\n{json.dumps(output_contract, default=str)}\n```\n\n"
        "DATA_CONTEXT (JSON):\n"
        f"```json\n{json.dumps(data_context, default=str)}\n```\n"
        + news_block
        + fdi_benchmark_block
        + focus_block
        + manual_block
        + "\n\n"
        "INSTRUCTIONS:\n"
        "1. Follow OUTPUT_CONTRACT_JSON exactly; treat it as the single format authority.\n"
        "2. Keep each section concise and insight-first: what changed, why, and what follows.\n"
        "3. Use [CHART:kpi_id] markers where the narrative references that KPI trend.\n"
        "4. Use annual references and avoid quarter-by-quarter narration unless essential.\n"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]


REFINE_SYSTEM_PROMPT = """\
You are a senior macro-economic analyst helping refine a section of a country brief. You have the original section text and the underlying KPI data. The analyst will ask you to revise, expand, condense, or reframe the section.

Rules:
- Preserve all factual accuracy — never change numbers unless the data supports it.
- Maintain the analytical depth and specificity of the original.
- When asked to expand, add genuine analytical value (causal mechanisms, policy context, implications) — not filler.
- When asked to condense, keep the most impactful insights and cut the rest.
- Return ONLY the revised section text. Do not include preamble like "Here's the revised version".
- For section bodies (not Executive Summary), use markdown bullets only: each line "- " + one insight. No paragraphs unless the user asks for prose.
- Lead with the insight, not the number. Numbers are evidence placed after the analytical claim.
- Be succinct — short sentences, no multi-clause walls of text.
- Abbreviate large numbers: K (thousands), M (millions), B (billions). No comma-separated integers in prose. Percentages at most 1 decimal.
- Use calendar years by default; quarter notation (Q1–Q4) only when intra-year precision matters. Never use H1/H2.
"""


def build_refine_prompt(
    section_content: str,
    data_context: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Assemble messages for section refinement chat."""
    cleaned_section = strip_source_markers(section_content)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": REFINE_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Current section text:\n"
                f"```\n{cleaned_section}\n```\n\n"
                "Underlying data context:\n"
                f"```json\n{json.dumps(data_context, default=str)}\n```"
            ),
        },
    ]

    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": message})
    return messages
