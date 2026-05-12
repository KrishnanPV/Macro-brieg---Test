"""Signal extraction step for the insights workflow."""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_json_model


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


def _trend_label_from_pct(pct: float, *, stable_threshold: float = 0.03) -> str:
    if pct >= stable_threshold:
        return "rising"
    if pct <= -stable_threshold:
        return "falling"
    return "stable"


def _level_from_score(score: float) -> str:
    if score >= 45:
        return "high"
    if score >= 20:
        return "medium"
    return "low"


def _rolling_mean(values: list[float], window: int) -> list[float]:
    if not values:
        return []
    if window <= 1:
        return list(values)
    rolling: list[float] = []
    for idx in range(len(values)):
        start = max(0, idx - window + 1)
        rolling.append(statistics.mean(values[start : idx + 1]))
    return rolling


def _slope(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    return (values[-1] - values[0]) / (len(values) - 1)


def _segment_pattern(values: list[float]) -> str:
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
    return _trend_label_from_pct(pct)


def _build_phase_segments(
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if not values:
        return []
    segments: list[dict[str, Any]] = []
    count = _segment_count(len(values))
    chunk = max(1, math.ceil(len(values) / count))
    for start_idx in range(0, len(values), chunk):
        end_idx = min(len(values), start_idx + chunk)
        chunk_values = values[start_idx:end_idx]
        if len(chunk_values) < 2:
            continue
        pct = _pct_change(chunk_values[0], chunk_values[-1])
        pattern = _segment_pattern(chunk_values)
        change_text = f"{chunk_values[0]:.2f} -> {chunk_values[-1]:.2f} ({pct * 100:+.1f}%)"
        score = abs(pct) * 100
        if pattern in {"volatile", "reversing", "mixed"}:
            score += 10
        significance = _level_from_score(score)
        segments.append(
            {
                "period": f"{_date_label(points[start_idx].get('date', ''))} to {_date_label(points[end_idx - 1].get('date', ''))}",
                "pattern": pattern,
                "signal": change_text,
                "significance": f"{significance} ({score:.1f})",
            }
        )
    return segments


def _build_turning_points(
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if len(values) < 4:
        return []
    turning_points: list[dict[str, Any]] = []
    smooth = _rolling_mean(values, window=3)
    diffs = [smooth[idx] - smooth[idx - 1] for idx in range(1, len(smooth))]
    base_scale = statistics.mean([abs(d) for d in diffs]) if diffs else 0.0
    base_scale = base_scale or 1e-6
    for idx in range(1, len(smooth) - 1):
        prev_diff = smooth[idx] - smooth[idx - 1]
        next_diff = smooth[idx + 1] - smooth[idx]
        if prev_diff * next_diff >= 0:
            continue
        reversal_to = "upward" if next_diff > 0 else "downward"
        kind = "trough" if next_diff > 0 else "peak"
        swing = abs(next_diff - prev_diff)
        score = (swing / base_scale) * 10
        turning_points.append(
            {
                "period": _date_label(points[idx].get("date", "")),
                "type": kind,
                "reversal_to": reversal_to,
                "value": values[idx],
                "signal": f"{kind} with {reversal_to} reversal",
                "significance": f"{_level_from_score(score)} ({score:.1f})",
            }
        )
    return turning_points


def _build_spikes_or_dips(
    points: list[dict[str, Any]],
    values: list[float],
) -> list[dict[str, Any]]:
    if len(values) < 4:
        return []
    spikes_or_dips: list[dict[str, Any]] = []
    mean_val = statistics.mean(values)
    std_val = statistics.pstdev(values) or 0.0
    p90 = _percentile(values, 0.9)
    p10 = _percentile(values, 0.1)
    for idx, value in enumerate(values):
        z = (value - mean_val) / std_val if std_val > 0 else 0.0
        event_type = ""
        if std_val > 0 and (z >= 1.5 or (value >= p90 and value > mean_val)):
            event_type = "spike"
        elif std_val > 0 and (z <= -1.5 or (value <= p10 and value < mean_val)):
            event_type = "dip"
        if not event_type:
            continue
        score = abs(z) * 15
        spikes_or_dips.append(
            {
                "period": _date_label(points[idx].get("date", "")),
                "type": event_type,
                "value": value,
                "z_score": round(z, 2),
                "signal": f"{event_type} at {value:.2f} (z={z:.2f})",
                "significance": f"{_level_from_score(score)} ({score:.1f})",
            }
        )
    return spikes_or_dips


def _short_term_momentum(values: list[float]) -> tuple[str, float]:
    if len(values) < 4:
        return "insufficient data", 0.0
    step = min(3, len(values) - 1)
    recent = (values[-1] - values[-1 - step]) / step
    if len(values) >= (2 * step + 1):
        prior = (values[-1 - step] - values[-1 - (2 * step)]) / step
    else:
        prior = (values[-2] - values[0]) / max(1, len(values) - 2)
    direction = "positive" if recent > 0 else "negative" if recent < 0 else "flat"
    change = ""
    if recent * prior < 0:
        change = " after reversal"
    elif abs(recent) > abs(prior) * 1.2:
        change = " and accelerating"
    elif abs(recent) < abs(prior) * 0.8:
        change = " and decelerating"
    return f"{direction}{change} (recent slope {recent:+.3f})", recent


def _volatility_signal(values: list[float]) -> tuple[str, float]:
    if len(values) < 3:
        return "low volatility", 0.0
    diffs = [values[idx] - values[idx - 1] for idx in range(1, len(values))]
    sign_changes = sum(1 for idx in range(1, len(diffs)) if diffs[idx - 1] * diffs[idx] < 0)
    avg_level = abs(statistics.mean(values)) or 1.0
    vol_ratio = (statistics.pstdev(values) or 0.0) / avg_level
    oscillation_ratio = sign_changes / max(1, len(diffs) - 1)
    score = (vol_ratio * 100) + (oscillation_ratio * 35)
    label = _level_from_score(score)
    if label == "high":
        return f"high volatility/oscillation (vol_ratio={vol_ratio:.2f}, sign_change_ratio={oscillation_ratio:.2f})", score
    if label == "medium":
        return f"moderate volatility (vol_ratio={vol_ratio:.2f}, sign_change_ratio={oscillation_ratio:.2f})", score
    return f"low volatility (vol_ratio={vol_ratio:.2f}, sign_change_ratio={oscillation_ratio:.2f})", score


def _series_component_drivers(
    current: dict[str, Any],
    peers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    same_country_peers = [peer for peer in peers if peer["country"] == current["country"]]
    if len(same_country_peers) <= 1:
        return []
    peer_movers = sorted(
        [peer for peer in same_country_peers if peer["indicator"] != current["indicator"]],
        key=lambda item: abs(item["delta"]),
        reverse=True,
    )
    if not peer_movers:
        return []
    total_abs_delta = sum(abs(item["delta"]) for item in same_country_peers) or 1.0
    drivers: list[dict[str, Any]] = []
    for peer in peer_movers[:3]:
        share = abs(peer["delta"]) / total_abs_delta
        alignment = "reinforcing" if peer["delta"] * current["delta"] > 0 else "offsetting"
        score = (abs(peer["pct_change"]) * 100) + (share * 35)
        drivers.append(
            {
                "component": peer["indicator"],
                "signal": f"{peer['delta']:+.2f} ({peer['pct_change'] * 100:+.1f}%) move over full period",
                "alignment": alignment,
                "significance": f"{_level_from_score(score)} ({score:.1f})",
            }
        )
    return drivers


def _date_label(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m")
    except Exception:
        return raw


def _deterministic_signals(kpi_payload: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    signal_idx = 1
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
                "indicator": str(series.get("indicator", "indicator")),
                "country": str(series.get("country", "")),
                "source_kpi_id": str(series.get("source_kpi_id") or "").strip(),
                "source_frequency": str(series.get("source_frequency") or "").strip(),
                "delta": values[-1] - values[0],
                "pct_change": _pct_change(values[0], values[-1]),
            }
        )

    for item in valid_series:
        points = item["points"]
        values = item["values"]
        overall_pct = item["pct_change"]
        overall_trend = _trend_label_from_pct(overall_pct)
        segments = _build_phase_segments(points, values)
        turning_points = _build_turning_points(points, values)
        spikes_or_dips = _build_spikes_or_dips(points, values)
        short_momentum, short_momentum_score = _short_term_momentum(values)
        volatility_text, volatility_score = _volatility_signal(values)
        component_drivers = _series_component_drivers(item, valid_series)
        indicator = item["indicator"]
        country = item["country"]
        source_kpi_id = item["source_kpi_id"]
        source_frequency = item["source_frequency"]
        start_label = _date_label(points[0].get("date", ""))
        end_label = _date_label(points[-1].get("date", ""))
        period_summary = (
            f"{country} {indicator} moved from {values[0]:.2f} to {values[-1]:.2f} "
            f"between {start_label} and {end_label} ({overall_pct * 100:+.1f}%)."
        )
        long_term_trend = f"{overall_trend} ({overall_pct * 100:+.1f}% over full period)"
        materiality_score = (
            abs(overall_pct) * 100
            + (len(spikes_or_dips) * 12)
            + (len(turning_points) * 8)
            + abs(short_momentum_score) * 3
            + volatility_score * 0.4
        )
        materiality = _level_from_score(materiality_score)
        primary_pattern = overall_trend
        if materiality == "high" and "volatility" in volatility_text:
            primary_pattern = "volatile"
        elif turning_points:
            primary_pattern = "reversing"
        description = (
            f"{country} {indicator}: {long_term_trend}; "
            f"{len(segments)} phase trends, {len(turning_points)} turning points, "
            f"{len(spikes_or_dips)} spikes/dips."
        )

        signals.append(
            {
                "id": f"sig_{signal_idx}",
                "type": "kpi_signal_profile",
                "description": description,
                "kpi": indicator,
                "period_summary": period_summary,
                "segments": segments,
                "turning_points": turning_points,
                "spikes_or_dips": spikes_or_dips,
                "short_term_momentum": short_momentum,
                "long_term_trend": long_term_trend,
                "volatility_or_oscillation": volatility_text,
                "component_drivers": component_drivers,
                "materiality": materiality,
                "pattern": primary_pattern,
                "source_kpi_id": source_kpi_id,
                "source_frequency": source_frequency,
                "evidence": {
                    "overall_pct_change": round(overall_pct * 100, 2),
                    "start_value": values[0],
                    "end_value": values[-1],
                    "segment_count": len(segments),
                    "turning_point_count": len(turning_points),
                    "spike_or_dip_count": len(spikes_or_dips),
                },
            }
        )
        signal_idx += 1

    return signals


def run_step(
    kpi_payload: dict[str, Any],
    *,
    reasoning_model: str = REASONING_MODEL,
) -> dict[str, Any]:
    """Extract deterministic signals and filter to high-relevance ones."""
    raw_signals = _deterministic_signals(kpi_payload)
    if not raw_signals:
        return {
            "raw_signals": [],
            "selected_signals": [],
            "filter_notes": "No clear deterministic signals detected.",
            "call_meta": None,
        }

    system_prompt = (
        "You are a macro signal triage assistant. Select only the most decision-relevant "
        "signals and ignore weak or redundant ones. Return JSON with keys "
        "`selected_signal_ids` (array) and `notes` (string)."
    )
    user_prompt = (
        "Signals extracted from KPI data:\n"
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

