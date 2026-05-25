"""Pre-compute summary statistics per series for LLM grounding."""
from __future__ import annotations

import statistics
from typing import Any
import pandas as pd

_MULTI_SERIES_KPIS = frozenset({"2", "4", "11"})
_PAIRED_NET_KPIS = frozenset({"4"})
_GROWTH_GAP_KPIS = frozenset({"2"})


def compute_derived_facts(results: list[dict]) -> list[dict]:
    """Pre-compute summary statistics per series so the LLM can ground on them."""
    facts: list[dict] = []
    for kpi_result in results:
        kpi_id = str(kpi_result.get("kpi_id", ""))
        kpi_facts: dict[str, Any] = {
            "kpi_id": kpi_result["kpi_id"],
            "kpi_name": kpi_result["kpi_name"],
            "unit": kpi_result.get("unit", ""),
            "series_facts": [],
        }

        all_series_vals: dict[str, list[tuple[str, float]]] = {}

        for s in kpi_result.get("series", []):
            vals = [(p["date"], p["value"]) for p in s["points"] if p["value"] is not None]
            series_unit = s.get("unit", "") or kpi_result.get("unit", "")
            indicator_name = s.get("indicator", "")
            if not vals:
                kpi_facts["series_facts"].append({
                    "country": s["country"],
                    "indicator": indicator_name,
                    "unit": series_unit,
                    "note": "No non-null values.",
                })
                continue

            vals.sort(key=lambda x: x[0])
            if kpi_id in _MULTI_SERIES_KPIS:
                all_series_vals[indicator_name] = vals

            latest_date, latest_val = vals[-1]
            earliest_date, earliest_val = vals[0]
            prior_date, prior_val = vals[-2] if len(vals) >= 2 else (None, None)
            all_vals = [v for _, v in vals]

            sf: dict[str, Any] = {
                "country": s["country"],
                "indicator": indicator_name,
                "unit": series_unit,
                "n_points": len(vals),
                "earliest": {"date": earliest_date, "value": earliest_val},
                "latest": {"date": latest_date, "value": latest_val},
                "min": {"value": min(all_vals), "date": vals[all_vals.index(min(all_vals))][0]},
                "max": {"value": max(all_vals), "date": vals[all_vals.index(max(all_vals))][0]},
            }
            if prior_val is not None:
                sf["prior"] = {"date": prior_date, "value": prior_val}
                if prior_val != 0:
                    sf["change_pct"] = round((latest_val - prior_val) / abs(prior_val) * 100, 2)

            if len(all_vals) >= 2:
                sf["window_summary"] = {
                    "mean": round(statistics.mean(all_vals), 4),
                    "std_dev": round(statistics.stdev(all_vals), 4) if len(all_vals) >= 3 else None,
                    "best": {"date": vals[all_vals.index(max(all_vals))][0], "value": max(all_vals)},
                    "worst": {"date": vals[all_vals.index(min(all_vals))][0], "value": min(all_vals)},
                }

            if len(vals) >= 2 and earliest_val and earliest_val > 0 and latest_val > 0:
                try:
                    t_start = pd.Timestamp(earliest_date)
                    t_end = pd.Timestamp(latest_date)
                    years = max((t_end - t_start).days / 365.25, 0.25)
                    cagr = ((latest_val / earliest_val) ** (1.0 / years) - 1) * 100
                    sf["cagr"] = {
                        "from": earliest_date,
                        "to": latest_date,
                        "years": round(years, 1),
                        "cagr_pct": round(cagr, 2),
                    }
                except Exception:
                    pass

            if len(vals) >= 2:
                pop_changes: list[dict] = []
                for i in range(1, len(vals)):
                    d_prev, v_prev = vals[i - 1]
                    d_curr, v_curr = vals[i]
                    chg: dict[str, Any] = {
                        "from_date": d_prev,
                        "to_date": d_curr,
                        "from_value": v_prev,
                        "to_value": v_curr,
                        "absolute_change": round(v_curr - v_prev, 4),
                    }
                    if v_prev != 0:
                        chg["pct_change"] = round((v_curr - v_prev) / abs(v_prev) * 100, 2)
                    pop_changes.append(chg)
                sf["period_over_period"] = pop_changes

                inflections: list[dict] = []
                pct_changes = [c.get("pct_change") for c in pop_changes if c.get("pct_change") is not None]
                if pct_changes:
                    mean_abs = sum(abs(p) for p in pct_changes) / len(pct_changes)
                    threshold = max(mean_abs * 1.5, 3.0)
                    for i, chg in enumerate(pop_changes):
                        pct = chg.get("pct_change")
                        if pct is None:
                            continue
                        reason = None
                        if i > 0:
                            prev_pct = pop_changes[i - 1].get("pct_change")
                            if prev_pct is not None and prev_pct * pct < 0 and abs(pct) > 2.0:
                                reason = "sign_reversal"
                        if abs(pct) > threshold:
                            reason = reason or "outsized_move"
                        if reason:
                            inflections.append({
                                "date": chg["to_date"],
                                "value": chg["to_value"],
                                "pct_change": pct,
                                "reason": reason,
                            })
                if inflections:
                    sf["inflection_points"] = inflections

                segments: list[dict] = []
                seg_start_idx = 0
                for i in range(1, len(pop_changes)):
                    prev_pct = pop_changes[i - 1].get("pct_change")
                    curr_pct = pop_changes[i].get("pct_change")
                    if prev_pct is not None and curr_pct is not None and prev_pct * curr_pct < 0:
                        seg = pop_changes[seg_start_idx:i]
                        if len(seg) >= 2:
                            segments.append(_summarize_segment(seg))
                        seg_start_idx = i
                final_seg = pop_changes[seg_start_idx:]
                if len(final_seg) >= 2:
                    segments.append(_summarize_segment(final_seg))
                if segments:
                    sf["trend_segments"] = segments

            kpi_facts["series_facts"].append(sf)

        if kpi_id in _MULTI_SERIES_KPIS and len(all_series_vals) >= 2:
            kpi_facts["composition"] = _compute_composition(all_series_vals)

        if kpi_id in _PAIRED_NET_KPIS and len(all_series_vals) == 2:
            kpi_facts["net_flow"] = _compute_net_flow(all_series_vals, kpi_id)

        if kpi_id in _GROWTH_GAP_KPIS and len(all_series_vals) == 2:
            kpi_facts["growth_gap"] = _compute_growth_gap(all_series_vals)

        facts.append(kpi_facts)
    return facts


