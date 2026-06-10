"""Headline metrics ribbon — computed from derived_facts so trends/arrows match data."""
from __future__ import annotations

import re
from typing import Any


def _year_from_iso(iso_date: str) -> str:
    m = re.match(r"(\d{4})", iso_date or "")
    return m.group(1) if m else ""


def _quarter_label(iso_date: str) -> str:
    """Return Qn YYYY from an ISO date."""
    if not iso_date:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso_date)
    if not m:
        return ""
    y, mo = int(m.group(1)), int(m.group(2))
    q = (mo - 1) // 3 + 1
    return f"Q{q} {y}"


def _trend_from_change_pct(change_pct: float | None, *, threshold: float = 0.04) -> str:
    """Literal data trend: latest vs prior period."""
    if change_pct is None:
        return "flat"
    if abs(change_pct) < threshold:
        return "flat"
    return "up" if change_pct > 0 else "down"


def _trend_from_change_pp(change_pp: float | None, *, threshold: float = 0.05) -> str:
    """Literal data trend for rate KPIs, based on percentage-point movement."""
    if change_pp is None:
        return "flat"
    if abs(change_pp) < threshold:
        return "flat"
    return "up" if change_pp > 0 else "down"


_PERCENT_KPIS = frozenset(("3", "5", "7", "8"))

_SCALE_WORDS: dict[str, float] = {
    "billions": 1e9, "billion": 1e9,
    "millions": 1e6, "million": 1e6,
    "thousands": 1e3, "thousand": 1e3,
}


def _extract_scale_multiplier(unit: str) -> float:
    """Return the numeric multiplier encoded in a unit string like 'SAR millions (2023 prices)'."""
    for token in unit.lower().split():
        if token in _SCALE_WORDS:
            return _SCALE_WORDS[token]
    return 1.0


def _extract_currency(unit: str) -> str:
    """Return only the currency code (e.g. 'SAR') from a unit like 'SAR millions (2023 prices)'."""
    if not unit or unit.startswith("%"):
        return ""
    first = unit.split()[0]
    if first.lower() in _SCALE_WORDS:
        return ""
    return first


def _round_to_sig(v: float, n_sig: int = 2) -> float:
    """Round to n significant digits."""
    if v == 0:
        return 0
    import math
    d = math.ceil(math.log10(abs(v)))
    factor = 10 ** (n_sig - d)
    return round(v * factor) / factor


def _abbrev(n: float) -> str:
    """Abbreviate an absolute number to K/M/B, rounded to ~2 significant digits."""
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n >= 1_000_000_000:
        v = _round_to_sig(abs_n / 1_000_000_000)
        return f"{sign}{v:.1f}B" if v < 10 else f"{sign}{v:.0f}B"
    if abs_n >= 1_000_000:
        v = _round_to_sig(abs_n / 1_000_000)
        return f"{sign}{v:.1f}M" if v < 10 else f"{sign}{v:.0f}M"
    if abs_n >= 1_000:
        v = _round_to_sig(abs_n / 1_000)
        return f"{sign}{v:.0f}K"
    return f"{sign}{abs_n:.1f}" if abs_n != int(abs_n) else f"{sign}{int(abs_n)}"


def _format_value(kpi_id: str, raw: float, unit: str = "") -> str:
    if kpi_id in _PERCENT_KPIS:
        return f"{raw:.1f}%" if abs(raw) < 10 else f"{raw:.0f}%"
    display_val = raw * _extract_scale_multiplier(unit)
    abbr = _abbrev(display_val)
    ccy = _extract_currency(unit)
    if ccy:
        return f"{abbr} {ccy}"
    return abbr


