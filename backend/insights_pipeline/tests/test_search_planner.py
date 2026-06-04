"""Tests for search_planner.plan_searches and _make_planned_query."""
from __future__ import annotations

from typing import Any

import pytest

from backend.insights_pipeline.stages.search_planner import (
    DEFAULT_BUDGET,
    MAX_BUDGET,
    MIN_BUDGET,
    PLANNED_QUERY_KEYS,
    QUERY_SOURCES,
    _make_planned_query,
    plan_searches,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _hyp(
    *,
    hyp_id: str,
    htype: str = "external_shock",
    queries: list[str] | None = None,
    priority: str = "high",
) -> dict[str, Any]:
    return {
        "hypothesis_id": hyp_id,
        "hypothesis_type": htype,
        "hypothesis": "h",
        "mechanism": "m",
        "explains_signals": [],
        "does_not_explain": [],
        "expected_evidence": [],
        "contradictory_evidence": [],
        "neutral_search_queries": list(queries or []),
        "search_priority": priority,
        "brief_use_before_evidence": "do_not_use_as_claim",
    }


def _doc(
    *,
    groups: list[dict[str, Any]] | None = None,
    cross: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": list(groups or []),
        "cross_group_hypotheses": list(cross or []),
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }


def _group(group_id: str, hyps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "group_theme": "",
        "group_level_question": "",
        "hypotheses": list(hyps),
    }


# ---------------------------------------------------------------------------
# Shape enforcement
# ---------------------------------------------------------------------------

def test_every_planned_query_has_exact_keys_in_order():
    doc = _doc(
        groups=[
            _group("family:growth", [_hyp(hyp_id="G1_H1", queries=["q1"])]),
            _group("family:fiscal", [_hyp(hyp_id="G2_H1", queries=["q2"])]),
        ],
    )
    for planned in plan_searches(doc):
        assert tuple(planned.keys()) == PLANNED_QUERY_KEYS


def test_make_planned_query_rejects_unknown_source():
    with pytest.raises(ValueError):
        _make_planned_query(
            query_id="q_001",
            query="q",
            source="other",
            hypothesis_id="",
            group_ids=["family:growth"],
            priority="high",
            search_priority_rank=0,
        )


def test_make_planned_query_rejects_unknown_priority():
    with pytest.raises(ValueError):
        _make_planned_query(
            query_id="q_001",
            query="q",
            source="hypothesis",
            hypothesis_id="G1_H1",
            group_ids=["family:growth"],
            priority="critical",
            search_priority_rank=0,
        )


# ---------------------------------------------------------------------------
# Budget clamping
# ---------------------------------------------------------------------------

def test_budget_below_min_is_clamped_up():
    queries = ["q1", "q2", "q3", "q4", "q5", "q6", "q7", "q8"]
    doc = _doc(
        groups=[_group("g1", [_hyp(hyp_id=f"H{i}", queries=[q]) for i, q in enumerate(queries)])],
    )
    result = plan_searches(doc, budget=3)
    assert len(result) == MIN_BUDGET


def test_budget_above_max_is_clamped_down():
    queries = [f"q{i}" for i in range(20)]
    doc = _doc(
        groups=[_group("g1", [_hyp(hyp_id=f"H{i}", queries=[q]) for i, q in enumerate(queries)])],
    )
    result = plan_searches(doc, budget=99)
    assert len(result) == MAX_BUDGET


def test_default_budget_is_within_range():
    queries = [f"q{i}" for i in range(20)]
    doc = _doc(
        groups=[_group("g1", [_hyp(hyp_id=f"H{i}", queries=[q]) for i, q in enumerate(queries)])],
    )
    result = plan_searches(doc)
    assert len(result) == DEFAULT_BUDGET


def test_empty_document_returns_empty_list():
    assert plan_searches(_doc()) == []
    assert plan_searches({}) == []


# ---------------------------------------------------------------------------
# Cross-group precedence and source tagging
# ---------------------------------------------------------------------------

def test_cross_group_queries_appear_before_hypothesis_queries():
    doc = _doc(
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["per_group_q1"])]),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["per_group_q2"])]),
        ],
        cross=[
            {
                "hypothesis": "spans groups",
                "related_groups": ["g1", "g2"],
                "search_once": True,
                "preferred_search_query": "cross_q",
            }
        ],
    )
    result = plan_searches(doc)
    assert result[0]["source"] == "cross_group"
    assert result[0]["query"] == "cross_q"
    assert result[0]["group_ids"] == ["g1", "g2"]


def test_cross_group_source_is_in_locked_enum():
    doc = _doc(
        cross=[
            {
                "hypothesis": "x",
                "related_groups": ["g1", "g2"],
                "search_once": True,
                "preferred_search_query": "qX",
            }
        ],
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["qA"])]),
        ],
    )
    for planned in plan_searches(doc):
        assert planned["source"] in QUERY_SOURCES