def _summarize_segment(seg: list[dict]) -> dict[str, Any]:
    direction = "rising" if seg[0].get("pct_change", 0) > 0 else "falling"
    start_val = seg[0]["from_value"]
    end_val = seg[-1]["to_value"]
    total_change = round(end_val - start_val, 4)
    total_pct = round((end_val - start_val) / abs(start_val) * 100, 2) if start_val != 0 else None
    return {
        "direction": direction,
        "from_date": seg[0]["from_date"],
        "to_date": seg[-1]["to_date"],
        "from_value": start_val,
        "to_value": end_val,
        "periods": len(seg),
        "total_change": total_change,
        "total_pct_change": total_pct,
    }


def _compute_composition(
    all_series: dict[str, list[tuple[str, float]]],
) -> list[dict[str, Any]]:
    """Compute per-period share percentages for multi-series KPIs."""
    dates: dict[str, dict[str, float]] = {}
    for indicator, vals in all_series.items():
        for d, v in vals:
            dates.setdefault(d, {})[indicator] = v

    composition: list[dict[str, Any]] = []
    for date in sorted(dates.keys()):
        values = dates[date]
        total = sum(abs(v) for v in values.values())
        if total == 0:
            continue
        shares = {ind: round(v / total * 100, 2) for ind, v in values.items()}
        composition.append({"date": date, "total": round(total, 4), "shares": shares})

    if len(composition) >= 2:
        first_shares = composition[0]["shares"]
        last_shares = composition[-1]["shares"]
        all_indicators = set(first_shares) | set(last_shares)
        shifts: dict[str, float] = {}
        for ind in all_indicators:
            s0 = first_shares.get(ind, 0.0)
            s1 = last_shares.get(ind, 0.0)
            shift = round(s1 - s0, 2)
            if abs(shift) > 0.5:
                shifts[ind] = shift
        if shifts:
            composition.append({
                "type": "share_shift_summary",
                "from_date": composition[0]["date"],
                "to_date": composition[-1]["date"],
                "shifts_pp": shifts,
            })

    return composition


def _compute_net_flow(
    all_series: dict[str, list[tuple[str, float]]],
    kpi_id: str,
) -> list[dict[str, Any]]:
    """Compute net (first series minus second series) for paired flow KPIs like FDI."""
    names = list(all_series.keys())
    inward_key = next((n for n in names if "inward" in n.lower()), names[0])
    outward_key = next((n for n in names if "outward" in n.lower()), names[1] if len(names) > 1 else names[0])
    if inward_key == outward_key:
        return []

    inward = {d: v for d, v in all_series[inward_key]}
    outward = {d: v for d, v in all_series[outward_key]}
    common_dates = sorted(set(inward) & set(outward))

    net_flow: list[dict[str, Any]] = []
    for d in common_dates:
        net = round(inward[d] - outward[d], 4)
        net_flow.append({
            "date": d,
            "inward": round(inward[d], 4),
            "outward": round(outward[d], 4),
            "net": net,
            "direction": "net_inflow" if net > 0 else "net_outflow",
        })
    return net_flow


def _compute_growth_gap(
    all_series: dict[str, list[tuple[str, float]]],
) -> list[dict[str, Any]]:
    """Compute growth-rate gap between two series (e.g. oil vs non-oil GDP)."""
    names = list(all_series.keys())
    if len(names) < 2:
        return []

    growth_rates: dict[str, dict[str, float]] = {}
    for name, vals in all_series.items():
        for i in range(1, len(vals)):
            d_prev, v_prev = vals[i - 1]
            d_curr, v_curr = vals[i]
            if v_prev and v_prev != 0:
                gr = round((v_curr - v_prev) / abs(v_prev) * 100, 2)
                growth_rates.setdefault(d_curr, {})[name] = gr

    gap_series: list[dict[str, Any]] = []
    for date in sorted(growth_rates.keys()):
        rates = growth_rates[date]
        if len(rates) == 2:
            keys = list(rates.keys())
            gap = round(rates[keys[1]] - rates[keys[0]], 2)
            gap_series.append({
                "date": date,
                "rates": rates,
                "gap_pp": gap,
                "faster": keys[1] if gap > 0 else keys[0],
            })
    return gap_series