def _pick_series(kpi_id: str, series_facts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the primary series for ribbon display."""
    valid = [sf for sf in series_facts if not sf.get("note") and sf.get("latest")]
    if not valid:
        return None

    if kpi_id == "2":
        for sf in valid:
            ind = (sf.get("indicator") or "").lower()
            if "non-oil" in ind:
                return sf
        return valid[0]

    if kpi_id == "4":
        for sf in valid:
            ind = (sf.get("indicator") or "").lower()
            if "inward" in ind:
                return sf
        return valid[0]

    return valid[0]


def _build_label(kpi_id: str, kpi_name: str, sf: dict[str, Any]) -> str:
    ld = sf.get("latest", {}).get("date", "")

    short = {
        "3": "Real GDP growth",
        "2": "Non-oil real GDP",
        "5": "Unemployment rate",
        "7": "Inflation (CPI YoY)",
        "8": "External debt (% GDP)",
        "4": "FDI inward",
        "6": "Private consumption (real PPP)",
        "9": "Population",
    }.get(kpi_id, kpi_name.split(",")[0][:40])

    y = _year_from_iso(ld)
    suffix = f" ({y})" if y else ""

    return f"{short}{suffix}"


def compute_ribbon_metrics(derived_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build 4–6 headline metrics from derived facts. Directions are **literal**
    period-over-period changes (latest vs prior), not sentiment.
    """
    by_id: dict[str, dict[str, Any]] = {str(f["kpi_id"]): f for f in derived_facts}

    order = ["3", "2", "5", "7", "8", "4"]
    out: list[dict[str, str]] = []

    for kid in order:
        facts = by_id.get(kid)
        if not facts:
            continue
        sf = _pick_series(kid, facts.get("series_facts") or [])
        if not sf:
            continue

        latest = sf.get("latest", {})
        lv = latest.get("value")
        if lv is None:
            continue

        is_percent = kid in _PERCENT_KPIS

        unit = sf.get("unit", "") or facts.get("unit", "")
        label = _build_label(kid, facts.get("kpi_name", ""), sf)
        value = _format_value(kid, float(lv), unit)

        cp = sf.get("change_pct")
        prior = sf.get("prior", {})
        cagr = sf.get("cagr")
        earliest = sf.get("earliest", {})

        # For rate KPIs (growth, unemployment, inflation, debt %) a relative
        # percentage change of the rate is misleading ("0.1% growth, -99% vs
        # prior"). Use percentage-point deltas instead and base the trend on
        # the pp movement. Level KPIs keep the relative percentage change.
        change_pp: float | None = None
        change_from_earliest_pp: float | None = None
        if is_percent and prior.get("value") is not None:
            change_pp = round(float(lv) - float(prior["value"]), 1)
        if is_percent and earliest.get("value") is not None:
            change_from_earliest_pp = round(float(lv) - float(earliest["value"]), 1)

        if is_percent:
            direction = _trend_from_change_pp(change_pp)
        else:
            direction = _trend_from_change_pct(cp)

        detail: dict[str, Any] = {
            "label": label,
            "value": value,
            "direction": direction,
            "kpi_id": kid,
        }
        if unit:
            detail["unit"] = unit

        if is_percent:
            if change_pp is not None:
                detail["change_pp"] = change_pp
            if change_from_earliest_pp is not None:
                detail["change_from_earliest_pp"] = change_from_earliest_pp
        else:
            if cp is not None:
                detail["change_pct"] = round(cp, 2)
            if isinstance(cagr, dict) and cagr.get("cagr_pct") is not None:
                detail["cagr"] = round(cagr["cagr_pct"], 2)
            elif isinstance(cagr, (int, float)):
                detail["cagr"] = round(cagr, 2)

        if prior.get("value") is not None:
            detail["prior_value"] = _format_value(kid, float(prior["value"]), unit)
            pd = prior.get("date", "")
            detail["prior_label"] = _year_from_iso(pd)
        if earliest.get("value") is not None:
            detail["earliest_value"] = _format_value(kid, float(earliest["value"]), unit)
            ed = earliest.get("date", "")
            detail["earliest_label"] = _year_from_iso(ed)

        out.append(detail)

        if len(out) >= 6:
            break

    return out
