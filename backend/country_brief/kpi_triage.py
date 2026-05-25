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


_BORING_CAGR: dict[str, float] = {
    "9": 0.5,    # population — any direction change >0.5% or decline is notable
    "5": 1.0,    # unemployment — < 1pp change is noise
    "6": 3.0,    # consumption — steady single-digit growth is expected
    "13": 4.0,   # trade — exports/imports typically grow at high single digits
    "14": 5.0,   # fiscal — government revenue/expenditure track nominal economy
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

    if kpi_id in ("2", "3", "11", "12"):
        # Core growth / structure KPIs always carry baseline notability.
        score += 1.0

    if kpi_id == "5":
        for sf in series_facts:
            if sf.get("note"):
                continue
            latest = sf.get("latest", {}).get("value")
            if latest is not None and (latest > 8.0 or latest < 3.0):
                score += 1.5
                reasons.append(f"level {latest:.1f}% notable")
                break

    if kpi_id == "9":
        for sf in series_facts:
            if sf.get("note"):
                continue
            cagr_info = sf.get("cagr")
            if cagr_info and cagr_info["cagr_pct"] < 0:
                score += 3.0
                reasons.append("population decline")
                break

    if kpi_id == "12":
        # Growth split is notable when oil and non-oil growth diverge sharply.
        latest_by_series: dict[str, float] = {}
        for sf in series_facts:
            if sf.get("note"):
                continue
            ind = str(sf.get("indicator", "")).lower()
            latest = (sf.get("latest") or {}).get("value")
            if latest is None:
                continue
            if "non-oil" in ind:
                latest_by_series["non_oil"] = latest
            elif "oil" in ind:
                latest_by_series.setdefault("oil", latest)
        oil = latest_by_series.get("oil")
        non_oil = latest_by_series.get("non_oil")
        if oil is not None and non_oil is not None and abs(oil - non_oil) > 2.0:
            score += 1.5
            reasons.append(f"oil/non-oil growth gap {oil - non_oil:+.1f}pp")

    if kpi_id == "13":
        # Trade balance flips or wide gaps between exports and imports are notable.
        # KPI 13 series are now [Oil exports, Non-oil exports, Oil imports, Non-oil imports];
        # sum the two legs per side to recover totals for the balance calculation.
        totals: dict[str, float] = {}
        oil_share_export: float | None = None
        for sf in series_facts:
            if sf.get("note"):
                continue
            ind = str(sf.get("indicator", "")).lower()
            latest = (sf.get("latest") or {}).get("value")
            if latest is None:
                continue
            side = "export" if "export" in ind else ("import" if "import" in ind else None)
            if side is None:
                continue
            totals[side] = totals.get(side, 0.0) + latest
            if side == "export" and "non-oil" not in ind and "oil" in ind:
                # Track latest oil-export level for share computation below.
                totals["__oil_export"] = latest
        exp = totals.get("export")
        imp = totals.get("import")
        if exp is not None and imp is not None and imp:
            balance_share = (exp - imp) / abs(imp) * 100
            if abs(balance_share) > 15:
                score += 1.5
                reasons.append(f"trade balance {balance_share:+.1f}% of imports")
        oil_exp = totals.get("__oil_export")
        if exp and oil_exp is not None and exp:
            oil_share_export = oil_exp / exp * 100
            # Flag heavy oil concentration (>50%) — relevant for diversification framing.
            if oil_share_export > 50:
                score += 1.0
                reasons.append(f"oil = {oil_share_export:.0f}% of exports")

    if kpi_id == "14":
        # Fiscal balance swings (revenue vs expenditure gap) are notable.
        levels: dict[str, float] = {}
        for sf in series_facts:
            if sf.get("note"):
                continue
            ind = str(sf.get("indicator", "")).lower()
            latest = (sf.get("latest") or {}).get("value")
            if latest is None:
                continue
            if "revenue" in ind:
                levels.setdefault("revenue", latest)
            elif "expenditure" in ind:
                levels.setdefault("expenditure", latest)
        rev = levels.get("revenue")
        exp = levels.get("expenditure")
        if rev is not None and exp is not None and exp:
            deficit_share = (rev - exp) / abs(exp) * 100
            if abs(deficit_share) > 10:
                score += 1.5
                reasons.append(f"fiscal balance {deficit_share:+.1f}% of expenditure")

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
