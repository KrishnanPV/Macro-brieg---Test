# 01 — Derived facts, inflections, and trend segments

**Source:** [`backend/services/derived_facts.py`](../../backend/services/derived_facts.py) (lines 1–142 at commit `ce49207fc3ac58a63b3d44a528fd0f57057a2eb7`)

**Entry point:** `compute_derived_facts(results: list[dict]) -> list[dict]`

This module pre-computes per-series statistics that are injected into `DATA_CONTEXT.derived_facts` for dashboard prompts and used downstream for news date ranges and triage.

**End-to-end context:** For how this stage connects to news and the LLM, see [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md).

---

## What this stage does (plain language)

The app already has **time series** from Oxford Economics (or similar): dated points for each KPI and, often, multiple **series** per KPI (e.g. several countries or several industry lines). This function does **not** call an LLM and does **not** fetch news. It only **summarizes** each series using standard arithmetic: latest vs previous value, long-run growth (CAGR), step-by-step changes, and rule-based flags for “something unusual happened here.”

That matters because later steps **forbid** the model from inventing numbers: the LLM is told to ground claims in `derived_facts` and `results`. This object is the **single deterministic summary** of the data window.

---

## Inputs and outputs

| | |
|---|---|
| **Input** | `results`: a list of KPI payloads. Each item has `kpi_id`, `kpi_name`, and `series`: a list of objects with `country`, `indicator`, and `points` (each point: `date`, `value`). |
| **Output** | A list parallel to the input: for each KPI, a dict with `series_facts[]`. Each `series_facts` entry corresponds to **one** input series (or a placeholder row if there were no valid points). |
| **Downstream uses** | (1) **Prompt JSON** — merged into `DATA_CONTEXT.derived_facts` for insight and brief generation. (2) **News date range** — [`_derive_date_range`](../../backend/services/news_client.py) reads earliest/latest dates from these facts to set Newscatcher `from_` / `to_`. (3) **Country brief triage** — [`score_kpi`](../../backend/services/kpi_triage.py) reads `cagr`, `inflection_points`, `trend_segments`, `change_pct` from each series fact. |

---

## Glossary (terms used in this doc)

| Term | Meaning |
|------|--------|
| **Series** | One plotted line: a `(country, indicator)` combination inside a KPI. |
| **Point** | One observation: a date + value on that line. |
| **PoP (period over period)** | From one consecutive point to the next: “how much did the value change between this reporting period and the previous one?” Often expressed as **% change** when the previous value is non-zero. |
| **Mean absolute PoP** | Take every PoP % change in the series, drop missing values, then average **absolute** size. Used only inside the inflection logic as a **typical volatility** reference for that series — not passed to the LLM as a named field. |
| **Inflection point** | A PoP step the code **flags** because either (a) growth flipped from positive to negative or vice versa with a large enough move, or (b) the move is **larger than usual** for that series (see rules below). |
| **Trend segment** | A **run** of consecutive PoP moves in the **same direction** (all growth or all shrinkage). When direction flips, the run ends and a new segment can start. Segments need at least two steps to be summarized. |
| **CAGR** | Compound annual growth rate from the **first** to the **last** point in the window — “if growth were smooth, what yearly % would get from start to end?” Only computed when both endpoints are positive (log-style formula in code). |
| **`change_pct` (series fact)** | Latest value vs **immediately prior** point only — *not* the same as comparing to the same quarter last year unless the data are already YoY. |

---

## Behavior summary

| Output field | Meaning |
|--------------|---------|
| `earliest` / `latest` | Bookend observations |
| `prior` + `change_pct` | Latest vs prior period % change (if ≥2 points) |
| `cagr` | CAGR over full window (requires ≥2 points, positive earliest/latest for log-style calc) |
| `period_over_period` | Consecutive step changes with optional `pct_change` |
| `inflection_points` | Subset of PoP steps flagged by rules below |
| `trend_segments` | Runs of same-direction PoP changes, split when sign flips |

## Inflection rules (verbatim logic)

From consecutive `period_over_period` changes:

1. **Mean absolute PoP:** `mean_abs = average(|pct_change|)` over all PoP steps that have `pct_change`.
2. **Dynamic threshold:** `threshold = max(mean_abs * 1.5, 3.0)`.
3. **Sign reversal:** For step `i > 0`, if `prev_pct * pct < 0` and `abs(pct) > 2.0` → `reason = "sign_reversal"`.
4. **Outsized move:** If `abs(pct) > threshold` → `reason = reason or "outsized_move"`. If both sign-reversal and outsized apply, **`sign_reversal` wins** because it is assigned first and `outsized_move` only fills in when `reason` is still empty.

**Intuition:** A quiet series gets a **lower** `mean_abs`, so the bar for an “outsized” move drops — but never below **3 percentage points** (the `max(..., 3.0)` floor). A volatile series raises the bar so only genuinely large single jumps count.

## Trend segments

When consecutive PoP `%` signs differ (`prev_pct * curr_pct < 0`), the code closes a segment and, if the segment has **≥2** PoP steps, summarizes it via `_summarize_segment`. The final segment is also summarized if it has **≥2** steps. Direction is `"rising"` or `"falling"` from the **first** step’s `pct_change` sign.

## Full module (verbatim)

```python
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
            "series_facts": [],
        }
        for s in kpi_result.get("series", []):
            vals = [(p["date"], p["value"]) for p in s["points"] if p["value"] is not None]
            if not vals:
                kpi_facts["series_facts"].append({
                    "country": s["country"],
                    "indicator": s["indicator"],
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
```

## Related

- KPI **notability** scoring for country briefs (different from inflection math): [02 — KPI notability scoring](02-kpi-notability-scoring.md)
- Prompt instructions that tell the LLM how to **use** `derived_facts`: [05 — Prompts & KPI lenses](05-dashboard-prompts-and-lenses.md)
- Full pipeline narrative: [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)
