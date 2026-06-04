"""Unit tests for country-brief aggregated insights composition."""
from __future__ import annotations

from typing import Any

from backend.country_brief.composition import aggregated_insights as agg


def _series(values: list[float]) -> list[dict[str, object]]:
    return [{"date": f"201{idx}-01-01T00:00:00", "value": value} for idx, value in enumerate(values)]


def test_bundle_payload_prefers_annual_series_and_preserves_source_tags():
    payload = agg._bundle_kpi_payload(
        selected_kpi_ids=["1", "2"],
        kpi_results={
            "1": {
                "kpi_name": "GDP",
                "frequency": "Q",
                "series": [{"indicator": "GDP quarterly", "country": "SAU", "points": _series([1.0, 2.0])}],
                "series_annual": [{"indicator": "GDP annual", "country": "SAU", "points": _series([10.0, 12.0])}],
                "errors": [{"kpi_id": "1", "message": "warn"}],
            },
            "2": {
                "kpi_name": "Inflation",
                "frequency": "Q",
                "series": [{"indicator": "CPI", "country": "SAU", "points": _series([3.0, 2.5])}],
                "errors": [],
            },
        },
    )

    assert payload["aggregation_policy"] == "prefer_annual_then_native"
    assert payload["source_frequencies"]["1"] == "A"
    assert payload["source_frequencies"]["2"] == "Q"
    assert payload["errors"] == [{"kpi_id": "1", "message": "warn"}]

    indicators = [row["indicator"] for row in payload["series"]]
    assert "GDP annual [KPI 1]" in indicators
    assert "GDP quarterly [KPI 1]" not in indicators
    assert all("source_kpi_id" in row for row in payload["series"])
    assert any(row["source_kpi_id"] == "1" and row["source_frequency"] == "A" for row in payload["series"])


def test_extract_kpi_ids_prefers_structured_source_tag():
    selected = ["4", "9"]
    signal = {
        "source_kpi_id": "4",
        "description": "mentions KPI 9 in prose",
        "period_summary": "KPI 9 volatility",
    }
    assert agg._extract_kpi_ids_from_signal(signal, selected) == ["4"]


def _new_signal(
    sig_id: str,
    kpi_id: str,
    *,
    pct_change: float = 0.1,
    direction: str = "up",
) -> dict[str, Any]:
    """Flat-schema signal fixture for the new pipeline."""
    return {
        "id": sig_id,
        "signal_type": "long_term_trend",
        "kpi": f"KPI {kpi_id}",
        "kpi_id": kpi_id,
        "country": "SAU",
        "frequency": "A",
        "unit": "%",
        "period_start": "2019-01",
        "period_end": "2024-01",
        "period_length_months": 60,
        "start_value": 1.0,
        "end_value": 2.0,
        "abs_change": 1.0,
        "pct_change": pct_change,
        "direction": direction,
        "metrics": {},
    }


