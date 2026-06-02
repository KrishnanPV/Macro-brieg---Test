"""Schema and behaviour tests for the signal-graph layer."""
from __future__ import annotations

import pytest

from backend.insights_pipeline.stages.signal_graph import (
    GROUP_KEYS,
    GROUP_TYPES,
    MEMBER_KEYS,
    MEMBER_ROLES,
    NET_DIRECTIONS,
    _make_group,
    _make_member,
    build_groups,
)


def _signal(sig_id: str, kpi_id: str, direction: str = "up") -> dict[str, object]:
    """Minimal signal fixture (only the fields the graph layer reads)."""
    return {"id": sig_id, "kpi_id": kpi_id, "direction": direction}


# Three signals whose KPIs collectively populate every group_type:
# - KPI 3 (growth family, growth channel, parent of two identities)
# - KPI 2 (growth family, oil_sector + domestic_demand channels, component of real_gdp_split)
# - KPI 11 (growth family, growth + domestic_demand channels, component of growth_sector_decomposition)
_SIGNALS = [
    _signal("sig_001", "3", direction="up"),
    _signal("sig_002", "2", direction="up"),
    _signal("sig_003", "11", direction="up"),
]


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------

def test_every_group_has_exact_group_keys_in_order():
    for group in build_groups(_SIGNALS):
        assert tuple(group.keys()) == GROUP_KEYS


def test_group_type_and_net_direction_in_closed_enums():
    for group in build_groups(_SIGNALS):
        assert group["group_type"] in GROUP_TYPES
        assert group["net_direction"] in NET_DIRECTIONS


def test_member_dicts_have_exact_keys_and_valid_role():
    for group in build_groups(_SIGNALS):
        for member in group["members"]:
            assert tuple(member.keys()) == MEMBER_KEYS
            assert member["role"] in MEMBER_ROLES


def test_size_equals_member_count_for_every_group():
    for group in build_groups(_SIGNALS):
        assert group["size"] == len(group["members"])


# ---------------------------------------------------------------------------
# Role-by-group_type rules
# ---------------------------------------------------------------------------

def test_family_and_channel_members_are_all_role_member():
    for group in build_groups(_SIGNALS):
        if group["group_type"] in {"family", "channel"}:
            assert all(m["role"] == "member" for m in group["members"])


def test_identity_groups_have_exactly_one_parent():
    identity_groups = [g for g in build_groups(_SIGNALS) if g["group_type"] == "identity"]
    assert identity_groups, "Fixture should populate at least one identity group"
    for group in identity_groups:
        parents = [m for m in group["members"] if m["role"] == "parent"]
        components = [m for m in group["members"] if m["role"] == "component"]
        assert len(parents) == 1
        assert components, "identity group must include at least one component"


# ---------------------------------------------------------------------------
# Singleton drop
# ---------------------------------------------------------------------------

def test_singletons_are_dropped():
    # Only one KPI represented -> nothing can reach size >= 2.
    assert build_groups([_signal("sig_001", "3")]) == []
    # No KPI ids at all -> nothing.
    assert build_groups([_signal("sig_001", "")]) == []


def test_no_group_with_size_less_than_two_ever_emitted():
    for group in build_groups(_SIGNALS):
        assert group["size"] >= 2


# ---------------------------------------------------------------------------
# Multi-membership: one KPI must appear in every group its tags qualify it for
# ---------------------------------------------------------------------------

def test_kpi3_appears_in_family_channel_and_both_identities():
    groups = build_groups(_SIGNALS)
    groups_containing_kpi3 = [
        g for g in groups if any(m["kpi_id"] == "3" for m in g["members"])
    ]
    group_ids = {g["group_id"] for g in groups_containing_kpi3}
    assert "family:growth" in group_ids
    assert "channel:growth" in group_ids
    assert "identity:real_gdp_split" in group_ids
    assert "identity:growth_sector_decomposition" in group_ids
    assert len(group_ids) >= 4


def test_kpi3_signal_ids_propagate_into_every_group_it_belongs_to():
    groups = build_groups(_SIGNALS)
    for group in groups:
        for member in group["members"]:
            if member["kpi_id"] == "3":
                assert "sig_001" in member["signal_ids"]


def test_kpi3_role_is_parent_in_identity_groups_and_member_elsewhere():
    for group in build_groups(_SIGNALS):
        for member in group["members"]:
            if member["kpi_id"] != "3":
                continue
            if group["group_type"] == "identity":
                assert member["role"] == "parent"
            else:
                assert member["role"] == "member"


# ---------------------------------------------------------------------------
# net_direction rollup
# ---------------------------------------------------------------------------

def test_net_direction_is_up_when_all_signals_are_up():
    groups = build_groups(_SIGNALS)
    family_growth = next(g for g in groups if g["group_id"] == "family:growth")
    assert family_growth["net_direction"] == "up"


def test_net_direction_is_mixed_when_signals_disagree():
    signals = [
        _signal("sig_001", "3", direction="up"),
        _signal("sig_002", "2", direction="down"),
    ]
    groups = build_groups(signals)
    family_growth = next(g for g in groups if g["group_id"] == "family:growth")
    assert family_growth["net_direction"] == "mixed"


# ---------------------------------------------------------------------------
# Enforcement: _make_group and _make_member reject drift
# ---------------------------------------------------------------------------

def test_make_member_rejects_unknown_role():
    with pytest.raises(ValueError):
        _make_member(kpi_id="3", role="captain", signal_ids=["sig_001"])


def test_make_group_rejects_unknown_group_type():
    member = _make_member(kpi_id="3", role="member", signal_ids=["sig_001"])
    with pytest.raises(ValueError):
        _make_group(
            group_type="cluster",
            tag="x",
            label="x",
            members=[member, member],
            net_direction="up",
        )


def test_make_group_rejects_unknown_net_direction():
    member = _make_member(kpi_id="3", role="member", signal_ids=["sig_001"])
    with pytest.raises(ValueError):
        _make_group(
            group_type="family",
            tag="x",
            label="x",
            members=[member, member],
            net_direction="sideways",
        )


def test_make_group_rejects_parent_role_outside_identity():
    parent_like = _make_member(kpi_id="3", role="parent", signal_ids=["sig_001"])
    member = _make_member(kpi_id="2", role="member", signal_ids=["sig_002"])
    with pytest.raises(ValueError):
        _make_group(
            group_type="family",
            tag="growth",
            label="Growth",
            members=[parent_like, member],
            net_direction="up",
        )


def test_make_group_rejects_two_parents_in_identity():
    parent_a = _make_member(kpi_id="3", role="parent", signal_ids=["sig_001"])
    parent_b = _make_member(kpi_id="4", role="parent", signal_ids=["sig_002"])
    with pytest.raises(ValueError):
        _make_group(
            group_type="identity",
            tag="duo",
            label="Duo",
            members=[parent_a, parent_b],
            net_direction="up",
        )


def test_make_group_rejects_member_role_inside_identity():
    member = _make_member(kpi_id="3", role="member", signal_ids=["sig_001"])
    component = _make_member(kpi_id="2", role="component", signal_ids=["sig_002"])
    with pytest.raises(ValueError):
        _make_group(
            group_type="identity",
            tag="bad",
            label="Bad",
            members=[member, component],
            net_direction="up",
        )
