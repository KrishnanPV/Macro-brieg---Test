# 02 — KPI notability scoring (country brief triage)

**Source:** [`backend/services/kpi_triage.py`](../../backend/services/kpi_triage.py) (lines 1–125 at commit `ce49207fc3ac58a63b3d44a528fd0f57057a2eb7`)

**Purpose:** Turn **derived facts** (from [`compute_derived_facts`](../../backend/services/derived_facts.py)) into a **single importance score per KPI** and a **yes/no “notable” flag**. Only **country brief** generation uses this to decide which KPIs get full narrative treatment. It is **not** the same as Newscatcher **article** scoring ([04](04-article-scoring-and-filtering.md)).

**End-to-end context:** [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)

---

## Glossary

| Term | Meaning |
|------|--------|
| **Triage** | After scoring every KPI, adjust who counts as “notable” so the brief always has enough topics (min) but not too many (max). |
| **Boring CAGR** | A **floor** for “nothing to see here.” If the absolute CAGR is **below** this KPI’s boring threshold, we **do not** add the CAGR bonus (but other parts of the series can still add points). |
| **Notable** | `score >= 3.0` **before** triage tweaks; triage can promote/demote the boolean flag without changing the numeric `score`. |
| **Series facts** | One entry in `kpi_facts["series_facts"]` per plotted line (country × indicator). Scoring **loops over all of them** and **adds** points into one running total for that KPI. |

---

## Inputs and outputs

| | |
|---|---|
| **Input** | `derived_facts`: output of `compute_derived_facts` — one dict per KPI, each with `series_facts[]`. |
| **Processing** | **Deterministic.** No LLM. Same derived facts → same scores. |
| **Output** | `list[KpiScore]` sorted by **descending** `score`. Each row: `kpi_id`, `kpi_name`, `score`, `notable`, `reasons` (human-readable audit trail). |
| **Consumed by** | [`country_brief.py`](../../backend/routers/country_brief.py): `notable_ids = [s.kpi_id for s in scores if s.notable]`, then news fetch and `build_brief_prompt` only include those KPIs. |

---

## Critical detail: one KPI, many series

A KPI like “FDI” can have **multiple** `series_facts` (e.g. inward vs outward, or multiple countries in one payload). `score_kpi` **iterates every** non-placeholder `series_fact` and **adds** all bonuses into **one** `score` for that `kpi_id`. So a KPI with more lines can accumulate a higher score simply because there are more chances to hit inflections or reversals.

If a series has `"note": "No non-null values."`, it is **skipped** entirely.

---

## Exact scoring parameters (additive)

Start with `score = 0`. For **each** qualifying `series_fact` in that KPI:

### A — CAGR block (uses `sf["cagr"]` if present)

| Step | Condition | Points added | Notes |
|------|-----------|--------------|--------|
| A1 | `boring = _BORING_CAGR.get(kpi_id, 1.5)` — KPI **5** → 1.0, **6** → 3.0, **9** → 2.0, else **1.5** | — | Defines “unremarkable” magnitude. |
| A2 | `abs(cagr_pct) > boring` | `+ min(abs(cagr_pct) / boring, 5.0)` | Capped so one line cannot add more than **5** from this line alone. |
| A3 | `cagr_pct < -1.0` | **+2.0** (extra) | Triggers in addition to A2 when applicable; reason string `"negative CAGR"`. |

### B — Inflection block (uses `sf["inflection_points"]`)

| Condition | Points added |
|-----------|--------------|
| At least one inflection | `+ min(len(inflections) * 1.5, 6.0)` |

So 1 inflection → +1.5, 2 → +3, 3 → +4.5, 4+ → **capped at +6.0** for that series. A reason string logs count and worst `pct_change`.

### C — Trend segment reversals (uses `sf["trend_segments"]`)

| Condition | Points added |
|-----------|--------------|
| Count `reversals`: adjacent segments where `direction` differs | `+1.0` **per** reversal |

Example: three segments up → down → up yields **2** reversals → +2.0.

### D — Latest period shock (uses `sf["change_pct"]`)

| Condition | Points added |
|-----------|--------------|
| `change_pct` is not `None` and `abs(change_pct) > 10` | **+1.5** |

This is **latest vs prior point** in derived facts, not YoY unless the underlying data are YoY.

### E — GDP family boost (per KPI id, once per `score_kpi` call)

| Condition | Points added |
|-----------|--------------|
| `kpi_id in ("1", "2", "3")` | **+1.0** |

Applied **after** the loop, regardless of how many series were summed.

### Final boolean

`notable = (score >= 3.0)` where `_NOTABLE_THRESHOLD = 3.0`. The stored `score` is **rounded to 2 decimals** for display only; comparison uses the float before rounding in practice (minor edge case if rounding moved 2.996 → 3.00 — the code compares pre-round `score`).

---

## Worked example (illustrative)

Assume KPI **"4"** (FDI), one series, boring default **1.5**:

- CAGR +4.5% → `4.5/1.5 = 3.0` → **+3.0**
- Two inflections → `min(2 * 1.5, 6) = 3.0` → **+3.0**
- No segment reversals, latest change 8% → no D block
- Not GDP family → no E

Subtotal **6.0** → `notable = True`. Reasons would list CAGR text and inflection summary.

---

## `triage_kpis` parameters and behavior

