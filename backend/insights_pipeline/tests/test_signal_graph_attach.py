"""Tests for the attach_signals view (groups with embedded Signal dicts)."""
from __future__ import annotations

import pytest

from backend.insights_pipeline.stages.signal_graph import (
    ATTACHED_GROUP_KEYS,
    ATTACHED_MEMBER_KEYS,
    _make_attached_group,
    _make_attached_member,
    attach_signals,
    build_groups,
)


def _signal(sig_id: str, kpi_id: str, direction: str = "up") -> dict[str, object]:
    """Full Signal dict with the fields the join inspects."""
    return {
        "id": sig_id,
        "signal_type": "long_term_trend",
        "kpi": f"KPI {kpi_id}",
        "kpi_id": kpi_id,
        "country": "SAU",
        "frequency": "A",
        "unit": "%",
        "period_start": "2014-01",
        "period_end": "2023-01",
        "period_length_months": 108,
        "start_value": 1.0,
        "end_value": 2.0,
        "abs_change": 1.0,
        "pct_change": 1.0,
        "direction": direction,
        "metrics": {},
    }


# Three signals whose KPIs populate family + channel + identity groups.
_SIGNALS = [
    _signal("sig_001", "3", direction="up"),
    _signal("sig_002", "2", direction="up"),
    _signal("sig_003", "11", direction="up"),
]


# ---------------------------------------------------------------------------
# Shape enforcement
# ---------------------------------------------------------------------------

def test_every_attached_group_has_exact_keys_in_order():
    groups = build_groups(_SIGNALS)
    attached = attach_signals(groups, _SIGNALS)
    assert attached, "fixture should produce at least one group"
    for group in attached:
        assert tuple(group.keys()) == ATTACHED_GROUP_KEYS


def test_attached_members_have_exact_keys_in_order():
    groups = build_groups(_SIGNALS)
    attached = attach_signals(groups, _SIGNALS)
    for group in attached:
        for member in group["members"]:
            assert tuple(member.keys()) == ATTACHED_MEMBER_KEYS


def test_attached_group_size_matches_member_count():
    groups = build_groups(_SIGNALS)
    attached = attach_signals(groups, _SIGNALS)
    for group in attached:
        assert group["size"] == len(group["members"])


# ---------------------------------------------------------------------------
# Multi-membership: a signal whose KPI sits in N groups appears in all N
# ---------------------------------------------------------------------------

def test_signal_for_multi_tag_kpi_is_embedded_in_every_group_it_belongs_to():
    groups = build_groups(_SIGNALS)
    attached = attach_signals(groups, _SIGNALS)
    groups_with_sig_001 = [
        g
        for g in attached
        if any(s["id"] == "sig_001" for s in g["signals"])
    ]
    group_ids = {g["group_id"] for g in groups_with_sig_001}
    assert "family:growth" in group_ids
    assert "channel:growth" in group_ids
    assert "identity:real_gdp_split" in group_ids
    assert "identity:growth_sector_decomposition" in group_ids
    assert len(group_ids) >= 4


def test_attach_signals_does_not_mutate_inputs():
    groups = build_groups(_SIGNALS)
    pre_group_keys = [tuple(g.keys()) for g in groups]
    pre_signal_keys = [tuple(s.keys()) for s in _SIGNALS]
    attach_signals(groups, _SIGNALS)
    assert [tuple(g.keys()) for g in groups] == pre_group_keys
    assert [tuple(s.keys()) for s in _SIGNALS] == pre_signal_keys


# ---------------------------------------------------------------------------
# Unreferenced-signal drop
# ---------------------------------------------------------------------------

def test_signal_not_referenced_by_any_group_is_dropped_from_every_view():
    extra = _signal("sig_999", "9", direction="up")
    signals = list(_SIGNALS) + [extra]
    groups = build_groups(signals)
    attached = attach_signals(groups, signals)
    for group in attached:
        for embedded in group["signals"]:
            assert embedded["id"] != "sig_999"


def test_attached_signal_dicts_are_copies_not_aliases():
    groups = build_groups(_SIGNALS)
    attached = attach_signals(groups, _SIGNALS)
    for group in attached:
        for embedded in group["signals"]:
            for original in _SIGNALS:
                if embedded["id"] == original["id"]:
                    assert embedded is not original


# ---------------------------------------------------------------------------
# Constructor enforcement (parallel posture to _make_group / _make_signal)
# ---------------------------------------------------------------------------

def test_make_attached_member_rejects_unknown_role():
    with pytest.raises(ValueError):
        _make_attached_member(kpi_id="3", role="captain")


def test_make_attached_group_rejects_unknown_group_type():
    member = _make_attached_member(kpi_id="3", role="member")
    with pytest.raises(ValueError):
        _make_attached_group(
            group_id="cluster:x",
            group_type="cluster",
            label="x",
            net_direction="up",
            size=2,
            members=[member, member],
            signals=[],
        )


def test_make_attached_group_rejects_unknown_net_direction():
    member = _make_attached_member(kpi_id="3", role="member")
    with pytest.raises(ValueError):
        _make_attached_group(
            group_id="family:x",
            group_type="family",
            label="x",
            net_direction="sideways",
            size=2,
            members=[member, member],
            signals=[],
        )


def test_make_attached_group_rejects_size_mismatch():
    member = _make_attached_member(kpi_id="3", role="member")
    with pytest.raises(ValueError):
        _make_attached_group(
            group_id="family:x",
            group_type="family",
            label="x",
            net_direction="up",
            size=3,
            members=[member, member],
            signals=[],
        )


def test_attach_signals_rejects_input_group_with_wrong_keys():
    bad_group = {"group_id": "family:x"}
    with pytest.raises(ValueError):
        attach_signals([bad_group], _SIGNALS)
