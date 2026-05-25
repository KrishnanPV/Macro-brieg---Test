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


def test_run_for_country_skips_hypotheses_in_revamped_flow(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_signal_run_step(_payload, **kwargs):
        captured["use_llm_triage"] = kwargs.get("use_llm_triage")
        return {
            "raw_signals": [
                {"id": "sig_1", "kpi": "GDP", "source_kpi_id": "1", "pattern": "rising", "materiality_score": 50.0},
                {"id": "sig_2", "kpi": "CPI", "source_kpi_id": "2", "pattern": "falling", "materiality_score": 30.0},
            ],
            "selected_signals": [],
        }

    def fake_hyp_run_step(**_kwargs):
        captured["hyp_called"] = True
        return {"hypotheses": []}

    def fake_insights_run_step(**kwargs):
        captured.setdefault("insight_calls", 0)
        captured["insight_calls"] += 1
        captured["last_hypotheses"] = kwargs.get("hypotheses")
        return {"executive_summary": ["Macro conditions shifted across selected KPIs."]}

    monkeypatch.setattr(agg.signal_extractor, "run_step", fake_signal_run_step)
    monkeypatch.setattr(agg.hypotheses_generator, "run_step", fake_hyp_run_step)
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
    assert "hyp_called" not in captured  # hypotheses generator must not be invoked
    assert captured["last_hypotheses"] == []
    assert interpretation["themes"]
    assert articles == []
    assert prompt_bundle is None
    assert "signal_event_links" in interpretation
    assert "news_query" in interpretation


def test_filter_top_signals_per_kpi_applies_min_two_and_twenty_percent():
    raw = []
    # KPI A: 5 signals -> expect 2 (max(2, ceil(5*0.2))=2)
    for i in range(5):
        raw.append({"id": f"a{i}", "source_kpi_id": "A", "materiality_score": float(i)})
    # KPI B: 15 signals -> expect 3 (ceil(15*0.2)=3)
    for i in range(15):
        raw.append({"id": f"b{i}", "source_kpi_id": "B", "materiality_score": float(i)})
    # KPI C: 1 signal -> expect 1 (degenerate case)
    raw.append({"id": "c0", "source_kpi_id": "C", "materiality_score": 100.0})

    selected = agg._filter_top_signals_per_kpi(raw, ["A", "B", "C"])
    by_kpi: dict[str, list[str]] = {}
    for sig in selected:
        by_kpi.setdefault(sig["source_kpi_id"], []).append(sig["id"])
    assert len(by_kpi["A"]) == 2
    assert by_kpi["A"] == ["a4", "a3"]  # top by materiality_score desc
    assert len(by_kpi["B"]) == 3
    assert by_kpi["B"] == ["b14", "b13", "b12"]
    assert by_kpi["C"] == ["c0"]

