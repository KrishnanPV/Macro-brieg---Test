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