def test_cross_group_without_related_groups_is_skipped():
    doc = _doc(
        cross=[
            {
                "hypothesis": "no targets",
                "related_groups": [],
                "search_once": True,
                "preferred_search_query": "ghost",
            }
        ],
        groups=[_group("g1", [_hyp(hyp_id="G1_H1", queries=["real"])])],
    )
    result = plan_searches(doc)
    assert all(planned["query"] != "ghost" for planned in result)


# ---------------------------------------------------------------------------
# Round-robin spread across groups
# ---------------------------------------------------------------------------

def test_round_robin_spreads_queries_evenly_across_groups():
    doc = _doc(
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["a1", "a2", "a3"])]),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["b1", "b2", "b3"])]),
        ],
    )
    result = plan_searches(doc, budget=6)
    g1_count = sum(1 for p in result if p["group_ids"] == ["g1"])
    g2_count = sum(1 for p in result if p["group_ids"] == ["g2"])
    assert g1_count == 3
    assert g2_count == 3


def test_round_robin_no_group_dominates_when_budget_is_small():
    doc = _doc(
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["a1", "a2", "a3"])]),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["b1"])]),
        ],
    )
    result = plan_searches(doc, budget=6)
    g1_first = next(p for p in result if p["group_ids"] == ["g1"])
    g2_first = next(p for p in result if p["group_ids"] == ["g2"])
    assert result.index(g1_first) < result.index(g2_first) or result.index(g2_first) == 1
    g1_count = sum(1 for p in result if p["group_ids"] == ["g1"])
    g2_count = sum(1 for p in result if p["group_ids"] == ["g2"])
    assert g1_count == 3
    assert g2_count == 1


# ---------------------------------------------------------------------------
# Priority ordering within a group
# ---------------------------------------------------------------------------

def test_high_priority_query_picked_before_low_in_same_group():
    doc = _doc(
        groups=[
            _group(
                "g1",
                [
                    _hyp(hyp_id="G1_low", queries=["low_q"], priority="low"),
                    _hyp(hyp_id="G1_high", queries=["high_q"], priority="high"),
                    _hyp(hyp_id="G1_med", queries=["med_q"], priority="medium"),
                ],
            ),
        ],
    )
    result = plan_searches(doc, budget=MIN_BUDGET)
    g1_results = [p for p in result if p["group_ids"] == ["g1"]]
    assert g1_results[0]["query"] == "high_q"
    assert g1_results[1]["query"] == "med_q"
    assert g1_results[2]["query"] == "low_q"


# ---------------------------------------------------------------------------
# null_data_hypothesis skip
# ---------------------------------------------------------------------------

def test_null_data_hypothesis_is_never_picked():
    doc = _doc(
        groups=[
            _group(
                "g1",
                [
                    _hyp(
                        hyp_id="G1_null",
                        htype="null_data_hypothesis",
                        queries=["should_never_appear"],
                    ),
                ],
            ),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["real_q"])]),
        ],
    )
    result = plan_searches(doc)
    assert all(planned["query"] != "should_never_appear" for planned in result)


# ---------------------------------------------------------------------------
# Case-insensitive dedup
# ---------------------------------------------------------------------------

def test_case_insensitive_dedup_across_hypotheses():
    doc = _doc(
        groups=[
            _group(
                "g1",
                [
                    _hyp(hyp_id="G1_H1", queries=["Saudi Arabia OPEC quota"]),
                    _hyp(hyp_id="G1_H2", queries=["saudi arabia opec quota"]),
                    _hyp(hyp_id="G1_H3", queries=["unique q"]),
                ],
            ),
        ],
    )
    result = plan_searches(doc)
    g1_results = [p for p in result if p["group_ids"] == ["g1"]]
    assert len(g1_results) == 2
    assert {p["query"].lower() for p in g1_results} == {
        "saudi arabia opec quota",
        "unique q",
    }


def test_case_insensitive_dedup_between_cross_and_hypothesis():
    doc = _doc(
        cross=[
            {
                "hypothesis": "x",
                "related_groups": ["g1", "g2"],
                "search_once": True,
                "preferred_search_query": "SHARED Q",
            },
        ],
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["shared q"])]),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["g2 only"])]),
        ],
    )
    result = plan_searches(doc)
    assert sum(1 for p in result if p["query"].lower() == "shared q") == 1


def test_query_ids_are_sequential_and_unique():
    doc = _doc(
        groups=[
            _group("g1", [_hyp(hyp_id="G1_H1", queries=["q1", "q2", "q3"])]),
            _group("g2", [_hyp(hyp_id="G2_H1", queries=["q4", "q5"])]),
        ],
    )
    result = plan_searches(doc)
    ids = [p["query_id"] for p in result]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
