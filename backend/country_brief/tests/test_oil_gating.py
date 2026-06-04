"""Tests for data-driven oil gating (1A title + 3A overlay).

See docs/decisions.md (2026-06-04). The single signal `_has_oil_split` decides
whether a country is treated as an oil economy for display purposes.
"""
from __future__ import annotations

from backend.country_brief import pipeline


def _series(indicator: str, values: list[float | None]) -> dict:
    return {
        "indicator": indicator,
        "points": [{"date": f"20{20 + i}-01-01", "value": v} for i, v in enumerate(values)],
    }


def test_has_oil_split_true_from_kpi_12():
    results = [
        {
            "kpi_id": "12",
            "series": [
                _series("GDP real, annual growth", [3.1, 3.4]),
                _series("GDP, oil, real, LCU", [100.0, 102.0]),
                _series("GDP, non-oil, real, LCU", [200.0, 210.0]),
            ],
        }
    ]
    assert pipeline._has_oil_split(results) is True


def test_has_oil_split_true_from_kpi_2_annual_series():
    results = [
        {
            "kpi_id": "2",
            "series": [],
            "series_annual": [_series("GDP, non-oil, real, LCU", [200.0, 210.0])],
        }
    ]
    assert pipeline._has_oil_split(results) is True


def test_has_oil_split_false_when_only_total_growth():
    results = [
        {
            "kpi_id": "12",
            "series": [_series("GDP real, annual growth", [3.1, 3.4])],
        }
    ]
    assert pipeline._has_oil_split(results) is False


def test_has_oil_split_false_when_split_points_are_null():
    results = [
        {
            "kpi_id": "12",
            "series": [
                _series("GDP real, annual growth", [3.1, 3.4]),
                _series("GDP, oil, real, LCU", [None, None]),
                _series("GDP, non-oil, real, LCU", [None, None]),
            ],
        }
    ]
    assert pipeline._has_oil_split(results) is False


def test_has_oil_split_ignores_unrelated_kpis():
    results = [
        {
            "kpi_id": "13",
            "series": [_series("Exports, goods & services, nominal, LCU", [50.0])],
        }
    ]
    assert pipeline._has_oil_split(results) is False