**Signature:** `triage_kpis(derived_facts, min_notable=3, max_notable=7)`.

1. **Score** every KPI → **sort** by `score` **descending** (highest first).
2. **Count** how many already have `notable == True` (score ≥ 3).
3. **Promotion (too few notables):** If count `< min_notable`, walk the **sorted** list from the top. For each KPI that is **not** yet notable, set `notable = True` and append `"promoted (min-notable)"` to `reasons` until count ≥ `min_notable`. This guarantees the brief always has at least three “themes” even if every raw score was low.
4. **Demotion (too many notables):** If notable count `> max_notable`, walk in **sorted order** (best scores first). Keep the first `max_notable` **true** notables as you encounter them; set `notable = False` for any additional **true** notables further down the list.

After triage, **`score` numbers are unchanged** — only flags and reasons update.

---

## Relationship to dashboard insights

| Feature | Uses triage? |
|---------|----------------|
| Country brief generation | **Yes** — `notable_ids` drives which KPIs appear in the prompt. |
| `/api/insights`, single-KPI streams | **No** — user already picked KPIs; full `derived_facts` for those KPIs go to the LLM. |

---

## Full module (verbatim)

```python
"""KPI relevance scoring — filter to only the most notable KPIs for a brief."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.models.kpi_registry import SPECS_BY_ID


@dataclass
class KpiScore:
    kpi_id: str
    kpi_name: str
    score: float
    notable: bool
    reasons: list[str]


# Per-KPI "boring" thresholds — CAGR magnitudes below these are unremarkable
_BORING_CAGR: dict[str, float] = {
    "9": 2.0,   # population — < 2% CAGR is normal
    "5": 1.0,   # unemployment — < 1pp change is noise
    "6": 3.0,   # consumption — steady single-digit growth is expected
}

_NOTABLE_THRESHOLD = 3.0


def score_kpi(kpi_id: str, kpi_facts: dict[str, Any]) -> KpiScore:
    """Score a single KPI's notability from its derived facts."""
    spec = SPECS_BY_ID.get(kpi_id)
    kpi_name = spec.name if spec else kpi_facts.get("kpi_name", f"KPI {kpi_id}")
    series_facts = kpi_facts.get("series_facts", [])

    if not series_facts:
        return KpiScore(kpi_id=kpi_id, kpi_name=kpi_name, score=0, notable=False,
                        reasons=["No data"])

    score = 0.0
    reasons: list[str] = []

    for sf in series_facts:
        if sf.get("note"):
            continue

        cagr_info = sf.get("cagr")
        if cagr_info:
            cagr_abs = abs(cagr_info["cagr_pct"])
            boring = _BORING_CAGR.get(kpi_id, 1.5)
            if cagr_abs > boring:
                bonus = min(cagr_abs / boring, 5.0)
                score += bonus
                reasons.append(f"CAGR {cagr_info['cagr_pct']:+.1f}%")

            if cagr_info["cagr_pct"] < -1.0:
                score += 2.0
                reasons.append("negative CAGR")

        inflections = sf.get("inflection_points", [])
        if inflections:
            score += min(len(inflections) * 1.5, 6.0)
            worst = max(inflections, key=lambda x: abs(x.get("pct_change", 0)))
            reasons.append(
                f"{len(inflections)} inflection(s), max {worst['pct_change']:+.1f}%"
            )

        segments = sf.get("trend_segments", [])
        reversals = 0
        for i in range(1, len(segments)):
            if segments[i]["direction"] != segments[i - 1]["direction"]:
                reversals += 1
        if reversals:
            score += reversals * 1.0
            reasons.append(f"{reversals} trend reversal(s)")

        change_pct = sf.get("change_pct")
        if change_pct is not None and abs(change_pct) > 10:
            score += 1.5
            reasons.append(f"latest period {change_pct:+.1f}%")

    # GDP-related KPIs get a base relevance boost — they're almost always notable
    if kpi_id in ("1", "2", "3"):
        score += 1.0

    notable = score >= _NOTABLE_THRESHOLD
    return KpiScore(
        kpi_id=kpi_id, kpi_name=kpi_name, score=round(score, 2),
        notable=notable, reasons=reasons,
    )


def triage_kpis(
    derived_facts: list[dict[str, Any]],
    min_notable: int = 3,
    max_notable: int = 7,
) -> list[KpiScore]:
    """Score and rank all KPIs, returning them sorted by score descending.

    Guarantees at least *min_notable* KPIs are marked notable (so the brief
    always has content), capped at *max_notable*.
    """
    scores = [score_kpi(f["kpi_id"], f) for f in derived_facts]
    scores.sort(key=lambda s: s.score, reverse=True)

    notable_count = sum(1 for s in scores if s.notable)

    if notable_count < min_notable:
        for s in scores:
            if not s.notable:
                s.notable = True
                s.reasons.append("promoted (min-notable)")
                notable_count += 1
            if notable_count >= min_notable:
                break

    if notable_count > max_notable:
        seen = 0
        for s in scores:
            if s.notable:
                seen += 1
                if seen > max_notable:
                    s.notable = False

    return scores
```

---

## Related

- Where derived numbers come from: [01 — Derived facts & inflections](01-derived-facts-and-inflections.md)
- Article scoring (different formula): [04 — Article scoring & filtering](04-article-scoring-and-filtering.md)
- Full pipeline: [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)
