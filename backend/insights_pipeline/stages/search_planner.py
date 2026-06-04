"""Budgeted search-query planner for the grouped-hypotheses flow.

Consumes the ``document`` emitted by ``hypotheses_generator.run_step_groups``
and returns a flat list of planned queries, capped at a configurable budget
(default 8, clamped to ``[6, 10]``). Allocation is deterministic and pure --
no LLM, no I/O.

Allocation rules (in order):
1. Cross-group hypotheses first (each ``preferred_search_query`` is one call
   that covers multiple groups via ``search_once``).
2. Then a round-robin across ``hypothesis_groups``: one query per group, then
   loop again, until the budget is exhausted. Within a group, queries are
   picked from the highest-priority hypothesis first.
3. ``hypothesis_type == "null_data_hypothesis"`` is skipped entirely (its
   ``neutral_search_queries`` is empty by construction).
4. Queries are deduped case-insensitively against everything already planned.

Output shape per planned query is locked via ``PLANNED_QUERY_KEYS`` and the
single constructor ``_make_planned_query`` -- same posture as ``_make_signal``
and ``_make_attached_group``.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Locked output schema
# ---------------------------------------------------------------------------

PLANNED_QUERY_KEYS: tuple[str, ...] = (
    "query_id",
    "query",
    "source",
    "hypothesis_id",
    "group_ids",
    "priority",
    "search_priority_rank",
)
QUERY_SOURCES: frozenset[str] = frozenset({"cross_group", "hypothesis"})
QUERY_PRIORITIES: frozenset[str] = frozenset({"high", "medium", "low"})

DEFAULT_BUDGET: int = 8
MIN_BUDGET: int = 6
MAX_BUDGET: int = 10

_PRIORITY_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
_RANK_TO_PRIORITY: tuple[str, str, str] = ("high", "medium", "low")


# ---------------------------------------------------------------------------
# Constructor with enforcement
# ---------------------------------------------------------------------------

def _make_planned_query(
    *,
    query_id: str,
    query: str,
    source: str,
    hypothesis_id: str,
    group_ids: list[str],
    priority: str,
    search_priority_rank: int,
) -> dict[str, Any]:
    if source not in QUERY_SOURCES:
        raise ValueError(
            f"planned-query source={source!r} not in {sorted(QUERY_SOURCES)}."
        )
    if priority not in QUERY_PRIORITIES:
        raise ValueError(
            f"planned-query priority={priority!r} not in {sorted(QUERY_PRIORITIES)}."
        )
    if not isinstance(search_priority_rank, int) or search_priority_rank < 0:
        raise ValueError(
            f"search_priority_rank must be a non-negative int; got "
            f"{search_priority_rank!r}."
        )
    planned: dict[str, Any] = {
        "query_id": str(query_id),
        "query": str(query),
        "source": source,
        "hypothesis_id": str(hypothesis_id),
        "group_ids": [str(g) for g in group_ids],
        "priority": priority,
        "search_priority_rank": search_priority_rank,
    }
    if tuple(planned.keys()) != PLANNED_QUERY_KEYS:
        raise ValueError(
            f"planned-query key order must be {PLANNED_QUERY_KEYS}; "
            f"got {tuple(planned.keys())}."
        )
    return planned


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _clamp_budget(budget: int) -> int:
    try:
        b = int(budget)
    except (TypeError, ValueError):
        b = DEFAULT_BUDGET
    if b < MIN_BUDGET:
        return MIN_BUDGET
    if b > MAX_BUDGET:
        return MAX_BUDGET
    return b


def _is_useful_query(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _build_group_queues(
    hypothesis_groups: list[dict[str, Any]],
) -> dict[str, list[tuple[int, str, str]]]:
    """Return ``{group_id: [(rank, hypothesis_id, query), ...]}`` sorted by rank."""
    queues: dict[str, list[tuple[int, str, str]]] = {}
    for group in hypothesis_groups:
        group_id = str(group.get("group_id") or "")
        if not group_id:
            continue
        bucket: list[tuple[int, str, str]] = []
        for hyp in group.get("hypotheses") or []:
            if str(hyp.get("hypothesis_type") or "") == "null_data_hypothesis":
                continue
            priority = str(hyp.get("search_priority") or "low")
            rank = _PRIORITY_RANK.get(priority, _PRIORITY_RANK["low"])
            hyp_id = str(hyp.get("hypothesis_id") or "")
            for raw_q in hyp.get("neutral_search_queries") or []:
                if not _is_useful_query(raw_q):
                    continue
                bucket.append((rank, hyp_id, str(raw_q).strip()))
        bucket.sort(key=lambda t: t[0])
        queues[group_id] = bucket
    return queues


def plan_searches(
    document: dict[str, Any],
    *,
    budget: int = DEFAULT_BUDGET,
) -> list[dict[str, Any]]:
    """Pick a budget-bounded set of search queries from a hypotheses document.

    Returns ``[]`` for an empty document. Otherwise returns at most ``budget``
    planned queries (clamped to ``[MIN_BUDGET, MAX_BUDGET]``).
    """
    budget_capped = _clamp_budget(budget)
    if not isinstance(document, dict):
        return []

    planned: list[dict[str, Any]] = []
    used_query_strings: set[str] = set()
    counter = 0

    def _next_id() -> str:
        nonlocal counter
        counter += 1
        return f"q_{counter:03d}"

    # Pass A: cross-group hypotheses first.
    for cross in document.get("cross_group_hypotheses") or []:
        if len(planned) >= budget_capped:
            break
        if not isinstance(cross, dict):
            continue
        q = str(cross.get("preferred_search_query") or "").strip()
        if not q:
            continue
        key = q.lower()
        if key in used_query_strings:
            continue
        related_groups = [
            str(g) for g in (cross.get("related_groups") or []) if str(g).strip()
        ]
        if not related_groups:
            continue
        planned.append(
            _make_planned_query(
                query_id=_next_id(),
                query=q,
                source="cross_group",
                hypothesis_id="",
                group_ids=related_groups,
                priority="high",
                search_priority_rank=_PRIORITY_RANK["high"],
            )
        )
        used_query_strings.add(key)

    # Pass B: round-robin across groups.
    queues = _build_group_queues(document.get("hypothesis_groups") or [])
    group_order = [
        str(g.get("group_id") or "")
        for g in document.get("hypothesis_groups") or []
        if str(g.get("group_id") or "")
    ]

    while len(planned) < budget_capped and any(queues.get(gid) for gid in group_order):
        progress = False
        for group_id in group_order:
            if len(planned) >= budget_capped:
                break
            bucket = queues.get(group_id) or []
            while bucket:
                rank, hyp_id, q = bucket.pop(0)
                key = q.lower()
                if key in used_query_strings:
                    continue
                priority = _RANK_TO_PRIORITY[rank] if 0 <= rank < len(_RANK_TO_PRIORITY) else "low"
                planned.append(
                    _make_planned_query(
                        query_id=_next_id(),
                        query=q,
                        source="hypothesis",
                        hypothesis_id=hyp_id,
                        group_ids=[group_id],
                        priority=priority,
                        search_priority_rank=rank,
                    )
                )
                used_query_strings.add(key)
                progress = True
                break
        if not progress:
            break

    return planned[:budget_capped]
