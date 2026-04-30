"""Detect notable Signals from KPI derived facts."""
from __future__ import annotations

import logging
from typing import Any

from backend.services.derived_facts import compute_derived_facts
from backend.models.insights import Signal
from backend.models.kpi_registry import INSIGHT_LENSES
from backend.services.kpi_triage import KpiScore

log = logging.getLogger(__name__)


def _lens_hint(kpi_id: str) -> str:
    """Return a short analytical hint from the insight lens for a KPI.

    Appended to signal descriptions so downstream agents (interpreter, researcher)
    get domain-specific context without a separate lookup.
    """
    lens = INSIGHT_LENSES.get(kpi_id)
    if not lens:
        return ""
    parts: list[str] = []
    if lens.forbidden_claims:
        parts.append(f"Note: {lens.forbidden_claims[0]}")
    if lens.context_hooks:
        parts.append(f"Consider: {lens.context_hooks[0]}")
    return " | ".join(parts)

_MAX_SIGNALS_FOR_INTERPRETER = 20


def rank_signals(
    signals: list[Signal],
    triage_scores: list[KpiScore],
) -> list[Signal]:
    """Rank signals by composite score and cap at _MAX_SIGNALS_FOR_INTERPRETER.

    Composite = abs(magnitude_pct) * kpi_triage_score. Signals from higher-scoring
    KPIs and with larger magnitude are ranked first, ensuring the interpreter sees
    the most analytically significant signals rather than a noisy dump.
    """
    if len(signals) <= _MAX_SIGNALS_FOR_INTERPRETER:
        return signals

    kpi_score_map: dict[str, float] = {s.kpi_id: s.score for s in triage_scores}

    def _composite(sig: Signal) -> float:
        triage = kpi_score_map.get(sig.kpi_id, 1.0)
        return abs(sig.magnitude_pct) * max(triage, 0.1)

    ranked = sorted(signals, key=_composite, reverse=True)
    kept = ranked[:_MAX_SIGNALS_FOR_INTERPRETER]

    log.info(
        "Signal pre-filter: %d -> %d (dropped %d low-scoring signals)",
        len(signals), len(kept), len(signals) - len(kept),
    )
    return kept

_BORING_CAGR: dict[str, float] = {
    "9": 0.5,
    "5": 1.0,
    "6": 3.0,
}
_DEFAULT_BORING_CAGR = 1.5

_TREND_SEGMENT_MIN_PCT = 8.0
_OUTSIZED_MOVE_MIN_PCT = 5.0


_SCALE_WORDS: dict[str, float] = {
    "billions": 1e9, "billion": 1e9,
    "millions": 1e6, "million": 1e6,
    "thousands": 1e3, "thousand": 1e3,
}


def _scale_multiplier(unit: str) -> float:
    for token in unit.lower().split():
        if token in _SCALE_WORDS:
            return _SCALE_WORDS[token]
    return 1.0


def _currency_code(unit: str) -> str:
    if not unit or unit.startswith("%"):
        return ""
    first = unit.split()[0]
    if first.lower() in _SCALE_WORDS:
        return ""
    return first


def _fmt_val(v: float, unit: str = "") -> str:
    """Format a number with optional currency suffix (e.g. '~690B SAR')."""
    display = v * _scale_multiplier(unit)
    av = abs(display)
    if av >= 1_000_000_000:
        num = f"~{display / 1e9:.1f}B"
    elif av >= 1_000_000:
        num = f"~{display / 1e6:.1f}M"
    elif av >= 1_000:
        num = f"~{display / 1e3:.0f}K"
    else:
        num = f"{display:.1f}"
    ccy = _currency_code(unit)
    if ccy:
        return f"{num} {ccy}"
    return num


def _year(date_str: str) -> str:
    return date_str[:4] if date_str else "?"


