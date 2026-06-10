"""Deterministic data-quality / measurement-break detection (WS4).

Some Oxford/Knoema series contain discontinuities that are reporting artifacts
(rebasing, methodology breaks, balance-of-payments revisions, lumpy one-off FDI
transactions) rather than true economic moves. Narrating those at face value
produces over-confident, wrong conclusions (e.g. China inward FDI "collapsing"
from ~107bn to ~9bn, or an implausible single-year CPI swing).

This module flags the clearest such smells from the already-computed derived
facts and renders a compact prompt block so the brief writer caveats them and
avoids building strong causal narratives on top of them. It is intentionally
conservative: it prefers missing a borderline case over flooding the prompt
with false positives.
"""
from __future__ import annotations

from typing import Any

# Rate KPIs are measured in percent; their anomaly test is a percentage-point
# swing. Everything else is treated as a level series.
_RATE_KPIS = frozenset({"3", "5", "7", "8", "12"})

# Thresholds tuned to catch breaks, not normal volatility.
_COLLAPSE_RATIO = 0.35           # latest below 35% of the period max => possible break
_LEVEL_JUMP_PCT = 60.0           # single-period move >= 60% => possible break
_RATE_SWING_PP = 5.0             # single-period rate swing >= 5pp => possible break
_SHARE_SHIFT_PP = 6.0            # compositional share shift >= 6pp over window


def _fmt(v: float) -> str:
    av = abs(v)
    if av >= 1_000_000_000:
        return f"{v / 1_000_000_000:.1f}bn"
    if av >= 1_000_000:
        return f"{v / 1_000_000:.1f}mn"
    if av >= 1_000:
        return f"{v / 1_000:.1f}k"
    return f"{v:.1f}"


def _series_label(kpi_name: str, indicator: str) -> str:
    indicator = (indicator or "").strip()
    base = (kpi_name or "").split(",")[0].strip()
    if indicator and indicator.lower() not in base.lower():
        return f"{base} ({indicator})"
    return base or indicator or "series"


def detect_anomalies(derived_facts: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return a list of {kpi_id, label, issue} flags for suspected data breaks."""
    flags: list[dict[str, str]] = []

    for fact in derived_facts:
        kid = str(fact.get("kpi_id", ""))
        kpi_name = fact.get("kpi_name", "")
        is_rate = kid in _RATE_KPIS

        for sf in fact.get("series_facts", []):
            if sf.get("note"):
                continue
            label = _series_label(kpi_name, sf.get("indicator", ""))
            latest = (sf.get("latest") or {}).get("value")
            mx = (sf.get("max") or {}).get("value")
            issues: list[str] = []

            # 1) Level collapse: latest far below the period peak.
            if (
                not is_rate
                and latest is not None
                and mx is not None
                and mx > 0
                and latest >= 0
                and latest < _COLLAPSE_RATIO * mx
            ):
                issues.append(
                    f"latest {_fmt(latest)} is far below the period peak {_fmt(mx)} "
                    "(possible reporting break or one-off)"
                )

            # 2) Outsized single-period move or sign reversal (from inflections).
            for infl in sf.get("inflection_points", []) or []:
                pct = infl.get("pct_change")
                reason = infl.get("reason")
                if reason == "sign_reversal":
                    issues.append(
                        f"sign reversal around {infl.get('date', '')} "
                        "(series flips sign; interpret net position cautiously)"
                    )
                    break
                if not is_rate and pct is not None and abs(pct) >= _LEVEL_JUMP_PCT:
                    issues.append(
                        f"single-period move of {pct:+.0f}% around {infl.get('date', '')} "
                        "(possible break or lumpy transaction)"
                    )
                    break

            # 3) Rate KPIs: large single-period percentage-point swing.
            if is_rate:
                for chg in sf.get("period_over_period", []) or []:
                    delta = chg.get("absolute_change")
                    if delta is not None and abs(delta) >= _RATE_SWING_PP:
                        issues.append(
                            f"single-period swing of {delta:+.1f}pp around "
                            f"{chg.get('to_date', '')} (unusually large for a rate)"
                        )
                        break

            for issue in issues:
                flags.append({"kpi_id": kid, "label": label, "issue": issue})

        # 4) Implausibly large compositional share shift.
        for row in fact.get("composition", []) or []:
            if not isinstance(row, dict) or row.get("type") != "share_shift_summary":
                continue
            for ind, shift in (row.get("shifts_pp") or {}).items():
                if abs(shift) >= _SHARE_SHIFT_PP:
                    flags.append({
                        "kpi_id": kid,
                        "label": _series_label(kpi_name, ind),
                        "issue": (
                            f"share shifted {shift:+.1f}pp over the window "
                            "(large for a structural share; may reflect rebasing)"
                        ),
                    })

    return flags


def format_data_quality_block(flags: list[dict[str, str]]) -> str:
    """Render anomaly flags as a compact prompt block (empty string if none)."""
    if not flags:
        return ""
    lines = [f"- {f['label']}: {f['issue']}" for f in flags]
    return (
        "\n\nDATA_QUALITY_FLAGS — the following series show discontinuities that may be "
        "measurement breaks, rebasing, or reporting artifacts rather than true economic "
        "moves. Treat them with explicit caution: caveat the figure, avoid building a "
        "strong causal narrative on it, prefer cautious phrasing, and assign it lower "
        "confidence. Do not present an anomalous value as an established economic fact:\n"
        + "\n".join(lines)
        + "\n"
    )
