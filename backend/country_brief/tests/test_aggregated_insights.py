"""Unit tests for country-brief aggregated insights composition."""
from __future__ import annotations

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


def test_run_for_country_passes_bundle_context_to_hypotheses(monkeypatch):
    captured: dict[str, str] = {}

    def fake_signal_run_step(_payload, *, reasoning_model):
        _ = reasoning_model
        return {
            "raw_signals": [
                {"id": "sig_1", "kpi": "GDP", "source_kpi_id": "1", "pattern": "rising"},
                {"id": "sig_2", "kpi": "CPI", "source_kpi_id": "2", "pattern": "falling"},
            ],
            "selected_signals": [
                {"id": "sig_1", "kpi": "GDP", "source_kpi_id": "1", "pattern": "rising"},
                {"id": "sig_2", "kpi": "CPI", "source_kpi_id": "2", "pattern": "falling"},
            ],
        }

    def fake_hyp_run_step(**kwargs):
        captured["context"] = kwargs.get("kpi_context_override", "")
        return {
            "hypotheses": [
                {"id": "h1", "title": "Growth channel", "causal_story": "Demand improved", "potential_effects": []},
            ]
        }

    def fake_insights_run_step(**_kwargs):
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

    assert "KPI 1: GDP" in captured["context"]
    assert "KPI 2: Inflation" in captured["context"]
    assert interpretation["themes"]
    assert articles == []
    assert prompt_bundle is None

