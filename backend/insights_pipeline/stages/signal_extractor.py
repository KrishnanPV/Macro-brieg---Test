"""Deterministic signal extraction for the insights workflow.

Produces a flat, homogeneous list of Signal objects. Every signal has the
exact same top-level shape (``UNIVERSAL_KEYS``); type-specific extras live in
a ``metrics`` sub-dict whose key set is locked per ``signal_type`` via
``_METRICS_SCHEMA``. ``_make_signal`` is the single constructor and rejects
any drift with ``ValueError``.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_json_model


# ---------------------------------------------------------------------------
# Locked schema constants
# ---------------------------------------------------------------------------

UNIVERSAL_KEYS: tuple[str, ...] = (
    "id", "signal_type",
    "kpi", "kpi_id", "country", "frequency", "unit",
    "period_start", "period_end", "period_length_months",
    "start_value", "end_value", "abs_change", "pct_change",
    "direction", "metrics",
)

SIGNAL_TYPES: frozenset[str] = frozenset({
    "long_term_trend", "phase_trend", "turning_point",
    "spike", "dip", "momentum_shift",
    "volatility", "component_driver",
})

DIRECTIONS: frozenset[str] = frozenset({
    "up", "down", "flat", "volatile", "reversing_up", "reversing_down",
})

SIGNAL_TYPE_GLOSSARY: dict[str, str] = {
    "long_term_trend": "Net change from the first to the last observation in the full series window.",
    "phase_trend":     "Directional trend over a contiguous sub-window (chunk) of the series.",
    "turning_point":   "Local peak or trough where the smoothed series reverses direction.",
    "spike":           "Single observation whose value is unusually high relative to the series (|z| >= 1.5 or above the 90th percentile).",
    "dip":             "Single observation whose value is unusually low relative to the series (|z| <= -1.5 or below the 10th percentile).",
    "momentum_shift":  "Most recent slope differs materially from the immediately prior slope (acceleration, deceleration, or reversal).",
    "volatility":      "Whole-window dispersion and sign-change behaviour, independent of net direction.",
    "component_driver": "Movement in a peer indicator within the same country that is reinforcing or offsetting the focal indicator.",
}

_METRICS_SCHEMA: dict[str, frozenset[str]] = {
    "long_term_trend":  frozenset(),
    "phase_trend":      frozenset({"pattern", "phase_index", "phase_count"}),
    "turning_point":    frozenset({"kind", "pivot_date", "pivot_value", "swing"}),
    "spike":            frozenset({"z_score", "series_mean", "series_stdev"}),
    "dip":              frozenset({"z_score", "series_mean", "series_stdev"}),
    "momentum_shift":   frozenset({"recent_slope", "prior_slope", "acceleration_state"}),
    "volatility":       frozenset({"vol_ratio", "sign_change_ratio"}),
    "component_driver": frozenset({"parent_kpi_id", "parent_kpi", "share_of_total_move", "alignment"}),
}

_STABLE_PCT_THRESHOLD: float = 0.03
_SMOOTHING_WINDOW: int = 3
_VOLATILITY_HIGH_SCORE: float = 45.0


# ---------------------------------------------------------------------------
# Numeric helpers (no narrative output)
# ---------------------------------------------------------------------------

def _sorted_points(series: dict[str, Any]) -> list[dict[str, Any]]:
    points = [p for p in series.get("points", []) if p.get("value") is not None]
    points.sort(key=lambda p: p.get("date", ""))
    return points


def _to_float_list(points: list[dict[str, Any]]) -> list[float]:
    values: list[float] = []
    for point in points:
        try:
            values.append(float(point["value"]))
        except (TypeError, ValueError, KeyError):
            continue
    return values


def _pct_change(start: float, end: float) -> float:
    denom = abs(start) if abs(start) > 1e-9 else 1.0
    return (end - start) / denom


def _segment_count(length: int) -> int:
    if length >= 12:
        return 4
    if length >= 8:
        return 3
    if length >= 5:
        return 2
    return 1


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return sorted_vals[lower]
    weight = pos - lower
    return sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight


def _rolling_mean(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return list(values)
    rolling: list[float] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        rolling.append(statistics.mean(values[start: idx + 1]))
    return rolling


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / (len(values) - 1)


def _segment_pattern(values: list[float]) -> str:
    """Return one of: rising | falling | stable | volatile | reversing | mixed."""
    if len(values) < 2:
        return "stable"
    diffs = [values[idx] - values[idx - 1] for idx in range(1, len(values))]
    sign_changes = sum(1 for idx in range(1, len(diffs)) if diffs[idx - 1] * diffs[idx] < 0)
    pct = _pct_change(values[0], values[-1])
    if len(values) >= 4:
        mid = len(values) // 2
        left = _slope(values[: mid + 1])
        right = _slope(values[mid:])
        if left * right < 0 and abs(left) + abs(right) > 0:
            return "reversing"
    if sign_changes >= max(2, len(diffs) // 2) and abs(pct) < 0.12:
        return "volatile"
    if sign_changes > 0 and abs(pct) < 0.05:
        return "mixed"
    if pct >= _STABLE_PCT_THRESHOLD:
        return "rising"
    if pct <= -_STABLE_PCT_THRESHOLD:
        return "falling"
    return "stable"


def _date_label(raw: str) -> str:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime("%Y-%m")
    except Exception:
        return str(raw)


def _months_between_labels(start_label: str, end_label: str) -> int:
    try:
        start_year, start_month = int(start_label[:4]), int(start_label[5:7])
        end_year, end_month = int(end_label[:4]), int(end_label[5:7])
        return (end_year - start_year) * 12 + (end_month - start_month)
    except (ValueError, IndexError):
        return 0


def _direction_from_pct(pct: float) -> str:
    if pct >= _STABLE_PCT_THRESHOLD:
        return "up"
    if pct <= -_STABLE_PCT_THRESHOLD:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# The only Signal constructor
# ---------------------------------------------------------------------------

def _make_signal(
    signal_type: str,
    *,
    series_meta: dict[str, Any],
    period_start: str,
    period_end: str,
    start_value: float,
    end_value: float,
    metrics: dict[str, Any],
    direction_override: str | None = None,
) -> dict[str, Any]:
    """Build one Signal dict, enforcing the universal and per-type schemas.

    Raises ``ValueError`` on any drift: unknown ``signal_type``, wrong metrics
    key set, or unknown ``direction``. Callers do not pass ``id`` — it is
    assigned by the orchestrator after all signals are collected.
    """
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(
            f"Unknown signal_type {signal_type!r}; expected one of {sorted(SIGNAL_TYPES)}."
        )
    expected_keys = _METRICS_SCHEMA[signal_type]
    actual_keys = frozenset(metrics.keys())
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        raise ValueError(
            f"metrics for signal_type={signal_type!r} must have keys "
            f"{sorted(expected_keys)}; missing={missing}, extra={extra}."
        )

    start = float(start_value)
    end = float(end_value)
    abs_change = end - start
    pct_change = _pct_change(start, end)

    if direction_override is not None:
        if direction_override not in DIRECTIONS:
            raise ValueError(
                f"direction_override={direction_override!r} not in {sorted(DIRECTIONS)}."
            )
        direction = direction_override
    else:
        direction = _direction_from_pct(pct_change)

    signal: dict[str, Any] = {
        "id": "",
        "signal_type": signal_type,
        "kpi": str(series_meta.get("indicator") or ""),
        "kpi_id": str(series_meta.get("source_kpi_id") or ""),
        "country": str(series_meta.get("country") or ""),
        "frequency": str(series_meta.get("source_frequency") or ""),
        "unit": str(series_meta.get("unit") or ""),
        "period_start": str(period_start),
        "period_end": str(period_end),
        "period_length_months": _months_between_labels(str(period_start), str(period_end)),
        "start_value": start,
        "end_value": end,
        "abs_change": abs_change,
        "pct_change": pct_change,
        "direction": direction,
        "metrics": dict(metrics),
    }

    if tuple(signal.keys()) != UNIVERSAL_KEYS:
        raise ValueError(
            f"Signal key order must be {UNIVERSAL_KEYS}; got {tuple(signal.keys())}."
        )
    return signal


# ---------------------------------------------------------------------------
# Detectors — each returns a list of Signal dicts built via _make_signal
# ---------------------------------------------------------------------------

def _long_term_trend_signal(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> dict[str, Any]:
    return _make_signal(
        "long_term_trend",
        series_meta=series_meta,
        period_start=_date_label(points[0].get("date", "")),
        period_end=_date_label(points[-1].get("date", "")),
        start_value=values[0],
        end_value=values[-1],
        metrics={},
    )


def _phase_trend_signals(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if not values:
        return []
    signals: list[dict[str, Any]] = []
    count = _segment_count(len(values))
    chunk = max(1, math.ceil(len(values) / count))
    chunk_ranges: list[tuple[int, int]] = []
    for start_idx in range(0, len(values), chunk):
        end_idx = min(len(values), start_idx + chunk)
        if end_idx - start_idx < 2:
            continue
        chunk_ranges.append((start_idx, end_idx))
    phase_count = len(chunk_ranges)
    for phase_index, (start_idx, end_idx) in enumerate(chunk_ranges, start=1):
        chunk_values = values[start_idx:end_idx]
        pattern = _segment_pattern(chunk_values)
        signals.append(
            _make_signal(
                "phase_trend",
                series_meta=series_meta,
                period_start=_date_label(points[start_idx].get("date", "")),
                period_end=_date_label(points[end_idx - 1].get("date", "")),
                start_value=chunk_values[0],
                end_value=chunk_values[-1],
                metrics={
                    "pattern": pattern,
                    "phase_index": phase_index,
                    "phase_count": phase_count,
                },
            )
        )
    return signals


def _turning_point_signals(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if len(values) < 4:
        return []
    signals: list[dict[str, Any]] = []
    smooth = _rolling_mean(values, window=_SMOOTHING_WINDOW)
    for idx in range(1, len(smooth) - 1):
        prev_diff = smooth[idx] - smooth[idx - 1]
        next_diff = smooth[idx + 1] - smooth[idx]
        if prev_diff * next_diff >= 0:
            continue
        kind = "trough" if next_diff > 0 else "peak"
        direction = "reversing_up" if next_diff > 0 else "reversing_down"
        swing = float(abs(next_diff - prev_diff))
        window_lo = max(0, idx - _SMOOTHING_WINDOW)
        window_hi = min(len(values) - 1, idx + _SMOOTHING_WINDOW)
        signals.append(
            _make_signal(
                "turning_point",
                series_meta=series_meta,
                period_start=_date_label(points[window_lo].get("date", "")),
                period_end=_date_label(points[window_hi].get("date", "")),
                start_value=smooth[window_lo],
                end_value=smooth[window_hi],
                metrics={
                    "kind": kind,
                    "pivot_date": _date_label(points[idx].get("date", "")),
                    "pivot_value": float(values[idx]),
                    "swing": swing,
                },
                direction_override=direction,
            )
        )
    return signals


def _spike_dip_signals(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if len(values) < 4:
        return []
    mean_val = statistics.mean(values)
    std_val = statistics.pstdev(values) or 0.0
    if std_val <= 0:
        return []
    p90 = _percentile(values, 0.9)
    p10 = _percentile(values, 0.1)
    signals: list[dict[str, Any]] = []
    for idx, value in enumerate(values):
        z = (value - mean_val) / std_val
        if z >= 1.5 or (value >= p90 and value > mean_val):
            signal_type = "spike"
            direction = "up"
        elif z <= -1.5 or (value <= p10 and value < mean_val):
            signal_type = "dip"
            direction = "down"
        else:
            continue
        prev_idx = idx - 1 if idx > 0 else idx
        signals.append(
            _make_signal(
                signal_type,
                series_meta=series_meta,
                period_start=_date_label(points[prev_idx].get("date", "")),
                period_end=_date_label(points[idx].get("date", "")),
                start_value=values[prev_idx],
                end_value=value,
                metrics={
                    "z_score": round(float(z), 3),
                    "series_mean": float(mean_val),
                    "series_stdev": float(std_val),
                },
                direction_override=direction,
            )
        )
    return signals


def _momentum_signals(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if len(values) < 4:
        return []
    step = min(3, len(values) - 1)
    recent = (values[-1] - values[-1 - step]) / step
    if len(values) >= (2 * step + 1):
        prior = (values[-1 - step] - values[-1 - (2 * step)]) / step
    else:
        prior = (values[-2] - values[0]) / max(1, len(values) - 2)
    if recent * prior < 0:
        acceleration = "reversed"
    elif abs(recent) > abs(prior) * 1.2:
        acceleration = "accelerating"
    elif abs(recent) < abs(prior) * 0.8:
        acceleration = "decelerating"
    else:
        acceleration = "steady"
    start_idx = max(0, len(values) - 1 - step)
    return [
        _make_signal(
            "momentum_shift",
            series_meta=series_meta,
            period_start=_date_label(points[start_idx].get("date", "")),
            period_end=_date_label(points[-1].get("date", "")),
            start_value=values[start_idx],
            end_value=values[-1],
            metrics={
                "recent_slope": round(float(recent), 6),
                "prior_slope": round(float(prior), 6),
                "acceleration_state": acceleration,
            },
        )
    ]


def _volatility_signal(
    series_meta: dict[str, Any],
    points: list[dict[str, Any]],
    values: list[float],
) -> dict[str, Any]:
    if len(values) < 3:
        vol_ratio = 0.0
        sign_change_ratio = 0.0
    else:
        diffs = [values[idx] - values[idx - 1] for idx in range(1, len(values))]
        sign_changes = sum(1 for idx in range(1, len(diffs)) if diffs[idx - 1] * diffs[idx] < 0)
        avg_level = abs(statistics.mean(values)) or 1.0
        vol_ratio = (statistics.pstdev(values) or 0.0) / avg_level
        sign_change_ratio = sign_changes / max(1, len(diffs) - 1)
    score = (vol_ratio * 100) + (sign_change_ratio * 35)
    if score >= _VOLATILITY_HIGH_SCORE:
        direction_override: str | None = "volatile"
    else:
        direction_override = None
    return _make_signal(
        "volatility",
        series_meta=series_meta,
        period_start=_date_label(points[0].get("date", "")),
        period_end=_date_label(points[-1].get("date", "")),
        start_value=values[0],
        end_value=values[-1],
        metrics={
            "vol_ratio": round(float(vol_ratio), 6),
            "sign_change_ratio": round(float(sign_change_ratio), 6),
        },
        direction_override=direction_override,
    )


def _component_driver_signals(
    focal: dict[str, Any],
    valid_series: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    same_country_peers = [peer for peer in valid_series if peer["country"] == focal["country"]]
    if len(same_country_peers) <= 1:
        return []
    peer_movers = sorted(
        [peer for peer in same_country_peers if peer["indicator"] != focal["indicator"]],
        key=lambda item: abs(item["delta"]),
        reverse=True,
    )
    if not peer_movers:
        return []
    total_abs_delta = sum(abs(item["delta"]) for item in same_country_peers) or 1.0
    parent_kpi_id = str(focal.get("source_kpi_id") or "")
    parent_kpi = str(focal.get("indicator") or "")
    signals: list[dict[str, Any]] = []
    for peer in peer_movers[:3]:
        share = abs(peer["delta"]) / total_abs_delta
        alignment = "reinforcing" if peer["delta"] * focal["delta"] > 0 else "offsetting"
        peer_points = peer["points"]
        peer_values = peer["values"]
        signals.append(
            _make_signal(
                "component_driver",
                series_meta={
                    "indicator": peer["indicator"],
                    "source_kpi_id": peer["source_kpi_id"],
                    "country": peer["country"],
                    "source_frequency": peer["source_frequency"],
                    "unit": peer.get("unit", ""),
                },
                period_start=_date_label(peer_points[0].get("date", "")),
                period_end=_date_label(peer_points[-1].get("date", "")),
                start_value=peer_values[0],
                end_value=peer_values[-1],
                metrics={
                    "parent_kpi_id": parent_kpi_id,
                    "parent_kpi": parent_kpi,
                    "share_of_total_move": round(float(share), 6),
                    "alignment": alignment,
                },
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _deterministic_signals(kpi_payload: dict[str, Any]) -> list[dict[str, Any]]:
    valid_series: list[dict[str, Any]] = []
    for series in kpi_payload.get("series", []):
        points = _sorted_points(series)
        values = _to_float_list(points)
        if len(values) < 4:
            continue
        valid_series.append(
            {
                "series": series,
                "points": points,
                "values": values,
                "indicator": str(series.get("indicator") or "indicator"),
                "country": str(series.get("country") or ""),
                "source_kpi_id": str(series.get("source_kpi_id") or "").strip(),
                "source_frequency": str(series.get("source_frequency") or "").strip(),
                "unit": str(series.get("unit") or "").strip(),
                "delta": values[-1] - values[0],
                "pct_change": _pct_change(values[0], values[-1]),
            }
        )

    signals: list[dict[str, Any]] = []
    for item in valid_series:
        points = item["points"]
        values = item["values"]
        series_meta = {
            "indicator": item["indicator"],
            "source_kpi_id": item["source_kpi_id"],
            "country": item["country"],
            "source_frequency": item["source_frequency"],
            "unit": item["unit"],
        }
        signals.append(_long_term_trend_signal(series_meta, points, values))
        signals.extend(_phase_trend_signals(series_meta, points, values))
        signals.extend(_turning_point_signals(series_meta, points, values))
        signals.extend(_spike_dip_signals(series_meta, points, values))
        signals.extend(_momentum_signals(series_meta, points, values))
        signals.append(_volatility_signal(series_meta, points, values))
        signals.extend(_component_driver_signals(item, valid_series))

    for idx, signal in enumerate(signals, start=1):
        signal["id"] = f"sig_{idx:03d}"
    return signals


def run_step(
    kpi_payload: dict[str, Any],
    *,
    reasoning_model: str = REASONING_MODEL,
    use_llm_triage: bool = True,
) -> dict[str, Any]:
    """Extract deterministic signals and optionally LLM-triage them.

    When ``use_llm_triage`` is False the LLM triage call is skipped and the
    caller receives ``raw_signals`` only; ``selected_signals`` is left empty
    so callers can apply their own selection rule.
    """
    raw_signals = _deterministic_signals(kpi_payload)
    if not raw_signals:
        return {
            "raw_signals": [],
            "selected_signals": [],
            "filter_notes": "No clear deterministic signals detected.",
            "call_meta": None,
        }

    if not use_llm_triage:
        return {
            "raw_signals": raw_signals,
            "selected_signals": [],
            "filter_notes": "LLM triage skipped; caller will select signals.",
            "call_meta": None,
        }

    glossary_text = "\n".join(f"- {tag}: {desc}" for tag, desc in SIGNAL_TYPE_GLOSSARY.items())
    system_prompt = (
        "You are a macro signal triage assistant. Each signal is a uniform row "
        "describing one data movement on one KPI. The fields are identical for "
        "every row; only `signal_type` and the contents of `metrics` vary. "
        "Select the most decision-relevant rows; ignore weak or redundant ones. "
        "Return JSON with keys `selected_signal_ids` (array of signal ids) and "
        "`notes` (short string).\n\n"
        "Signal type glossary:\n"
        f"{glossary_text}"
    )
    user_prompt = (
        "Signals extracted from KPI data (flat homogeneous list):\n"
        f"{raw_signals}\n\n"
        "Select up to 6 signals that are most relevant for hypothesis generation."
    )
    triage, call_meta = call_json_model(
        model=reasoning_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="insights_pipeline.signal_extractor",
        include_call_meta=True,
    )
    selected_ids = triage.get("selected_signal_ids", [])
    selected = [s for s in raw_signals if s["id"] in selected_ids]
    if not selected:
        selected = raw_signals[: min(6, len(raw_signals))]
    return {
        "raw_signals": raw_signals,
        "selected_signals": selected,
        "filter_notes": triage.get("notes", ""),
        "call_meta": call_meta,
    }
