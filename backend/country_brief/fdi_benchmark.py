"""FDI benchmark payload builder for Country Brief KPI 4 chart."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from typing import Any

from backend.models.kpi_registry import ISO3_TO_NAME


@dataclass
class _CountryFlowWindow:
    start_value: float | None
    end_value: float | None
    start_year_used: int | None
    end_year_used: int | None
    cagr: float | None


def _indicator_flow(indicator: str) -> str | None:
    lowered = (indicator or "").lower()
    if "inward" in lowered:
        return "inflow"
    if "outward" in lowered:
        return "outflow"
    return None


def _points_to_year_values(points: list[dict[str, Any]], *, start_year: int, end_year: int) -> list[tuple[int, float]]:
    rows: list[tuple[int, float]] = []
    for p in points or []:
        value = p.get("value")
        if value is None:
            continue
        date = p.get("date")
        if not date:
            continue
        try:
            year = datetime.fromisoformat(str(date).replace("Z", "+00:00")).year
        except Exception:
            continue
        if start_year <= year <= end_year:
            rows.append((year, float(value)))
    rows.sort(key=lambda x: x[0])
    return rows


def _pick_value(year_values: list[tuple[int, float]], target_year: int) -> tuple[float | None, int | None]:
    if not year_values:
        return None, None
    exact = [yv for yv in year_values if yv[0] == target_year]
    if exact:
        return exact[-1][1], target_year
    nearest_year, nearest_val = min(
        year_values,
        key=lambda yv: (abs(yv[0] - target_year), yv[0]),
    )
    return nearest_val, nearest_year


def _cagr(start_value: float | None, end_value: float | None, start_year: int | None, end_year: int | None) -> float | None:
    if start_value is None or end_value is None:
        return None
    if start_year is None or end_year is None or end_year <= start_year:
        return None
    # CAGR is undefined for non-positive bases in this context.
    if start_value <= 0 or end_value <= 0:
        return None
    n = end_year - start_year
    return (end_value / start_value) ** (1.0 / n) - 1.0


def _build_flow_window(points: list[dict[str, Any]], *, start_year: int, end_year: int) -> _CountryFlowWindow:
    year_values = _points_to_year_values(points, start_year=start_year, end_year=end_year)
    start_value, start_year_used = _pick_value(year_values, start_year)
    end_value, end_year_used = _pick_value(year_values, end_year)
    return _CountryFlowWindow(
        start_value=start_value,
        end_value=end_value,
        start_year_used=start_year_used,
        end_year_used=end_year_used,
        cagr=_cagr(start_value, end_value, start_year_used, end_year_used),
    )


def _has_complete_flow(country_row: dict[str, Any], flow: str) -> bool:
    payload = country_row.get(flow) or {}
    return payload.get("start") is not None and payload.get("end") is not None


def _country_has_required_data(country_row: dict[str, Any]) -> bool:
    return _has_complete_flow(country_row, "inflow") and _has_complete_flow(country_row, "outflow")


def _flow_end_value(country_row: dict[str, Any], flow: str) -> float | None:
    payload = country_row.get(flow) or {}
    value = payload.get("end")
    if value is None:
        return None
    return float(value)


def _scale_distance(candidate_row: dict[str, Any], target_row: dict[str, Any]) -> float:
    distances: list[float] = []
    for flow in ("inflow", "outflow"):
        candidate = _flow_end_value(candidate_row, flow)
        target = _flow_end_value(target_row, flow)
        if candidate is None or target is None:
            continue
        # Log-ratio distance keeps scale comparisons symmetric.
        distances.append(abs(math.log((abs(candidate) + 1.0) / (abs(target) + 1.0))))
    if not distances:
        return float("inf")
    return sum(distances) / len(distances)


def _rank_candidates_by_similarity(
    candidates: list[str],
    *,
    target_row: dict[str, Any],
    country_rows: dict[str, dict[str, Any]],
) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for code in candidates:
        if code in seen:
            continue
        row = country_rows.get(code)
        if not row or not _country_has_required_data(row):
            continue
        deduped.append(code)
        seen.add(code)
    return sorted(
        deduped,
        key=lambda code: _scale_distance(country_rows[code], target_row),
    )


def _fill_group(
    ranked_candidates: list[str],
    *,
    chosen: set[str],
    target_row: dict[str, Any],
    country_rows: dict[str, dict[str, Any]],
    target_count: int = 2,
    max_distance: float = 1.6,
) -> list[str]:
    out: list[str] = []
    # Pass 1: only comparable-scale peers (about <=5x distance in log-space).
    for code in ranked_candidates:
        if code in chosen:
            continue
        row = country_rows.get(code)
        if not row or not _country_has_required_data(row):
            continue
        if _scale_distance(row, target_row) > max_distance:
            continue
        out.append(code)
        if len(out) >= target_count:
            break

    # Pass 2: fallback to closest remaining peers if needed.
    if len(out) < target_count:
        for code in ranked_candidates:
            if code in chosen or code in out:
                continue
            row = country_rows.get(code)
            if not row or not _country_has_required_data(row):
                continue
            out.append(code)
            if len(out) >= target_count:
                break

    return out


def build_fdi_benchmark_payload(
    *,
    target_country: str,
    start_year: int,
    end_year: int,
    fdi_result: dict[str, Any],
    benchmark_selection: dict[str, Any],
) -> dict[str, Any] | None:
    """Build normalized payload for the frontend FDI benchmark chart."""
    if not fdi_result:
        return None

    target = target_country.upper()
    series = fdi_result.get("series") or []
    if not series:
        return None

    country_rows: dict[str, dict[str, Any]] = {}
    for s in series:
        country = str(s.get("country", "")).upper().strip()
        if not country:
            continue
        flow = _indicator_flow(str(s.get("indicator", "")))
        if flow is None:
            continue
        if country not in country_rows:
            country_rows[country] = {
                "country_code": country,
                "country_name": ISO3_TO_NAME.get(country, country),
            }
        window = _build_flow_window(
            s.get("points") or [],
            start_year=start_year,
            end_year=end_year,
        )
        country_rows[country][flow] = {
            "start": window.start_value,
            "end": window.end_value,
            "start_year_used": window.start_year_used,
            "end_year_used": window.end_year_used,
            "cagr": window.cagr,
        }

    target_row = country_rows.get(target)
    if not target_row or not _country_has_required_data(target_row):
        return None

    preferred_global = [str(c).upper() for c in benchmark_selection.get("global", [])]
    preferred_regional = [str(c).upper() for c in benchmark_selection.get("regional", [])]
    global_pool = [str(c).upper() for c in benchmark_selection.get("global_pool", [])]
    regional_pool = [str(c).upper() for c in benchmark_selection.get("regional_pool", [])]
    backfill_pool = [str(c).upper() for c in benchmark_selection.get("backfill_pool", [])]

    chosen: set[str] = {target}
    ranked_global = _rank_candidates_by_similarity(
        [*preferred_global, *global_pool],
        target_row=target_row,
        country_rows=country_rows,
    )
    final_global = _fill_group(
        ranked_global,
        chosen=chosen,
        target_row=target_row,
        country_rows=country_rows,
        target_count=2,
    )
    chosen.update(final_global)
    ranked_regional = _rank_candidates_by_similarity(
        [*preferred_regional, *regional_pool],
        target_row=target_row,
        country_rows=country_rows,
    )
    final_regional = _fill_group(
        ranked_regional,
        chosen=chosen,
        target_row=target_row,
        country_rows=country_rows,
        target_count=2,
    )
    chosen.update(final_regional)

    if len(final_global) < 2 or len(final_regional) < 2:
        ranked_backfill = _rank_candidates_by_similarity(
            backfill_pool,
            target_row=target_row,
            country_rows=country_rows,
        )
        for code in ranked_backfill:
            if code in chosen:
                continue
            row = country_rows.get(code)
            if not row or not _country_has_required_data(row):
                continue
            if len(final_global) < 2:
                final_global.append(code)
                chosen.add(code)
                continue
            if len(final_regional) < 2:
                final_regional.append(code)
                chosen.add(code)
            if len(final_global) >= 2 and len(final_regional) >= 2:
                break

    selected_codes = [*final_global, target, *final_regional]
    selected_rows = []
    for code in selected_codes:
        row = country_rows.get(code)
        if not row:
            continue
        if code in final_global:
            bucket = "global"
        elif code in final_regional:
            bucket = "regional"
        else:
            bucket = "target"
        row = {**row, "bucket": bucket}
        selected_rows.append(row)

    if not selected_rows:
        return None

    inflow_sorted = sorted(
        selected_rows,
        key=lambda row: (row.get("inflow", {}).get("end") is not None, row.get("inflow", {}).get("end") or float("-inf")),
        reverse=True,
    )
    outflow_sorted = sorted(
        selected_rows,
        key=lambda row: (row.get("outflow", {}).get("end") is not None, row.get("outflow", {}).get("end") or float("-inf")),
        reverse=True,
    )

    return {
        "target_country": target,
        "start_year": start_year,
        "end_year": end_year,
        "unit": fdi_result.get("unit", ""),
        "global_peers": final_global[:2],
        "regional_peers": final_regional[:2],
        "countries": selected_rows,
        "sorted_country_codes": {
            "inflow": [r["country_code"] for r in inflow_sorted],
            "outflow": [r["country_code"] for r in outflow_sorted],
        },
    }
