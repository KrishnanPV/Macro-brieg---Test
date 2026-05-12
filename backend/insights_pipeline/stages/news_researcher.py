"""News corroboration step for insights workflow."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from typing import Any

from backend.insights_pipeline.stages.common import NEWS_MODEL, call_json_model

MAX_PARALLEL_SONAR_CALLS = 4


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

