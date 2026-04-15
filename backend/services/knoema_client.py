"""Oxford Economics / Knoema EAP data fetching service."""
from __future__ import annotations

import logging
from typing import Any

import knoema
import pandas as pd

from backend.config import EAP_HOST, EAP_APP_ID, EAP_APP_SECRET, DATASET
from backend.models.kpi_registry import SPECS_BY_ID, sorted_kpi_ids, resolve_unit_label
from backend.models.schemas import SeriesPoint, IndicatorSeries, KpiResult, FetchResponse

log = logging.getLogger(__name__)


def _parse_timerange(tr: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    parts = tr.split("-")
    start_year = int(parts[0])
    end_year = int(parts[1])
    return pd.Timestamp(f"{start_year}-01-01"), pd.Timestamp(f"{end_year}-12-31")


def _clip_points(
    points: list[SeriesPoint], start: pd.Timestamp, end: pd.Timestamp,
) -> list[SeriesPoint]:
    clipped = []
    for p in points:
        ts = pd.Timestamp(p.date)
        if start <= ts <= end:
            clipped.append(p)
    return clipped


def _configure_api() -> None:
    apicfg = knoema.ApiConfig()
    apicfg.host = EAP_HOST
    apicfg.app_id = EAP_APP_ID
    apicfg.app_secret = EAP_APP_SECRET


def _extract_unit_scale(meta_df: pd.DataFrame) -> tuple[str, str]:
    """Pull the Unit and Scale strings from the knoema metadata DataFrame."""
    if meta_df is None or meta_df.empty:
        return "", ""
    unit_val = ""
    scale_val = ""
    for col in meta_df.columns:
        series = meta_df[col]
        for idx_label, val in series.items():
            idx_str = str(idx_label)
            if "Unit" in idx_str and pd.notna(val):
                unit_val = str(val).strip()
            elif "Scale" in idx_str and pd.notna(val):
                scale_val = str(val).strip()
    return unit_val, scale_val


def _fetch_indicator(
    country: str,
    indicator: str,
    effective_freq: str,
    tr: str,
    clip_start: pd.Timestamp,
    clip_end: pd.Timestamp,
) -> tuple[IndicatorSeries | None, str]:
    """Fetch a single indicator series with metadata.

    Returns (series_or_None, error_string).
    """
    try:
        result = knoema.get(
            DATASET,
            True,  # include_metadata
            Location=country.strip(),
            Indicator=indicator,
            Frequency=effective_freq,
            timerange=tr,
        )

        if isinstance(result, tuple) and len(result) == 2:
            df, meta_df = result
        else:
            df = result
            meta_df = None

        if df is None or df.empty:
            return None, f"{country}/{indicator}: no data returned."

        raw_unit, raw_scale = _extract_unit_scale(meta_df)
        unit_label = resolve_unit_label(raw_unit, country)

        points: list[SeriesPoint] = []
        for idx, row in df.iterrows():
            ts = idx if not isinstance(idx, tuple) else idx[0]
            val = row.iloc[0]
            points.append(SeriesPoint(
                date=pd.Timestamp(ts).isoformat(),
                value=None if pd.isna(val) else float(val),
            ))
        points = _clip_points(points, clip_start, clip_end)
        if not points:
            return None, f"{country}/{indicator}: no data in selected range."

        return IndicatorSeries(
            country=country,
            indicator=indicator,
            points=points,
            unit=unit_label,
            scale=raw_scale,
        ), ""

    except Exception as exc:
        return None, f"{country}/{indicator}: {exc}"


def _fetch_all_indicators(
    countries: list[str],
    indicators: list[str],
    freq: str,
    tr: str,
    clip_start: pd.Timestamp,
    clip_end: pd.Timestamp,
) -> tuple[list[IndicatorSeries], list[str]]:
    """Fetch all indicators for given countries at a single frequency."""
    all_series: list[IndicatorSeries] = []
    errors: list[str] = []
    for country in countries:
        for indicator in indicators:
            series, err = _fetch_indicator(
                country, indicator, freq, tr, clip_start, clip_end,
            )
            if series:
                all_series.append(series)
            if err:
                errors.append(err)
    return all_series, errors


def fetch_kpi_data(
    countries: list[str],
    kpi_ids: list[str],
    timerange_q: str = "2015-2029",
    timerange_a: str = "2015-2026",
    frequency_overrides: dict[str, str] | None = None,
    dual_fetch: bool = False,
) -> FetchResponse:
    """Fetch data for multiple KPIs and countries from Knoema.

    When dual_fetch=True, quarterly-capable KPIs are fetched at both Q and A
    frequencies. The quarterly data goes into ``series`` and the annual data
    into ``series_annual``, allowing the frontend to switch without re-fetching.
    """
    _configure_api()
    timeranges = {"Q": timerange_q, "A": timerange_a}
    freq_overrides = frequency_overrides or {}
    results: list[KpiResult] = []

    for kpi_id in sorted_kpi_ids(kpi_ids):
        spec = SPECS_BY_ID.get(kpi_id)
        if not spec:
            results.append(KpiResult(kpi_id=kpi_id, kpi_name="Unknown", frequency="",
                                     native_frequency="", series=[],
                                     errors=[f"KPI {kpi_id} not found."]))
            continue
        if spec.source != "oxford":
            results.append(KpiResult(kpi_id=kpi_id, kpi_name=spec.name,
                                     frequency=spec.frequency, native_frequency=spec.frequency,
                                     series=[], errors=["Not available via Oxford EAP (IMF source)."]))
            continue

        effective_freq = freq_overrides.get(kpi_id, spec.frequency)
        if spec.frequency == "A" and effective_freq == "Q":
            effective_freq = "A"

        if dual_fetch and spec.frequency == "Q":
            # Fetch quarterly (primary)
            tr_q = timeranges["Q"]
            clip_q_start, clip_q_end = _parse_timerange(tr_q)
            q_series, q_errors = _fetch_all_indicators(
                countries, spec.indicators, "Q", tr_q, clip_q_start, clip_q_end,
            )
            # Fetch annual
            tr_a = timeranges["A"]
            clip_a_start, clip_a_end = _parse_timerange(tr_a)
            a_series, a_errors = _fetch_all_indicators(
                countries, spec.indicators, "A", tr_a, clip_a_start, clip_a_end,
            )
            kpi_unit = q_series[0].unit if q_series else (a_series[0].unit if a_series else "")
            results.append(KpiResult(
                kpi_id=kpi_id, kpi_name=spec.name, frequency="Q",
                native_frequency=spec.frequency, unit=kpi_unit,
                series=q_series, series_annual=a_series,
                errors=q_errors + a_errors,
            ))
        else:
            tr = timeranges.get(effective_freq, timeranges["A"])
            clip_start, clip_end = _parse_timerange(tr)
            all_series, errors = _fetch_all_indicators(
                countries, spec.indicators, effective_freq, tr, clip_start, clip_end,
            )
            kpi_unit = all_series[0].unit if all_series else ""
            results.append(KpiResult(
                kpi_id=kpi_id, kpi_name=spec.name, frequency=effective_freq,
                native_frequency=spec.frequency, unit=kpi_unit,
                series=all_series, errors=errors,
            ))

    return FetchResponse(results=results)


def fetch_single_kpi(
    countries: list[str],
    kpi_id: str,
    frequency: str,
    timerange_q: str = "2015-2029",
    timerange_a: str = "2015-2026",
) -> KpiResult:
    """Re-fetch a single KPI with a specific frequency (A or Q)."""
    _configure_api()
    spec = SPECS_BY_ID.get(kpi_id)
    if not spec:
        raise ValueError(f"KPI {kpi_id} not found.")
    if spec.source != "oxford":
        raise ValueError("Not available via Oxford EAP.")

    effective_freq = frequency
    if spec.frequency == "A" and effective_freq == "Q":
        effective_freq = "A"

    timeranges = {"Q": timerange_q, "A": timerange_a}
    tr = timeranges.get(effective_freq, timeranges["A"])
    clip_start, clip_end = _parse_timerange(tr)
    all_series: list[IndicatorSeries] = []
    errors: list[str] = []

    for country in countries:
        for indicator in spec.indicators:
            series, err = _fetch_indicator(
                country, indicator, effective_freq, tr, clip_start, clip_end,
            )
            if series:
                all_series.append(series)
            if err:
                errors.append(err)

    kpi_unit = all_series[0].unit if all_series else ""

    return KpiResult(
        kpi_id=kpi_id, kpi_name=spec.name, frequency=effective_freq,
        native_frequency=spec.frequency, unit=kpi_unit,
        series=all_series, errors=errors,
    )
