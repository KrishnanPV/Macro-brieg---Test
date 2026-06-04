"""Deterministic time-proximity linker between signals and news events.

This is intentionally minimal scaffolding for a future signal/event knowledge
graph. No LLM call is made; we just match each event date to signal sub-events
(segments, turning points, spikes/dips) within a +/- 6 month window and emit a
flat ``links`` list. Callers can hang richer relations off this structure later.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

DEFAULT_PROXIMITY_MONTHS = 6


def _parse_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except Exception:  # noqa: BLE001
        pass
    try:
        return datetime.strptime(text[:7], "%Y-%m").date()
    except Exception:  # noqa: BLE001
        pass
    if len(text) >= 4 and text[:4].isdigit():
        try:
            return date(int(text[:4]), 1, 1)
        except Exception:  # noqa: BLE001
            return None
    return None


def _months_between(a: date, b: date) -> float:
    delta_days = abs((a - b).days)
    return delta_days / 30.4375


_POINT_EVENT_TYPES: frozenset[str] = frozenset({"spike", "dip", "turning_point"})


def _signal_anchor_dates(signal: dict[str, Any]) -> Iterable[tuple[str, date]]:
    """Yield ``(sub_event_label, date)`` pairs for a flat-schema Signal.

    Point-style events (``spike`` / ``dip`` / ``turning_point``) prefer the
    ``metrics.pivot_date`` (the date of the actual event), falling back to
    ``period_end``. All other signal types anchor on ``period_end``.
    """
    signal_type = str(signal.get("signal_type") or "").strip()
    metrics = signal.get("metrics") or {}
    pivot_date = metrics.get("pivot_date") if isinstance(metrics, dict) else None
    period_end = signal.get("period_end")

    if signal_type in _POINT_EVENT_TYPES:
        parsed = _parse_date(pivot_date) or _parse_date(period_end)
        if parsed:
            yield signal_type, parsed
        return

    parsed = _parse_date(period_end)
    if parsed:
        label = signal_type or "signal"
        yield label, parsed


def link(
    signals: list[dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    proximity_months: float = DEFAULT_PROXIMITY_MONTHS,
) -> dict[str, Any]:
    """Link signals to events via temporal proximity.

    Returns a dict with:
    - ``links``: list of ``{signal_id, event_id, link_type, score, anchor, months_apart}``
      (one row per matched signal anchor; the closest anchor wins per signal/event pair).
    - ``unlinked_signals``: signal ids with no event within proximity window.
    - ``unlinked_events``: event ids with no signal within proximity window.
    - ``proximity_months``: window used.
    """
    links: list[dict[str, Any]] = []
    matched_signal_ids: set[str] = set()
    matched_event_ids: set[str] = set()

    signal_anchor_index: list[tuple[str, list[tuple[str, date]]]] = []
    for signal in signals:
        sid = str(signal.get("id") or "").strip()
        if not sid:
            continue
        anchors = list(_signal_anchor_dates(signal))
        signal_anchor_index.append((sid, anchors))

    for event in events:
        eid = str(event.get("id") or "").strip()
        if not eid:
            continue
        event_date = _parse_date(event.get("date"))
        if event_date is None:
            continue
        for sid, anchors in signal_anchor_index:
            if not anchors:
                continue
            best: tuple[str, float] | None = None
            for anchor_label, anchor_date in anchors:
                gap = _months_between(event_date, anchor_date)
                if gap > proximity_months:
                    continue
                if best is None or gap < best[1]:
                    best = (anchor_label, gap)
            if best is None:
                continue
            anchor_label, months_apart = best
            score = max(0.0, 1.0 - months_apart / proximity_months)
            links.append(
                {
                    "signal_id": sid,
                    "event_id": eid,
                    "link_type": "temporal",
                    "score": round(score, 3),
                    "anchor": anchor_label,
                    "months_apart": round(months_apart, 2),
                }
            )
            matched_signal_ids.add(sid)
            matched_event_ids.add(eid)

    all_signal_ids = {
        str(s.get("id") or "").strip() for s in signals if str(s.get("id") or "").strip()
    }
    all_event_ids = {
        str(e.get("id") or "").strip() for e in events if str(e.get("id") or "").strip()
    }
    unlinked_signals = sorted(all_signal_ids - matched_signal_ids)
    unlinked_events = sorted(all_event_ids - matched_event_ids)

    return {
        "links": links,
        "unlinked_signals": unlinked_signals,
        "unlinked_events": unlinked_events,
        "proximity_months": proximity_months,
    }
