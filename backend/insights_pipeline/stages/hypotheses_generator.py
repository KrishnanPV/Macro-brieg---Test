"""Hypothesis generation step for insights workflow.

Two entry points live here:

- ``run_step(...)`` — legacy per-KPI hypothesis generation used by the
  dashboard pipeline. Untouched.
- ``run_step_groups(...)`` — per-signal-group hypothesis generation used by
  the new flow. Consumes the output of
  ``signal_graph.attach_signals(build_groups(signals), signals)`` and emits a
  strict, schema-validated document of grouped hypotheses, cross-group
  hypotheses, and a search-plan seed.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from backend.insights_pipeline.stages.common import (
    REASONING_MODEL,
    call_json_model,
    get_kpi_context,
    load_prompt,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locked controlled vocabularies for the group-based contract
# ---------------------------------------------------------------------------

HYPOTHESIS_TYPES: tuple[str, ...] = (
    "external_shock",
    "commodity_price",
    "sector_policy",
    "fiscal_policy",
    "monetary_policy",
    "domestic_demand",
    "external_demand",
    "labor_market",
    "investment_cycle",
    "demographics",
    "base_effect",
    "data_revision_or_measurement",
    "one_off_event",
    "structural_trend",
    "null_data_hypothesis",
)

SEARCH_PRIORITIES: tuple[str, ...] = ("high", "medium", "low")

_BRIEF_USE_LITERAL: str = "do_not_use_as_claim"
_STANDARD_WARNING: str = (
    "Hypotheses are unverified and should not be used as causal claims "
    "until evidence is retrieved."
)


# ---------------------------------------------------------------------------
# Locked JSON schema for OpenAI structured outputs (strict mode)
# ---------------------------------------------------------------------------

_MAX_EVIDENCE_ITEMS: int = 3
_MAX_NEUTRAL_QUERIES: int = 3


def _hypothesis_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "hypothesis_id",
            "hypothesis_type",
            "hypothesis",
            "mechanism",
            "explains_signals",
            "does_not_explain",
            "expected_evidence",
            "neutral_search_queries",
            "search_priority",
            "brief_use_before_evidence",
        ],
        "properties": {
            "hypothesis_id": {"type": "string"},
            "hypothesis_type": {"type": "string", "enum": list(HYPOTHESIS_TYPES)},
            "hypothesis": {"type": "string"},
            "mechanism": {"type": "string"},
            "explains_signals": {"type": "array", "items": {"type": "string"}},
            "does_not_explain": {"type": "array", "items": {"type": "string"}},
            "expected_evidence": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": _MAX_EVIDENCE_ITEMS,
            },
            "neutral_search_queries": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": _MAX_NEUTRAL_QUERIES,
            },
            "search_priority": {"type": "string", "enum": list(SEARCH_PRIORITIES)},
            "brief_use_before_evidence": {
                "type": "string",
                "enum": [_BRIEF_USE_LITERAL],
            },
        },
    }


def _build_output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "country",
            "period",
            "hypothesis_groups",
            "cross_group_hypotheses",
            "search_plan_seed",
            "warnings",
        ],
        "properties": {
            "country": {"type": "string"},
            "period": {"type": "string"},
            "hypothesis_groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "group_id",
                        "group_theme",
                        "group_level_question",
                        "hypotheses",
                    ],
                    "properties": {
                        "group_id": {"type": "string"},
                        "group_theme": {"type": "string"},
                        "group_level_question": {"type": "string"},
                        "hypotheses": {
                            "type": "array",
                            "items": _hypothesis_object_schema(),
                        },
                    },
                },
            },
            "cross_group_hypotheses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "hypothesis",
                        "related_groups",
                        "search_once",
                        "preferred_search_query",
                    ],
                    "properties": {
                        "hypothesis": {"type": "string"},
                        "related_groups": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "search_once": {"type": "boolean"},
                        "preferred_search_query": {"type": "string"},
                    },
                },
            },
            "search_plan_seed": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "highest_priority_questions",
                    "queries_to_run_first",
                    "queries_to_skip_unless_needed",
                ],
                "properties": {
                    "highest_priority_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "queries_to_run_first": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "queries_to_skip_unless_needed": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
    }


HYPOTHESES_OUTPUT_SCHEMA: dict[str, Any] = _build_output_schema()


# ---------------------------------------------------------------------------
# Legacy per-KPI entry point (unchanged behaviour)
# ---------------------------------------------------------------------------

def run_step(
    *,
    country: str,
    kpi_id: str,
    kpi_name: str,
    start_year: int,
    end_year: int,
    selected_signals: list[dict[str, Any]],
    reasoning_model: str = REASONING_MODEL,
    kpi_context_override: str | None = None,
) -> dict[str, Any]:
    """Generate broad causal hypotheses for the selected KPI signals."""
    system_base = load_prompt("system_base.md")
    per_kpi_prompt = load_prompt("per_kpi_context.md")
    kpi_context = (
        kpi_context_override
        if kpi_context_override is not None
        else get_kpi_context(kpi_id)
    )
    system_prompt = (
        "You are a macro hypothesis generator.\n"
        "Given KPI signal evidence, generate broad but testable causal hypotheses.\n"
        "Return JSON with key `hypotheses` where each item has: "
        "`id`, `title`, `causal_story`, `potential_effects`, `confidence`."
    )
    if system_base:
        system_prompt = f"{system_prompt}\n\n{system_base}"
    if per_kpi_prompt:
        system_prompt = f"{system_prompt}\n\n{per_kpi_prompt}"

    user_prompt = (
        f"Country: {country}\n"
        f"KPI: {kpi_name} ({kpi_id})\n"
        f"Window: {start_year}-{end_year}\n\n"
        f"KPI context:\n{kpi_context}\n\n"
        "Selected signals:\n"
        f"{json.dumps(selected_signals, indent=2, default=str)}\n\n"
        "Generate 3-6 hypotheses. Keep them specific enough for evidence checks."
    )
    parsed, call_meta = call_json_model(
        model=reasoning_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.hypotheses_generator",
        include_call_meta=True,
    )
    hypotheses = parsed.get("hypotheses", [])
    if not hypotheses:
        hypotheses = [{
            "id": "hyp_1",
            "title": "Insufficient structured hypotheses from model",
            "causal_story": (
                "Model did not return structured hypotheses. Manual review needed."
            ),
            "potential_effects": [],
            "confidence": "low",
        }]
    return {"hypotheses": hypotheses, "call_meta": call_meta}


# ---------------------------------------------------------------------------
# Group-based entry point: run_step_groups
# ---------------------------------------------------------------------------

def _signal_ids_for_group(attached_group: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for signal in attached_group.get("signals", []) or []:
        sig_id = str(signal.get("id") or "")
        if sig_id:
            out.append(sig_id)
    return out


def _make_null_hypothesis(group_id: str, signal_ids: list[str]) -> dict[str, Any]:
    return {
        "hypothesis_id": f"{group_id}_H_null",
        "hypothesis_type": "null_data_hypothesis",
        "hypothesis": (
            "The movement may be partly mechanical, statistical, or base-effect "
            "driven rather than caused by a new macro event."
        ),
        "mechanism": (
            "Carry-over, prior-period base, denominator effects, methodology "
            "revisions, or measurement noise can move a series without a new "
            "underlying macro cause."
        ),
        "explains_signals": list(signal_ids),
        "does_not_explain": [],
        "expected_evidence": [
            "release notes flagging methodology change",
            "prior-period base unusually high or low",
            "revisions to historical data",
        ],
        "neutral_search_queries": [],
        "search_priority": "low",
        "brief_use_before_evidence": _BRIEF_USE_LITERAL,
    }


def _validate_hypothesis(
    hyp: dict[str, Any],
    *,
    group_id: str,
    valid_signal_ids: set[str],
) -> dict[str, Any]:
    """Return a cleaned hypothesis dict; raise ValueError on type-whitelist violation.

    - hypothesis_type must be in HYPOTHESIS_TYPES (raise on violation).
    - search_priority defaulted to "low" if outside SEARCH_PRIORITIES.
    - brief_use_before_evidence forced to the locked literal.
    - explains_signals / does_not_explain filtered to ids present in the group.
    """
    hyp_type = str(hyp.get("hypothesis_type") or "")
    if hyp_type not in HYPOTHESIS_TYPES:
        raise ValueError(
            f"hypothesis_type={hyp_type!r} in group {group_id!r} is not in "
            f"HYPOTHESIS_TYPES."
        )

    priority = str(hyp.get("search_priority") or "")
    if priority not in SEARCH_PRIORITIES:
        priority = "low"

    explains = [
        str(sid)
        for sid in (hyp.get("explains_signals") or [])
        if str(sid) in valid_signal_ids
    ]
    does_not = [
        str(sid)
        for sid in (hyp.get("does_not_explain") or [])
        if str(sid) in valid_signal_ids
    ]

    def _str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    return {
        "hypothesis_id": str(hyp.get("hypothesis_id") or ""),
        "hypothesis_type": hyp_type,
        "hypothesis": str(hyp.get("hypothesis") or ""),
        "mechanism": str(hyp.get("mechanism") or ""),
        "explains_signals": explains,
        "does_not_explain": does_not,
        "expected_evidence": _str_list(hyp.get("expected_evidence"))[:_MAX_EVIDENCE_ITEMS],
        "neutral_search_queries": _str_list(hyp.get("neutral_search_queries"))[
            :_MAX_NEUTRAL_QUERIES
        ],
        "search_priority": priority,
        "brief_use_before_evidence": _BRIEF_USE_LITERAL,
    }


def _renumber_hypothesis_ids(
    hypotheses: list[dict[str, Any]],
    group_id: str,
) -> list[dict[str, Any]]:
    """Reassign stable {group_id}_H{idx} ids when collisions exist or ids are blank.

    The null hypothesis keeps its ``{group_id}_H_null`` id and is never
    renumbered.
    """
    seen: set[str] = set()
    has_collision = False
    for hyp in hypotheses:
        hid = hyp.get("hypothesis_id") or ""
        if not hid or hid in seen:
            has_collision = True
            break
        seen.add(hid)
    if not has_collision:
        return hypotheses
    renumbered: list[dict[str, Any]] = []
    counter = 0
    for hyp in hypotheses:
        if hyp.get("hypothesis_type") == "null_data_hypothesis":
            renumbered.append(hyp)
            continue
        counter += 1
        renumbered.append({**hyp, "hypothesis_id": f"{group_id}_H{counter}"})
    return renumbered


def _post_validate_document(
    document: dict[str, Any],
    *,
    country: str,
    period: str,
    attached_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    """Enforce invariants the LLM cannot be trusted to keep deterministic."""
    group_index: dict[str, dict[str, Any]] = {
        str(g["group_id"]): g for g in attached_groups
    }
    valid_group_ids: set[str] = set(group_index.keys())

    raw_groups = document.get("hypothesis_groups") or []
    emitted_group_ids: set[str] = set()
    out_groups: list[dict[str, Any]] = []

    for raw_group in raw_groups:
        group_id = str(raw_group.get("group_id") or "")
        if group_id not in valid_group_ids:
            continue
        emitted_group_ids.add(group_id)
        valid_signal_ids = set(_signal_ids_for_group(group_index[group_id]))

        validated_hyps: list[dict[str, Any]] = []
        for hyp in raw_group.get("hypotheses") or []:
            validated_hyps.append(
                _validate_hypothesis(
                    hyp,
                    group_id=group_id,
                    valid_signal_ids=valid_signal_ids,
                )
            )
        has_null = any(
            h["hypothesis_type"] == "null_data_hypothesis" for h in validated_hyps
        )
        if not has_null:
            validated_hyps.append(
                _make_null_hypothesis(
                    group_id=group_id,
                    signal_ids=sorted(valid_signal_ids),
                )
            )

        validated_hyps = _renumber_hypothesis_ids(validated_hyps, group_id)

        out_groups.append({
            "group_id": group_id,
            "group_theme": str(raw_group.get("group_theme") or ""),
            "group_level_question": str(
                raw_group.get("group_level_question")
                or "What explains this group of signals?"
            ),
            "hypotheses": validated_hyps,
        })

    for group_id in valid_group_ids - emitted_group_ids:
        attached = group_index[group_id]
        signal_ids = _signal_ids_for_group(attached)
        out_groups.append({
            "group_id": group_id,
            "group_theme": str(attached.get("label") or ""),
            "group_level_question": "What explains this group of signals?",
            "hypotheses": [
                _make_null_hypothesis(group_id=group_id, signal_ids=signal_ids),
            ],
        })

    out_cross: list[dict[str, Any]] = []
    for cross in document.get("cross_group_hypotheses") or []:
        related = [
            str(gid)
            for gid in (cross.get("related_groups") or [])
            if str(gid) in valid_group_ids
        ]
        if len(related) < 2:
            continue
        out_cross.append({
            "hypothesis": str(cross.get("hypothesis") or ""),
            "related_groups": related,
            "search_once": bool(cross.get("search_once", True)),
            "preferred_search_query": str(cross.get("preferred_search_query") or ""),
        })

    raw_seed = document.get("search_plan_seed") or {}

    def _seed_list(key: str) -> list[str]:
        items = raw_seed.get(key) or []
        if not isinstance(items, list):
            return []
        return [str(item) for item in items if str(item).strip()]

    search_plan_seed = {
        "highest_priority_questions": _seed_list("highest_priority_questions"),
        "queries_to_run_first": _seed_list("queries_to_run_first"),
        "queries_to_skip_unless_needed": _seed_list("queries_to_skip_unless_needed"),
    }

    raw_warnings = document.get("warnings") or []
    warnings = [str(w) for w in raw_warnings if str(w).strip()]
    if _STANDARD_WARNING not in warnings:
        warnings.append(_STANDARD_WARNING)

    return {
        "country": str(document.get("country") or country),
        "period": str(document.get("period") or period),
        "hypothesis_groups": out_groups,
        "cross_group_hypotheses": out_cross,
        "search_plan_seed": search_plan_seed,
        "warnings": warnings,
    }


def _trim_signal_for_prompt(sig: dict[str, Any]) -> dict[str, Any]:
    """Project a Signal into the minimal payload the hypothesis LLM needs.

    Drops fields that are noise for hypothesis generation:
    - country (same for every signal in the call)
    - frequency, unit (not used for direction/magnitude reasoning)
    - start_value, end_value, abs_change (pct_change captures size cleanly)
    - period_length_months (derivable from period)
    - metrics (per-type numerics like z_score / pivot_date; consumed downstream
      by signal_event_linker.link from the raw selected_signals list, NOT by
      the hypothesis LLM)

    Per-signal token cost: ~200 -> ~50. With ~210 signals across ~7 groups
    this is the single biggest input-cost lever for this stage.
    """
    try:
        pct_change = round(float(sig.get("pct_change") or 0.0), 3)
    except (TypeError, ValueError):
        pct_change = 0.0
    return {
        "id": str(sig.get("id") or ""),
        "signal_type": str(sig.get("signal_type") or ""),
        "kpi": str(sig.get("kpi") or ""),
        "kpi_id": str(sig.get("kpi_id") or ""),
        "direction": str(sig.get("direction") or ""),
        "pct_change": pct_change,
        "period": f"{sig.get('period_start') or ''}..{sig.get('period_end') or ''}",
    }


def _summarize_attached_group_for_prompt(group: dict[str, Any]) -> dict[str, Any]:
    """Trim each attached group into the minimal JSON payload sent to the LLM.

    Each embedded signal is projected through ``_trim_signal_for_prompt`` so
    the prompt only carries fields the hypothesis LLM actually reasons about.
    """
    return {
        "group_id": str(group.get("group_id") or ""),
        "group_type": str(group.get("group_type") or ""),
        "label": str(group.get("label") or ""),
        "net_direction": str(group.get("net_direction") or ""),
        "size": int(group.get("size") or 0),
        "members": [
            {"kpi_id": str(m.get("kpi_id") or ""), "role": str(m.get("role") or "")}
            for m in group.get("members") or []
        ],
        "signals": [
            _trim_signal_for_prompt(s) for s in (group.get("signals") or [])
        ],
    }


def run_step_groups(
    *,
    country: str,
    period: str,
    archetype_tags: list[str] | None,
    attached_groups: list[dict[str, Any]],
    reasoning_model: str = REASONING_MODEL,
) -> dict[str, Any]:
    """Generate per-group hypotheses + cross-group dedup + search-plan seed.

    Consumes the output of
    ``signal_graph.attach_signals(build_groups(signals), signals)``. Returns
    ``{"document": <validated>, "call_meta": <usage>}``.
    """
    system_base = load_prompt("system_base.md")
    hyp_prompt = load_prompt("hypotheses_groups.md")

    system_prompt = hyp_prompt or (
        "You are a macroeconomic analyst generating research hypotheses from "
        "grouped data signals. Output valid JSON only."
    )
    if system_base:
        system_prompt = f"{system_prompt}\n\n{system_base}"

    trimmed_groups = [
        _summarize_attached_group_for_prompt(g) for g in attached_groups or []
    ]
    tags = list(archetype_tags or [])

    user_prompt = (
        f"Country: {country}\n"
        f"Period: {period}\n"
        f"Archetype tags: {json.dumps(tags)}\n\n"
        "Signal groups (each with embedded signal items):\n"
        f"{json.dumps(trimmed_groups, indent=2, default=str)}\n\n"
        "Generate 3-6 hypotheses per group. Prefer group-level explanations. "
        "Include cross_group_hypotheses for any hypothesis that spans multiple "
        "groups. Populate search_plan_seed."
    )

    parsed, call_meta = call_json_model(
        model=reasoning_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.hypotheses_generator.groups",
        include_call_meta=True,
        response_schema=HYPOTHESES_OUTPUT_SCHEMA,
        response_schema_name="hypotheses_document",
        # 6000 (original): routinely truncated -> JSON parse failure -> empty
        #                  hypothesis document -> empty news plan -> degraded brief.
        # 12000 (first bump): worked for SAU (out=11,514) but UAE saturated at
        #                     12,000 exactly (finish_reason=length). The
        #                     QuantumBlack OpenAI gateway does NOT expose
        #                     completion_tokens_details.reasoning_tokens, so
        #                     reasoning and visible JSON share this single cap
        #                     opaquely. 12,000 is right at the threshold for an
        #                     8-group brief with 3-6 hypotheses each.
        # 16000 (current): ~33% headroom above the observed borderline run
        #                  (SAU at 11,514) and well above the saturated run
        #                  (ARE at 12,000). Worst-case cost delta is ~$0.06 at
        #                  gpt-5.4 output pricing.
        max_completion_tokens=16000,
    )

    if isinstance(parsed, dict) and parsed.get("_truncated"):
        log.error(
            "insights_pipeline.hypotheses_generator.groups response truncated: "
            "finish_reason=%s reasoning_tokens=%s visible_tokens=%s -- "
            "raise max_completion_tokens or lower reasoning_effort. "
            "Hypothesis document will degrade to null hypotheses only and "
            "deep-mode news flow will be empty.",
            parsed.get("_finish_reason"),
            call_meta.get("reasoning_tokens"),
            call_meta.get("visible_tokens"),
        )

    if not isinstance(parsed, dict) or "raw_text" in parsed:
        parsed = {}
    else:
        # Strip internal flags so they never leak into the post-validated document.
        parsed = {k: v for k, v in parsed.items() if not k.startswith("_")}

    document = _post_validate_document(
        parsed,
        country=country,
        period=period,
        attached_groups=attached_groups or [],
    )
    return {"document": document, "call_meta": call_meta}
