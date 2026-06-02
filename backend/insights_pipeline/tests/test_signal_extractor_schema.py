"""Schema tests for the unified signal extractor.

Asserts the exact universal-key shape, the per-signal_type ``metrics`` key sets,
and the internal consistency of ``abs_change`` / ``pct_change`` / ``direction``.
Also covers the negative path: ``_make_signal`` must raise ``ValueError`` on
any drift.
"""
from __future__ import annotations

import math

import pytest

from backend.insights_pipeline.stages.signal_extractor import (
    DIRECTIONS,
    SIGNAL_TYPES,
    UNIVERSAL_KEYS,
    _METRICS_SCHEMA,
    _deterministic_signals,
    _make_signal,
)

# A 16-point monthly series engineered to produce every signal_type the
# extractor knows about: a clear rise, a peak (turning point), a high spike,
# a fall to a low dip, a trough (turning point), and a recovery. The peak/spike
# at idx=5 and the dip at idx=10 are both well past |z|>=1.5 with this stdev.
_FOCAL_VALUES = [100, 105, 110, 115, 120, 145, 118, 115, 110, 105, 70, 95, 100, 105, 110, 115]
# A flat-rising peer series so a component_driver signal can fire against the
# focal series (same country, different indicator).
_PEER_VALUES = [50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74, 76, 78, 80]