def extract_signals(kpi_results: list[dict[str, Any]]) -> list[Signal]:
    """Run derived-facts computation and convert to structured Signal objects."""
    derived = compute_derived_facts(kpi_results)
    signals: list[Signal] = []

    for kpi_facts in derived:
        kpi_id = str(kpi_facts["kpi_id"])
        kpi_name = kpi_facts.get("kpi_name", f"KPI {kpi_id}")
        kpi_unit = kpi_facts.get("unit", "")
        hint = _lens_hint(kpi_id)

        for sf in kpi_facts.get("series_facts", []):
            if sf.get("note"):
                continue
            country = sf.get("country", "")
            unit = sf.get("unit", "") or kpi_unit

            for ip in sf.get("inflection_points", []):
                pct = ip.get("pct_change", 0)
                reason = ip.get("reason", "outsized_move")
                sig_type = "sign_reversal" if reason == "sign_reversal" else "inflection_point"
                direction = "increase" if pct > 0 else "decline"

                prior = sf.get("prior", {})
                from_date = prior.get("date", sf.get("earliest", {}).get("date", ""))
                from_val = prior.get("value", sf.get("earliest", {}).get("value", 0))

                desc = (
                    f"{kpi_name} {'reversed direction with' if sig_type == 'sign_reversal' else 'showed'} "
                    f"a {abs(pct):.1f}% {direction} reaching {_fmt_val(ip['value'], unit)} "
                    f"in {_year(ip['date'])}"
                )
                if hint:
                    desc += f" [{hint}]"
                signals.append(Signal(
                    kpi_id=kpi_id,
                    kpi_name=kpi_name,
                    country=country,
                    signal_type=sig_type,
                    from_date=from_date,
                    to_date=ip["date"],
                    from_value=from_val,
                    to_value=ip["value"],
                    magnitude_pct=round(pct, 2),
                    description=desc,
                ))

            for seg in sf.get("trend_segments", []):
                total_pct = seg.get("total_pct_change")
                if total_pct is None or abs(total_pct) < _TREND_SEGMENT_MIN_PCT:
                    continue
                direction_word = "growth" if seg["direction"] == "rising" else "decline"
                desc = (
                    f"Sustained {direction_word} in {kpi_name}: "
                    f"{_fmt_val(seg['from_value'], unit)} → {_fmt_val(seg['to_value'], unit)} "
                    f"({total_pct:+.1f}%) over {seg['periods']} periods "
                    f"({_year(seg['from_date'])}–{_year(seg['to_date'])})"
                )
                if hint:
                    desc += f" [{hint}]"
                signals.append(Signal(
                    kpi_id=kpi_id,
                    kpi_name=kpi_name,
                    country=country,
                    signal_type="trend_segment",
                    from_date=seg["from_date"],
                    to_date=seg["to_date"],
                    from_value=seg["from_value"],
                    to_value=seg["to_value"],
                    magnitude_pct=round(total_pct, 2),
                    description=desc,
                ))

            cagr = sf.get("cagr")
            if cagr:
                boring = _BORING_CAGR.get(kpi_id, _DEFAULT_BORING_CAGR)
                if abs(cagr["cagr_pct"]) > boring:
                    direction_word = "growth" if cagr["cagr_pct"] > 0 else "contraction"
                    unit_suffix = f" [{unit}]" if unit and not unit.startswith("%") else ""
                    desc = (
                        f"{kpi_name} showed notable {direction_word} at "
                        f"{cagr['cagr_pct']:+.1f}% CAGR over {cagr['years']:.0f} years "
                        f"({_year(cagr['from'])}–{_year(cagr['to'])}){unit_suffix}"
                    )
                    if hint:
                        desc += f" [{hint}]"
                    signals.append(Signal(
                        kpi_id=kpi_id,
                        kpi_name=kpi_name,
                        country=country,
                        signal_type="cagr_notable",
                        from_date=cagr["from"],
                        to_date=cagr["to"],
                        from_value=sf["earliest"]["value"],
                        to_value=sf["latest"]["value"],
                        magnitude_pct=round(cagr["cagr_pct"], 2),
                        description=desc,
                    ))

            pop = sf.get("period_over_period", [])
            all_pcts = [c.get("pct_change") for c in pop if c.get("pct_change") is not None]
            if all_pcts:
                mean_abs = sum(abs(p) for p in all_pcts) / len(all_pcts)
                threshold = max(mean_abs * 2.0, _OUTSIZED_MOVE_MIN_PCT)
                for chg in pop:
                    pct = chg.get("pct_change")
                    if pct is None or abs(pct) < threshold:
                        continue
                    inflection_dates = {ip["date"] for ip in sf.get("inflection_points", [])}
                    if chg["to_date"] in inflection_dates:
                        continue
                    direction = "jump" if pct > 0 else "drop"
                    desc = (
                        f"{kpi_name}: outsized {direction} of {abs(pct):.1f}% "
                        f"({_fmt_val(chg['from_value'], unit)} → {_fmt_val(chg['to_value'], unit)}) "
                        f"from {_year(chg['from_date'])} to {_year(chg['to_date'])}"
                    )
                    if hint:
                        desc += f" [{hint}]"
                    signals.append(Signal(
                        kpi_id=kpi_id,
                        kpi_name=kpi_name,
                        country=country,
                        signal_type="outsized_period_change",
                        from_date=chg["from_date"],
                        to_date=chg["to_date"],
                        from_value=chg["from_value"],
                        to_value=chg["to_value"],
                        magnitude_pct=round(pct, 2),
                        description=desc,
                    ))

    # ── Composition, divergence, net-flow, and period-highlight signals ──
    for kpi_facts in derived:
        kid = str(kpi_facts["kpi_id"])
        kname = kpi_facts.get("kpi_name", f"KPI {kid}")
        h = _lens_hint(kid)
        first_country = ""
        for sf in kpi_facts.get("series_facts", []):
            if sf.get("country"):
                first_country = sf["country"]
                break

        composition = kpi_facts.get("composition", [])
        shift_summary = next(
            (c for c in composition if c.get("type") == "share_shift_summary"), None,
        )
        if shift_summary:
            for ind, pp in shift_summary.get("shifts_pp", {}).items():
                if abs(pp) < 3.0:
                    continue
                direction = "gained" if pp > 0 else "lost"
                desc = (
                    f"{ind} {direction} {abs(pp):.1f}pp share of {kname} "
                    f"({_year(shift_summary['from_date'])}–{_year(shift_summary['to_date'])})"
                )
                if h:
                    desc += f" [{h}]"
                signals.append(Signal(
                    kpi_id=kid, kpi_name=kname, country=first_country,
                    signal_type="share_shift",
                    from_date=shift_summary["from_date"],
                    to_date=shift_summary["to_date"],
                    from_value=0, to_value=pp,
                    magnitude_pct=round(abs(pp), 2),
                    description=desc,
                ))

        growth_gap = kpi_facts.get("growth_gap", [])
        if growth_gap:
            max_gap = max(growth_gap, key=lambda g: abs(g.get("gap_pp", 0)))
            gap_pp = max_gap.get("gap_pp", 0)
            if abs(gap_pp) >= 5.0:
                faster = max_gap.get("faster", "")
                desc = (
                    f"{kname}: growth divergence of {abs(gap_pp):.1f}pp — "
                    f"{faster} outpaced in {_year(max_gap['date'])}"
                )
                if h:
                    desc += f" [{h}]"
                signals.append(Signal(
                    kpi_id=kid, kpi_name=kname, country=first_country,
                    signal_type="growth_divergence",
                    from_date=growth_gap[0]["date"],
                    to_date=max_gap["date"],
                    from_value=0, to_value=gap_pp,
                    magnitude_pct=round(abs(gap_pp), 2),
                    description=desc,
                ))

        net_flow = kpi_facts.get("net_flow", [])
        if len(net_flow) >= 2:
            for i in range(1, len(net_flow)):
                prev_dir = net_flow[i - 1].get("direction", "")
                curr_dir = net_flow[i].get("direction", "")
                if prev_dir and curr_dir and prev_dir != curr_dir:
                    desc = (
                        f"{kname}: net flow reversed from {prev_dir.replace('_', ' ')} "
                        f"to {curr_dir.replace('_', ' ')} in {_year(net_flow[i]['date'])}"
                    )
                    if h:
                        desc += f" [{h}]"
                    signals.append(Signal(
                        kpi_id=kid, kpi_name=kname, country=first_country,
                        signal_type="net_flow_reversal",
                        from_date=net_flow[i - 1]["date"],
                        to_date=net_flow[i]["date"],
                        from_value=net_flow[i - 1]["net"],
                        to_value=net_flow[i]["net"],
                        magnitude_pct=round(abs(net_flow[i]["net"] - net_flow[i - 1]["net"]), 2),
                        description=desc,
                    ))
                    break

    if signals:
        best = max(signals, key=lambda s: abs(s.magnitude_pct))
        signals.append(Signal(
            kpi_id=best.kpi_id, kpi_name=best.kpi_name, country=best.country,
            signal_type="period_highlight",
            from_date=best.from_date, to_date=best.to_date,
            from_value=best.from_value, to_value=best.to_value,
            magnitude_pct=best.magnitude_pct,
            description=f"Period highlight: {best.description}",
        ))

    return signals
