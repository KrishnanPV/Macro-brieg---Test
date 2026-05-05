"""Tests for deterministic lab signal extraction."""
from __future__ import annotations

from backend.insights_pipeline.stages import signal_extractor


def _series(indicator: str, values: list[float]) -> dict:
    points = []
    for idx, value in enumerate(values):
        points.append(
            {
                "date": f"201{idx}-01-01T00:00:00",
                "value": value,
            }
        )
    return {
        "country": "SAU",
        "indicator": indicator,
        "points": points,
    }


def test_signal_profile_splits_long_window_into_phases():
    payload = {
        "series": [
            _series("GDP real, annual growth", [100, 115, 125, 110, 90, 70, 80, 110, 130]),
        ]
    }

    signals = signal_extractor._deterministic_signals(payload)
    assert len(signals) == 1
    profile = signals[0]

    assert profile["segments"], "Expected long period to be split into segments."
    assert len(profile["segments"]) >= 3
    patterns = {seg["pattern"] for seg in profile["segments"]}
    assert "rising" in patterns
    assert "falling" in patterns or "reversing" in patterns

    assert profile["long_term_trend"].startswith("rising")
    assert profile["turning_points"], "Expected at least one inflection/reversal point."


def test_signal_profile_detects_spikes_and_dips_across_whole_period():
    payload = {
        "series": [
            _series("Inflation, consumer price index - % year-on-year", [2.1, 2.2, 2.4, 2.3, 5.8, 2.5, 1.1, 2.0, 2.2]),
        ]
    }

    signals = signal_extractor._deterministic_signals(payload)
    assert len(signals) == 1
    profile = signals[0]
    events = profile["spikes_or_dips"]
    event_types = {event["type"] for event in events}

    assert "spike" in event_types
    assert "dip" in event_types
    assert profile["materiality"] in {"low", "medium", "high"}


def test_component_drivers_present_when_multiple_series_exist():
    payload = {
        "series": [
            _series("GDP, oil, real, LCU", [90, 88, 84, 80, 79, 77, 76, 74]),
            _series("GDP, non-oil, real, LCU", [100, 104, 108, 113, 118, 124, 130, 136]),
            _series("GDP real, annual growth", [95, 97, 96, 99, 102, 106, 110, 114]),
        ]
    }

    signals = signal_extractor._deterministic_signals(payload)
    assert len(signals) == 3
    for profile in signals:
        assert profile["component_drivers"], "Expected component drivers when sibling series exist."
        assert profile["pattern"] in {"rising", "falling", "stable", "volatile", "reversing", "mixed"}
