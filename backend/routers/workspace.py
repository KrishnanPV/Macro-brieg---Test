"""Workspace CRUD endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db import get_session, purge_legacy_workspace_rows, Workspace
from backend.models.schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceOut

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(body: WorkspaceCreate, db: AsyncSession = Depends(get_session)):
    ws = Workspace(name=body.name, description=body.description)
    ws.countries = body.countries
    ws.kpi_ids = body.kpi_ids
    ws.country_brief = body.country_brief
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return _ws_out(ws)


@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(db: AsyncSession = Depends(get_session)):
    result = await db.execute(select(Workspace).order_by(Workspace.updated_at.desc()))
    return [_ws_out(ws) for ws in result.scalars().all()]


@router.get("/{ws_id}", response_model=WorkspaceOut)
async def get_workspace(ws_id: str, db: AsyncSession = Depends(get_session)):
    ws = await db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return _ws_out(ws)


@router.patch("/{ws_id}", response_model=WorkspaceOut)
async def update_workspace(ws_id: str, body: WorkspaceUpdate, db: AsyncSession = Depends(get_session)):
    ws = await db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description
    if body.countries is not None:
        ws.countries = body.countries
    if body.kpi_ids is not None:
        ws.kpi_ids = body.kpi_ids
    if body.country_brief is not None:
        ws.country_brief = body.country_brief
    await db.commit()
    await db.refresh(ws)
    return _ws_out(ws)


@router.delete("/{ws_id}", status_code=204)
async def delete_workspace(ws_id: str, db: AsyncSession = Depends(get_session)):
    ws = await db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    await purge_legacy_workspace_rows(db, ws_id)
    await db.delete(ws)
    await db.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws_out(ws: Workspace) -> dict[str, Any]:
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description,
        "countries": ws.countries,
        "kpi_ids": ws.kpi_ids,
        "country_brief": ws.country_brief,
        "created_at": ws.created_at.isoformat() if ws.created_at else "",
        "updated_at": ws.updated_at.isoformat() if ws.updated_at else "",
    }