def _monthly_points(values: list[float]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for idx, value in enumerate(values):
        year = 2023 + (idx // 12)
        month = (idx % 12) + 1
        points.append({"date": f"{year:04d}-{month:02d}-01T00:00:00", "value": value})
    return points


def _kpi_payload() -> dict[str, object]:
    return {
        "series": [
            {
                "indicator": "Focal Series",
                "country": "SAU",
                "source_kpi_id": "F1",
                "source_frequency": "M",
                "unit": "%",
                "points": _monthly_points(_FOCAL_VALUES),
            },
            {
                "indicator": "Peer Series",
                "country": "SAU",
                "source_kpi_id": "P1",
                "source_frequency": "M",
                "unit": "%",
                "points": _monthly_points(_PEER_VALUES),
            },
        ],
    }


# ---------------------------------------------------------------------------
# Schema shape: universal keys
# ---------------------------------------------------------------------------

def test_every_signal_has_exact_universal_keys_in_order():
    signals = _deterministic_signals(_kpi_payload())
    assert signals, "Engineered payload should produce signals"
    for signal in signals:
        assert tuple(signal.keys()) == UNIVERSAL_KEYS, (
            f"Signal {signal.get('id')} has keys {tuple(signal.keys())}, "
            f"expected {UNIVERSAL_KEYS}"
        )


def test_signal_ids_are_unique_and_sequential():
    signals = _deterministic_signals(_kpi_payload())
    ids = [s["id"] for s in signals]
    assert len(ids) == len(set(ids))
    assert ids == [f"sig_{i:03d}" for i in range(1, len(ids) + 1)]


# ---------------------------------------------------------------------------
# Schema shape: signal_type enum and per-type metrics
# ---------------------------------------------------------------------------

def test_signal_type_is_always_in_closed_enum():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        assert signal["signal_type"] in SIGNAL_TYPES


def test_metrics_keys_exactly_match_per_type_schema():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        expected = _METRICS_SCHEMA[signal["signal_type"]]
        actual = frozenset(signal["metrics"].keys())
        assert actual == expected, (
            f"Signal {signal['id']} ({signal['signal_type']}): "
            f"metrics keys {sorted(actual)} != expected {sorted(expected)}"
        )


def test_direction_is_always_in_closed_enum():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        assert signal["direction"] in DIRECTIONS


# ---------------------------------------------------------------------------
# Internal numeric consistency
# ---------------------------------------------------------------------------

def test_abs_change_equals_end_minus_start():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        assert math.isclose(
            signal["abs_change"],
            signal["end_value"] - signal["start_value"],
            rel_tol=1e-9,
            abs_tol=1e-9,
        )


def test_direction_is_consistent_with_pct_change_or_override():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        signal_type = signal["signal_type"]
        direction = signal["direction"]
        pct = signal["pct_change"]
        if signal_type == "turning_point":
            assert direction in {"reversing_up", "reversing_down"}
        elif signal_type == "spike":
            assert direction == "up"
        elif signal_type == "dip":
            assert direction == "down"
        elif signal_type == "volatility":
            # Either flagged volatile, or fall-through to pct-based bucket.
            assert direction in {"up", "down", "flat", "volatile"}
        else:
            if pct >= 0.03:
                assert direction == "up"
            elif pct <= -0.03:
                assert direction == "down"
            else:
                assert direction == "flat"


def test_period_length_months_is_non_negative_and_matches_labels():
    signals = _deterministic_signals(_kpi_payload())
    for signal in signals:
        assert signal["period_length_months"] >= 0
        start_year, start_month = (int(signal["period_start"][:4]),
                                   int(signal["period_start"][5:7]))
        end_year, end_month = (int(signal["period_end"][:4]),
                               int(signal["period_end"][5:7]))
        expected = (end_year - start_year) * 12 + (end_month - start_month)
        assert signal["period_length_months"] == expected


# ---------------------------------------------------------------------------
# Coverage: required signal_types are all emitted for the crafted payload
# ---------------------------------------------------------------------------

def test_required_signal_types_are_all_produced():
    signals = _deterministic_signals(_kpi_payload())
    types_seen = {s["signal_type"] for s in signals}
    for required in ("long_term_trend", "volatility", "spike", "dip",
                     "turning_point", "phase_trend", "momentum_shift",
                     "component_driver"):
        assert required in types_seen, (
            f"Expected at least one {required} signal in crafted payload; "
            f"got types {sorted(types_seen)}"
        )


def test_each_series_emits_exactly_one_long_term_trend_and_one_volatility():
    signals = _deterministic_signals(_kpi_payload())
    long_terms = [s for s in signals if s["signal_type"] == "long_term_trend"]
    volatilities = [s for s in signals if s["signal_type"] == "volatility"]
    assert len(long_terms) == 2
    assert len(volatilities) == 2


# ---------------------------------------------------------------------------
# Enforcement: _make_signal rejects drift
# ---------------------------------------------------------------------------

_SERIES_META = {
    "indicator": "X",
    "source_kpi_id": "X1",
    "country": "SAU",
    "source_frequency": "M",
    "unit": "%",
}


def test_make_signal_rejects_unknown_signal_type():
    with pytest.raises(ValueError):
        _make_signal(
            "not_a_real_type",
            series_meta=_SERIES_META,
            period_start="2023-01",
            period_end="2023-02",
            start_value=1.0,
            end_value=2.0,
            metrics={},
        )


def test_make_signal_rejects_metrics_with_extra_key():
    with pytest.raises(ValueError):
        _make_signal(
            "long_term_trend",
            series_meta=_SERIES_META,
            period_start="2023-01",
            period_end="2023-02",
            start_value=1.0,
            end_value=2.0,
            metrics={"unexpected": 1},
        )


def test_make_signal_rejects_metrics_with_missing_key():
    with pytest.raises(ValueError):
        _make_signal(
            "spike",
            series_meta=_SERIES_META,
            period_start="2023-01",
            period_end="2023-02",
            start_value=1.0,
            end_value=2.0,
            metrics={"z_score": 2.0, "series_mean": 1.0},  # missing series_stdev
        )


def test_make_signal_rejects_unknown_direction_override():
    with pytest.raises(ValueError):
        _make_signal(
            "long_term_trend",
            series_meta=_SERIES_META,
            period_start="2023-01",
            period_end="2023-02",
            start_value=1.0,
            end_value=2.0,
            metrics={},
            direction_override="sideways",
        )


def test_make_signal_returns_keys_in_universal_order():
    signal = _make_signal(
        "long_term_trend",
        series_meta=_SERIES_META,
        period_start="2023-01",
        period_end="2023-12",
        start_value=1.0,
        end_value=2.0,
        metrics={},
    )
    assert tuple(signal.keys()) == UNIVERSAL_KEYS
