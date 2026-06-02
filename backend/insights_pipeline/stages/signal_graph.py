"""Signal-graph layer: cluster signals by static KPI relationship tags.

Takes the flat signal list emitted by ``signal_extractor`` and emits a flat
list of ``SignalGroup`` dicts, one per (family | identity | channel) tag that
has at least two distinct KPIs represented. No LLM. No materialised pairwise
edges (consumers that want edges expand ``group.members x group.members``).

The output shape is locked the same way the signal schema is locked:
``_make_group`` is the single constructor and rejects any drift with
``ValueError``.
"""
from __future__ import annotations

from typing import Any

from backend.models.kpi_relationships import (
    ACCOUNTING_IDENTITIES,
    CHANNEL_LABELS,
    FAMILY_LABELS,
    KPI_CHANNELS,
    KPI_FAMILY,
)


# ---------------------------------------------------------------------------
# Locked group schema constants
# ---------------------------------------------------------------------------

GROUP_KEYS: tuple[str, ...] = (
    "group_id", "group_type", "label", "members", "net_direction", "size",
)
GROUP_TYPES: frozenset[str] = frozenset({"family", "identity", "channel"})

MEMBER_KEYS: tuple[str, ...] = ("kpi_id", "role", "signal_ids")
MEMBER_ROLES: frozenset[str] = frozenset({"parent", "component", "member"})

NET_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "flat", "mixed"})

_MIN_GROUP_SIZE: int = 2

# ---------------------------------------------------------------------------
# Locked attached-group schema (separate view, not a mutation of GROUP_KEYS)
# ---------------------------------------------------------------------------

ATTACHED_GROUP_KEYS: tuple[str, ...] = (
    "group_id", "group_type", "label",
    "net_direction", "size",
    "members", "signals",
)
ATTACHED_MEMBER_KEYS: tuple[str, ...] = ("kpi_id", "role")


# ---------------------------------------------------------------------------
# Constructors with enforcement
# ---------------------------------------------------------------------------

def _make_member(kpi_id: str, role: str, signal_ids: list[str]) -> dict[str, Any]:
    if role not in MEMBER_ROLES:
        raise ValueError(
            f"member role={role!r} not in {sorted(MEMBER_ROLES)}."
        )
    member: dict[str, Any] = {
        "kpi_id": str(kpi_id),
        "role": role,
        "signal_ids": list(signal_ids),
    }
    if tuple(member.keys()) != MEMBER_KEYS:
        raise ValueError(
            f"member key order must be {MEMBER_KEYS}; got {tuple(member.keys())}."
        )
    return member