def test_run_for_country_light_path_skips_grouped_flow(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_signal_run_step(_payload, **kwargs):
        captured["use_llm_triage"] = kwargs.get("use_llm_triage")
        return {
            "raw_signals": [_new_signal("sig_1", "1"), _new_signal("sig_2", "2")],
            "selected_signals": [],
        }

    def fake_legacy_hyp(**_kwargs):
        captured["legacy_hyp_called"] = True
        return {"hypotheses": []}

    def fake_grouped_hyp(**_kwargs):
        captured["grouped_hyp_called"] = True
        return {"document": {}, "call_meta": None}

    def fake_planned_queries(**_kwargs):
        captured["planned_queries_called"] = True
        return {"events": [], "by_query": [], "call_meta": None}

    def fake_insights_run_step(**kwargs):
        captured.setdefault("insight_calls", 0)
        captured["insight_calls"] += 1
        captured["last_hypotheses"] = kwargs.get("hypotheses")
        return {"executive_summary": ["Macro conditions shifted across selected KPIs."]}

    monkeypatch.setattr(agg.signal_extractor, "run_step", fake_signal_run_step)
    monkeypatch.setattr(agg.hypotheses_generator, "run_step", fake_legacy_hyp)
    monkeypatch.setattr(agg.hypotheses_generator, "run_step_groups", fake_grouped_hyp)
    monkeypatch.setattr(agg.news_researcher, "run_planned_queries", fake_planned_queries)
    monkeypatch.setattr(agg.insights_generator, "run_step", fake_insights_run_step)

    interpretation, articles, prompt_bundle = agg.run_for_country(
        country="SAU",
        start_year=2019,
        end_year=2024,
        selected_kpi_ids=["1", "2"],
        kpi_results={
            "1": {"kpi_name": "GDP", "unit": "%", "series": [{"indicator": "GDP", "country": "SAU", "points": _series([1.0, 2.0])}]},
            "2": {"kpi_name": "Inflation", "unit": "%", "series": [{"indicator": "CPI", "country": "SAU", "points": _series([3.0, 2.5])}]},
        },
        deep_analysis=False,
    )

    assert captured.get("use_llm_triage") is False
    assert "legacy_hyp_called" not in captured
    assert "grouped_hyp_called" not in captured  # light path -> no grouped flow
    assert "planned_queries_called" not in captured
    assert captured["last_hypotheses"] == []
    assert interpretation["themes"]
    assert articles == []
    assert prompt_bundle is None
    assert "signal_event_links" in interpretation
    assert "planned_queries" in interpretation
    assert "news_by_query" in interpretation
    assert "hypothesis_document" in interpretation
    assert "news_query" not in interpretation


def test_run_for_country_deep_path_wires_grouped_flow(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_signal_run_step(_payload, **kwargs):
        # kpi_ids 3 and 2 both belong to the growth family in kpi_relationships.py
        # so build_groups will return a non-empty group set.
        return {
            "raw_signals": [
                _new_signal("sig_1", "3", pct_change=0.5),
                _new_signal("sig_2", "2", pct_change=0.4),
                _new_signal("sig_3", "3", pct_change=0.3),
            ],
            "selected_signals": [],
        }

    fake_document = {
        "country": "Saudi Arabia",
        "period": "2019-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "Growth weakness",
                "group_level_question": "?",
                "hypotheses": [
                    {
                        "hypothesis_id": "G1_H1",
                        "hypothesis_type": "external_shock",
                        "hypothesis": "h",
                        "mechanism": "m",
                        "explains_signals": ["sig_1"],
                        "does_not_explain": [],
                        "expected_evidence": ["e1"],
                        "contradictory_evidence": [],
                        "neutral_search_queries": ["query alpha"],
                        "search_priority": "high",
                        "brief_use_before_evidence": "do_not_use_as_claim",
                    },
                ],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }

    def fake_grouped_hyp(**kwargs):
        captured["grouped_hyp_kwargs"] = kwargs
        return {"document": fake_document, "call_meta": None}

    def fake_planned_queries(**kwargs):
        captured["planned_queries_kwargs"] = kwargs
        return {
            "events": [
                {
                    "id": "ev_1",
                    "title": "t",
                    "date": "2022-01-15",
                    "summary": "s",
                    "url": "https://r.com/a",
                    "actor": "A",
                    "action": "did",
                    "query_id": "q_001",
                    "hypothesis_id": "G1_H1",
                    "group_ids": ["family:growth"],
                }
            ],
            "by_query": [
                {
                    "query_id": "q_001",
                    "query": "query alpha",
                    "hypothesis_id": "G1_H1",
                    "group_ids": ["family:growth"],
                    "raw_count": 1,
                    "kept": 1,
                    "dropped_host": 0,
                    "dropped_missing_actor_or_action": 0,
                    "dropped_duplicate": 0,
                }
            ],
            "call_meta": None,
        }

    def fake_insights_run_step(**kwargs):
        captured.setdefault("insight_calls", 0)
        captured["insight_calls"] += 1
        captured["last_hypotheses"] = kwargs.get("hypotheses")
        captured["last_evidence"] = kwargs.get("evidence_items")
        return {"executive_summary": ["x"], "insights": [{"headline": "h", "analysis": "a"}]}

    def fake_eval_step(**_kwargs):
        return {"revision_instructions": []}

    monkeypatch.setattr(agg.signal_extractor, "run_step", fake_signal_run_step)
    monkeypatch.setattr(agg.hypotheses_generator, "run_step_groups", fake_grouped_hyp)
    monkeypatch.setattr(agg.news_researcher, "run_planned_queries", fake_planned_queries)
    monkeypatch.setattr(agg.insights_generator, "run_step", fake_insights_run_step)
    monkeypatch.setattr(agg.evaluator, "run_step", fake_eval_step)

    interpretation, articles, prompt_bundle = agg.run_for_country(
        country="SAU",
        start_year=2019,
        end_year=2024,
        selected_kpi_ids=["3", "2"],
        kpi_results={
            "3": {"kpi_name": "Real GDP Growth", "unit": "%", "series": [{"indicator": "GDP", "country": "SAU", "points": _series([1.0, 2.0])}]},
            "2": {"kpi_name": "Real GDP (oil/non-oil)", "unit": "%", "series": [{"indicator": "GDP split", "country": "SAU", "points": _series([3.0, 2.5])}]},
        },
        deep_analysis=True,
    )

    assert "grouped_hyp_kwargs" in captured
    grouped_kwargs = captured["grouped_hyp_kwargs"]
    assert grouped_kwargs["period"] == "2019-2024"
    assert "attached_groups" in grouped_kwargs

    assert "planned_queries_kwargs" in captured
    planned_kwargs = captured["planned_queries_kwargs"]
    assert planned_kwargs["country_name"] == "Saudi Arabia"
    assert planned_kwargs["start_year"] == 2019
    assert planned_kwargs["end_year"] == 2024
    assert isinstance(planned_kwargs["planned_queries"], list)

    legacy_hyps = captured.get("last_hypotheses") or []
    assert any(h["id"] == "G1_H1" for h in legacy_hyps)
    assert all(h.get("confidence") in {"high", "medium", "low"} for h in legacy_hyps)

    assert interpretation["planned_queries"] == planned_kwargs["planned_queries"]
    assert interpretation["news_by_query"]
    assert interpretation["hypothesis_document"] == fake_document
    assert "news_query" not in interpretation
    assert articles  # at least one article emitted from the single fake event
    assert prompt_bundle is not None


def test_filter_top_signals_per_kpi_applies_min_two_and_twenty_percent():
    raw = []
    # KPI A: 5 signals -> expect 2 (max(2, ceil(5*0.2))=2)
    for i in range(5):
        raw.append({"id": f"a{i}", "kpi_id": "A", "pct_change": float(i)})
    # KPI B: 15 signals -> expect 3 (ceil(15*0.2)=3)
    for i in range(15):
        raw.append({"id": f"b{i}", "kpi_id": "B", "pct_change": float(i)})
    # KPI C: 1 signal -> expect 1 (degenerate case)
    raw.append({"id": "c0", "kpi_id": "C", "pct_change": 100.0})

    selected = agg._filter_top_signals_per_kpi(raw, ["A", "B", "C"])
    by_kpi: dict[str, list[str]] = {}
    for sig in selected:
        by_kpi.setdefault(sig["kpi_id"], []).append(sig["id"])
    assert len(by_kpi["A"]) == 2
    assert by_kpi["A"] == ["a4", "a3"]  # top by abs(pct_change) desc
    assert len(by_kpi["B"]) == 3
    assert by_kpi["B"] == ["b14", "b13", "b12"]
    assert by_kpi["C"] == ["c0"]


def test_filter_top_signals_per_kpi_uses_abs_pct_change():
    """Negative pct_change should rank by absolute magnitude."""
    raw = [
        {"id": "a0", "kpi_id": "A", "pct_change": -10.0},
        {"id": "a1", "kpi_id": "A", "pct_change": 2.0},
        {"id": "a2", "kpi_id": "A", "pct_change": -1.0},
    ]
    selected = agg._filter_top_signals_per_kpi(raw, ["A"])
    ids = [sig["id"] for sig in selected]
    assert ids[0] == "a0"  # |-10| beats |+2| and |-1|


def test_flatten_hypotheses_for_legacy_skips_null_data_hypothesis():
    document = {
        "hypothesis_groups": [
            {
                "group_id": "g1",
                "group_theme": "",
                "group_level_question": "",
                "hypotheses": [
                    {
                        "hypothesis_id": "G1_H1",
                        "hypothesis_type": "external_shock",
                        "hypothesis": "Oil cuts may have lowered exports.",
                        "mechanism": "Lower production -> lower exports.",
                        "explains_signals": ["sig_1"],
                        "does_not_explain": [],
                        "expected_evidence": ["news of cut"],
                        "contradictory_evidence": [],
                        "neutral_search_queries": ["Saudi oil cuts"],
                        "search_priority": "high",
                        "brief_use_before_evidence": "do_not_use_as_claim",
                    },
                    {
                        "hypothesis_id": "G1_H_null",
                        "hypothesis_type": "null_data_hypothesis",
                        "hypothesis": "Could be statistical.",
                        "mechanism": "base effects",
                        "explains_signals": ["sig_1"],
                        "does_not_explain": [],
                        "expected_evidence": [],
                        "contradictory_evidence": [],
                        "neutral_search_queries": [],
                        "search_priority": "low",
                        "brief_use_before_evidence": "do_not_use_as_claim",
                    },
                ],
            }
        ]
    }
    flat = agg._flatten_hypotheses_for_legacy(document)
    assert [h["id"] for h in flat] == ["G1_H1"]
    assert flat[0]["title"].startswith("Oil cuts")
    assert flat[0]["causal_story"] == "Lower production -> lower exports."
    assert flat[0]["potential_effects"] == ["news of cut"]
    assert flat[0]["confidence"] == "high"


def test_flatten_hypotheses_for_legacy_handles_empty_or_invalid_document():
    assert agg._flatten_hypotheses_for_legacy({}) == []
    assert agg._flatten_hypotheses_for_legacy({"hypothesis_groups": []}) == []
    assert agg._flatten_hypotheses_for_legacy({"hypothesis_groups": None}) == []

