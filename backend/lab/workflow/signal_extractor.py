"""Signal extraction step for the lab workflow."""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from backend.lab.workflow.common import REASONING_MODEL, call_json_model


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


def _date_label(raw: str) -> str:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m")
    except Exception:
        return raw


def _deterministic_signals(kpi_payload: dict[str, Any]) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    signal_idx = 1
    for series in kpi_payload.get("series", []):
        points = _sorted_points(series)
        values = _to_float_list(points)
        if len(values) < 4:
            continue

        latest = values[-1]
        prev = values[:-1]
        prev_mean = statistics.mean(prev)
        prev_std = statistics.pstdev(prev) or 0.0
        first = values[0]
        diffs = [values[i] - values[i - 1] for i in range(1, len(values))]

        indicator = series.get("indicator", "indicator")
        country = series.get("country", "")
        last_date = _date_label(points[-1].get("date", ""))

        if prev_std > 0:
            z_score = (latest - prev_mean) / prev_std
            if z_score >= 1.5:
                signals.append({
                    "id": f"sig_{signal_idx}",
                    "type": "spike",
                    "description": f"{country} {indicator} shows a sharp upward spike in {last_date}.",
                    "evidence": {"z_score": round(z_score, 2), "latest_value": latest, "mean_prior": round(prev_mean, 3)},
                })
                signal_idx += 1
            elif z_score <= -1.5:
                signals.append({
                    "id": f"sig_{signal_idx}",
                    "type": "dip",
                    "description": f"{country} {indicator} shows a sharp downward dip in {last_date}.",
                    "evidence": {"z_score": round(z_score, 2), "latest_value": latest, "mean_prior": round(prev_mean, 3)},
                })
                signal_idx += 1

        pct_change = ((latest - first) / abs(first)) if first else 0.0
        if pct_change >= 0.15:
            signals.append({
                "id": f"sig_{signal_idx}",
                "type": "long_term_uptrend",
                "description": f"{country} {indicator} has a sustained positive trend over the selected period.",
                "evidence": {"pct_change": round(pct_change * 100, 2), "first_value": first, "latest_value": latest},
            })
            signal_idx += 1
        elif pct_change <= -0.15:
            signals.append({
                "id": f"sig_{signal_idx}",
                "type": "long_term_downtrend",
                "description": f"{country} {indicator} has a sustained negative trend over the selected period.",
                "evidence": {"pct_change": round(pct_change * 100, 2), "first_value": first, "latest_value": latest},
            })
            signal_idx += 1

        if len(diffs) >= 3:
            previous_direction = diffs[-3]
            current_direction = diffs[-1]
            if previous_direction * current_direction < 0:
                signals.append({
                    "id": f"sig_{signal_idx}",
                    "type": "inflection_point",
                    "description": f"{country} {indicator} recently changed direction, suggesting an inflection point.",
                    "evidence": {"previous_diff": round(previous_direction, 4), "latest_diff": round(current_direction, 4)},
                })
                signal_idx += 1

            direction_changes = 0
            for idx in range(1, len(diffs)):
                if diffs[idx - 1] * diffs[idx] < 0:
                    direction_changes += 1
            if direction_changes >= max(2, len(diffs) // 2):
                signals.append({
                    "id": f"sig_{signal_idx}",
                    "type": "rapid_undulation",
                    "description": f"{country} {indicator} oscillates rapidly with frequent sign changes.",
                    "evidence": {"direction_changes": direction_changes, "periods_observed": len(diffs)},
                })
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
        caller="lab.signal_extractor",
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

