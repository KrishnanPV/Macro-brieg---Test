"""Tests for signal_event_linker against the new flat-signal schema."""
from __future__ import annotations

from typing import Any

from backend.insights_pipeline.stages.signal_event_linker import (
    _signal_anchor_dates,
    link,
)


def _signal(
    *,
    sig_id: str,
    signal_type: str,
    period_end: str = "2020-01",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": sig_id,
        "signal_type": signal_type,
        "kpi": "K",
        "kpi_id": "1",
        "country": "SAU",
        "frequency": "M",
        "unit": "%",
        "period_start": "2014-01",
        "period_end": period_end,
        "period_length_months": 12,
        "start_value": 1.0,
        "end_value": 2.0,
        "abs_change": 1.0,
        "pct_change": 1.0,
        "direction": "up",
        "metrics": dict(metrics or {}),
    }


def _event(eid: str, date: str) -> dict[str, Any]:
    return {
        "id": eid,
        "date": date,
        "title": "t",
        "summary": "s",
        "url": "https://r.com/x",
        "actor": "A",
        "action": "did",
    }


# ---------------------------------------------------------------------------
# Anchor selection per signal_type
# ---------------------------------------------------------------------------

def test_spike_anchors_on_metrics_pivot_date():
    sig = _signal(
        sig_id="sig_1",
        signal_type="spike",
        period_end="2021-12",
        metrics={
            "z_score": 2.0,
            "series_mean": 1.0,
            "series_stdev": 0.5,
            "pivot_date": "2020-03",
        },
    )
    anchors = list(_signal_anchor_dates(sig))
    assert len(anchors) == 1
    label, anchor_date = anchors[0]
    assert label == "spike"
    assert anchor_date.year == 2020 and anchor_date.month == 3


def test_turning_point_falls_back_to_period_end_when_pivot_date_missing():
    sig = _signal(
        sig_id="sig_1",
        signal_type="turning_point",
        period_end="2022-06",
        metrics={
            "kind": "peak",
            "pivot_date": "",
            "pivot_value": 0.0,
            "swing": 0.0,
        },
    )
    anchors = list(_signal_anchor_dates(sig))
    assert len(anchors) == 1
    label, anchor_date = anchors[0]
    assert label == "turning_point"
    assert anchor_date.year == 2022 and anchor_date.month == 6


def test_phase_trend_anchors_on_period_end():
    sig = _signal(sig_id="sig_1", signal_type="phase_trend", period_end="2019-09")
    anchors = list(_signal_anchor_dates(sig))
    assert len(anchors) == 1
    label, anchor_date = anchors[0]
    assert label == "phase_trend"
    assert anchor_date.year == 2019 and anchor_date.month == 9


def test_signal_with_no_parseable_date_yields_nothing():
    sig = _signal(sig_id="sig_1", signal_type="phase_trend", period_end="not-a-date")
    anchors = list(_signal_anchor_dates(sig))
    assert anchors == []


# ---------------------------------------------------------------------------
# link() against the new schema
# ---------------------------------------------------------------------------

def test_spike_links_to_event_within_proximity_window():
    sig = _signal(
        sig_id="sig_1",
        signal_type="spike",
        period_end="2020-12",
        metrics={
            "z_score": 2.0,
            "series_mean": 1.0,
            "series_stdev": 0.5,
            "pivot_date": "2020-03",
        },
    )
    ev = _event("ev_1", "2020-04-15")
    output = link([sig], [ev])
    assert len(output["links"]) == 1
    assert output["links"][0]["signal_id"] == "sig_1"
    assert output["links"][0]["event_id"] == "ev_1"
    assert output["links"][0]["anchor"] == "spike"


def test_phase_trend_links_via_period_end():
    sig = _signal(sig_id="sig_1", signal_type="phase_trend", period_end="2021-06")
    ev = _event("ev_1", "2021-06-20")
    output = link([sig], [ev])
    assert len(output["links"]) == 1
    assert output["links"][0]["anchor"] == "phase_trend"


def test_unanchored_signal_appears_in_unlinked_signals():
    sig = _signal(sig_id="sig_1", signal_type="phase_trend", period_end="garbage")
    ev = _event("ev_1", "2020-04-15")
    output = link([sig], [ev])
    assert output["links"] == []
    assert "sig_1" in output["unlinked_signals"]


def test_event_outside_window_is_unlinked():
    sig = _signal(sig_id="sig_1", signal_type="phase_trend", period_end="2014-01")
    ev_far = _event("ev_far", "2024-01-15")
    output = link([sig], [ev_far])
    assert output["links"] == []
    assert "ev_far" in output["unlinked_events"]
