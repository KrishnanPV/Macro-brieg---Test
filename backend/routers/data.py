"""Data endpoints: KPI catalogue, data fetching."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.config import EAP_HOST, EAP_APP_ID, EAP_APP_SECRET
from backend.models.kpi_registry import SPECS
from backend.models.schemas import (
    KpiInfo, FetchRequest, FetchResponse, RefetchKpiRequest, KpiResult,
)
from backend.services.knoema_client import fetch_kpi_data, fetch_single_kpi

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/kpis", response_model=list[KpiInfo])
def list_kpis():
    return [
        KpiInfo(
            id=s.id, name=s.name, source=s.source, frequency=s.frequency,
            indicators=s.indicators, notes=s.notes,
            available=(s.source == "oxford"),
        )
        for s in SPECS
    ]


@router.post("/fetch", response_model=FetchResponse)
def fetch_data(req: FetchRequest):
    if not EAP_HOST:
        raise HTTPException(500, "EAP_HOST is not configured in .env.")
    if not EAP_APP_ID or not EAP_APP_SECRET:
        raise HTTPException(500, "EAP_APP_ID / EAP_APP_SECRET not configured in .env.")
    if not req.countries:
        raise HTTPException(400, "Select at least one country.")
    if not req.kpi_ids:
        raise HTTPException(400, "Select at least one KPI.")

    return fetch_kpi_data(
        countries=req.countries,
        kpi_ids=req.kpi_ids,
        timerange_q=req.timerange_q,
        timerange_a=req.timerange_a,
        frequency_overrides=req.frequency_overrides,
    )


@router.post("/fetch-kpi", response_model=KpiResult)
def fetch_single(req: RefetchKpiRequest):
    if not EAP_HOST or not EAP_APP_ID or not EAP_APP_SECRET:
        raise HTTPException(500, "EAP credentials not configured in .env.")
    try:
        return fetch_single_kpi(
            countries=req.countries,
            kpi_id=req.kpi_id,
            frequency=req.frequency,
            timerange_q=req.timerange_q,
            timerange_a=req.timerange_a,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
