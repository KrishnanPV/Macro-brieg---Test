"""Pre-compute summary statistics per series for LLM grounding."""
from __future__ import annotations

from typing import Any
import pandas as pd


def compute_derived_facts(results: list[dict]) -> list[dict]:
    """Pre-compute summary statistics per series so the LLM can ground on them."""
    facts: list[dict] = []
    for kpi_result in results:
        kpi_facts: dict[str, Any] = {
            "kpi_id": kpi_result["kpi_id"],
            "kpi_name": kpi_result["kpi_name"],
            "unit": kpi_result.get("unit", ""),
            "series_facts": [],
        }
        for s in kpi_result.get("series", []):
            vals = [(p["date"], p["value"]) for p in s["points"] if p["value"] is not None]
            series_unit = s.get("unit", "") or kpi_result.get("unit", "")
            if not vals:
                kpi_facts["series_facts"].append({
                    "country": s["country"],
                    "indicator": s["indicator"],
                    "unit": series_unit,
                    "note": "No non-null values.",
                })
                continue

            vals.sort(key=lambda x: x[0])
            latest_date, latest_val = vals[-1]
            earliest_date, earliest_val = vals[0]
            prior_date, prior_val = vals[-2] if len(vals) >= 2 else (None, None)
            all_vals = [v for _, v in vals]

            sf: dict[str, Any] = {
                "country": s["country"],
                "indicator": s["indicator"],
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