def _make_group(
    *,
    group_type: str,
    tag: str,
    label: str,
    members: list[dict[str, Any]],
    net_direction: str,
) -> dict[str, Any]:
    if group_type not in GROUP_TYPES:
        raise ValueError(
            f"group_type={group_type!r} not in {sorted(GROUP_TYPES)}."
        )
    if net_direction not in NET_DIRECTIONS:
        raise ValueError(
            f"net_direction={net_direction!r} not in {sorted(NET_DIRECTIONS)}."
        )

    parent_count = 0
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("members must be dicts.")
        if tuple(member.keys()) != MEMBER_KEYS:
            raise ValueError(
                f"member keys must be {MEMBER_KEYS}; got {tuple(member.keys())}."
            )
        if member["role"] not in MEMBER_ROLES:
            raise ValueError(
                f"member role={member['role']!r} not in {sorted(MEMBER_ROLES)}."
            )
        if group_type == "identity":
            if member["role"] not in {"parent", "component"}:
                raise ValueError(
                    f"identity group members must have role in {{parent, component}}; "
                    f"got {member['role']!r}."
                )
            if member["role"] == "parent":
                parent_count += 1
        else:
            if member["role"] != "member":
                raise ValueError(
                    f"{group_type} group members must have role 'member'; "
                    f"got {member['role']!r}."
                )
    if group_type == "identity" and parent_count > 1:
        raise ValueError(
            f"identity group {tag!r} has {parent_count} parents; expected at most 1."
        )

    size = len(members)
    group: dict[str, Any] = {
        "group_id": f"{group_type}:{tag}",
        "group_type": group_type,
        "label": str(label),
        "members": list(members),
        "net_direction": net_direction,
        "size": size,
    }
    if tuple(group.keys()) != GROUP_KEYS:
        raise ValueError(
            f"group key order must be {GROUP_KEYS}; got {tuple(group.keys())}."
        )
    if group["size"] != len(group["members"]):
        raise ValueError(
            f"group size {group['size']} != len(members) {len(group['members'])}."
        )
    return group


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bucket_signals_by_kpi(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Return ``{kpi_id: [signal, ...]}`` in input order, skipping blank kpi_ids."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for signal in signals:
        kpi_id = str(signal.get("kpi_id") or "").strip()
        if not kpi_id:
            continue
        buckets.setdefault(kpi_id, []).append(signal)
    return buckets


def _net_direction(member_signals: list[dict[str, Any]]) -> str:
    """All-up -> up, all-down -> down, all-flat -> flat, otherwise mixed.

    ``volatile`` / ``reversing_*`` signal directions always fall through to
    ``mixed`` because they do not map cleanly to a single net polarity.
    """
    directions = [str(s.get("direction") or "") for s in member_signals]
    if not directions:
        return "mixed"
    unique = set(directions)
    if unique == {"up"}:
        return "up"
    if unique == {"down"}:
        return "down"
    if unique == {"flat"}:
        return "flat"
    return "mixed"


def _flat_signals_for_member(
    kpi_id: str,
    buckets: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return list(buckets.get(kpi_id, []))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_groups(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster the flat signal list into SignalGroups.

    Returns groups in a stable order: families first (alphabetical by tag),
    then identities (insertion order from ``ACCOUNTING_IDENTITIES``), then
    channels (alphabetical by tag). Groups with fewer than two distinct KPIs
    are dropped.
    """
    buckets = _bucket_signals_by_kpi(signals)
    if not buckets:
        return []
    represented_kpi_ids = set(buckets.keys())

    groups: list[dict[str, Any]] = []

    # Families
    family_to_kpis: dict[str, list[str]] = {}
    for kpi_id, family in KPI_FAMILY.items():
        if kpi_id not in represented_kpi_ids:
            continue
        family_to_kpis.setdefault(family, []).append(kpi_id)
    for family in sorted(family_to_kpis):
        kpis = sorted(family_to_kpis[family])
        if len(kpis) < _MIN_GROUP_SIZE:
            continue
        members: list[dict[str, Any]] = []
        all_member_signals: list[dict[str, Any]] = []
        for kpi_id in kpis:
            member_signals = _flat_signals_for_member(kpi_id, buckets)
            all_member_signals.extend(member_signals)
            members.append(
                _make_member(
                    kpi_id=kpi_id,
                    role="member",
                    signal_ids=[s["id"] for s in member_signals],
                )
            )
        groups.append(
            _make_group(
                group_type="family",
                tag=family,
                label=FAMILY_LABELS.get(family, family),
                members=members,
                net_direction=_net_direction(all_member_signals),
            )
        )

    # Identities (preserve declaration order from ACCOUNTING_IDENTITIES).
    for identity_id, spec in ACCOUNTING_IDENTITIES.items():
        parent_kpi_id = str(spec.get("parent_kpi_id") or "").strip()
        component_kpi_ids = [str(k) for k in spec.get("component_kpi_ids", [])]
        candidate_kpis: list[tuple[str, str]] = []
        if parent_kpi_id and parent_kpi_id in represented_kpi_ids:
            candidate_kpis.append((parent_kpi_id, "parent"))
        for component_id in component_kpi_ids:
            if component_id in represented_kpi_ids and component_id != parent_kpi_id:
                candidate_kpis.append((component_id, "component"))
        if len(candidate_kpis) < _MIN_GROUP_SIZE:
            continue
        members = []
        all_member_signals = []
        for kpi_id, role in candidate_kpis:
            member_signals = _flat_signals_for_member(kpi_id, buckets)
            all_member_signals.extend(member_signals)
            members.append(
                _make_member(
                    kpi_id=kpi_id,
                    role=role,
                    signal_ids=[s["id"] for s in member_signals],
                )
            )
        groups.append(
            _make_group(
                group_type="identity",
                tag=identity_id,
                label=str(spec.get("label") or identity_id),
                members=members,
                net_direction=_net_direction(all_member_signals),
            )
        )

    # Channels
    channel_to_kpis: dict[str, list[str]] = {}
    for kpi_id, channels in KPI_CHANNELS.items():
        if kpi_id not in represented_kpi_ids:
            continue
        for channel in channels:
            channel_to_kpis.setdefault(channel, []).append(kpi_id)
    for channel in sorted(channel_to_kpis):
        kpis = sorted(channel_to_kpis[channel])
        if len(kpis) < _MIN_GROUP_SIZE:
            continue
        members = []
        all_member_signals = []
        for kpi_id in kpis:
            member_signals = _flat_signals_for_member(kpi_id, buckets)
            all_member_signals.extend(member_signals)
            members.append(
                _make_member(
                    kpi_id=kpi_id,
                    role="member",
                    signal_ids=[s["id"] for s in member_signals],
                )
            )
        groups.append(
            _make_group(
                group_type="channel",
                tag=channel,
                label=CHANNEL_LABELS.get(channel, channel),
                members=members,
                net_direction=_net_direction(all_member_signals),
            )
        )

    return groups


# ---------------------------------------------------------------------------
# Attached-group view (groups with full Signal dicts embedded)
# ---------------------------------------------------------------------------

def _make_attached_member(kpi_id: str, role: str) -> dict[str, Any]:
    if role not in MEMBER_ROLES:
        raise ValueError(
            f"attached member role={role!r} not in {sorted(MEMBER_ROLES)}."
        )
    member: dict[str, Any] = {
        "kpi_id": str(kpi_id),
        "role": role,
    }
    if tuple(member.keys()) != ATTACHED_MEMBER_KEYS:
        raise ValueError(
            f"attached member key order must be {ATTACHED_MEMBER_KEYS}; "
            f"got {tuple(member.keys())}."
        )
    return member


def _make_attached_group(
    *,
    group_id: str,
    group_type: str,
    label: str,
    net_direction: str,
    size: int,
    members: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    if group_type not in GROUP_TYPES:
        raise ValueError(
            f"attached group_type={group_type!r} not in {sorted(GROUP_TYPES)}."
        )
    if net_direction not in NET_DIRECTIONS:
        raise ValueError(
            f"attached net_direction={net_direction!r} not in {sorted(NET_DIRECTIONS)}."
        )
    for member in members:
        if not isinstance(member, dict):
            raise ValueError("attached members must be dicts.")
        if tuple(member.keys()) != ATTACHED_MEMBER_KEYS:
            raise ValueError(
                f"attached member keys must be {ATTACHED_MEMBER_KEYS}; "
                f"got {tuple(member.keys())}."
            )
        if member["role"] not in MEMBER_ROLES:
            raise ValueError(
                f"attached member role={member['role']!r} not in {sorted(MEMBER_ROLES)}."
            )
    if size != len(members):
        raise ValueError(
            f"attached group size {size} != len(members) {len(members)}."
        )
    attached: dict[str, Any] = {
        "group_id": str(group_id),
        "group_type": group_type,
        "label": str(label),
        "net_direction": net_direction,
        "size": size,
        "members": list(members),
        "signals": list(signals),
    }
    if tuple(attached.keys()) != ATTACHED_GROUP_KEYS:
        raise ValueError(
            f"attached group key order must be {ATTACHED_GROUP_KEYS}; "
            f"got {tuple(attached.keys())}."
        )
    return attached


def attach_signals(
    groups: list[dict[str, Any]],
    signals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a new list where each group carries the full Signal dicts
    referenced by its ``members[].signal_ids``.

    The original ``groups`` / ``signals`` lists are not mutated. Signals
    whose ``id`` is not referenced by any group are dropped from this view.
    Output preserves the order of ``signals`` for deterministic fixtures.
    """
    signal_by_id: dict[str, dict[str, Any]] = {}
    signal_order: dict[str, int] = {}
    for idx, signal in enumerate(signals):
        sig_id = str(signal.get("id") or "")
        if not sig_id:
            continue
        signal_by_id[sig_id] = signal
        signal_order[sig_id] = idx

    attached_groups: list[dict[str, Any]] = []
    for group in groups:
        if tuple(group.keys()) != GROUP_KEYS:
            raise ValueError(
                f"input group keys must be {GROUP_KEYS}; got {tuple(group.keys())}."
            )
        members_view: list[dict[str, Any]] = []
        referenced_ids: list[str] = []
        for member in group.get("members", []):
            if tuple(member.keys()) != MEMBER_KEYS:
                raise ValueError(
                    f"input member keys must be {MEMBER_KEYS}; "
                    f"got {tuple(member.keys())}."
                )
            members_view.append(
                _make_attached_member(
                    kpi_id=str(member["kpi_id"]),
                    role=str(member["role"]),
                )
            )
            for sig_id in member.get("signal_ids", []):
                sig_id_str = str(sig_id)
                if sig_id_str in signal_by_id:
                    referenced_ids.append(sig_id_str)

        seen: set[str] = set()
        ordered_unique_ids: list[str] = []
        for sig_id in referenced_ids:
            if sig_id in seen:
                continue
            seen.add(sig_id)
            ordered_unique_ids.append(sig_id)
        ordered_unique_ids.sort(key=lambda sid: signal_order[sid])
        attached_signals = [dict(signal_by_id[sid]) for sid in ordered_unique_ids]

        attached_groups.append(
            _make_attached_group(
                group_id=str(group["group_id"]),
                group_type=str(group["group_type"]),
                label=str(group["label"]),
                net_direction=str(group["net_direction"]),
                size=int(group["size"]),
                members=members_view,
                signals=attached_signals,
            )
        )
    return attached_groups
