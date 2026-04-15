"""Workspace CRUD, notebook cells, and context document endpoints."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db import (
    get_session, Workspace, NotebookCell, ContextDocument,
)
from backend.models.schemas import (
    WorkspaceCreate, WorkspaceUpdate, WorkspaceOut,
    NotebookCellCreate, NotebookCellUpdate, NotebookCellOut,
    ContextDocCreate, ContextDocOut,
)

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
    await db.delete(ws)
    await db.commit()


# ---------------------------------------------------------------------------
# Notebook Cells
# ---------------------------------------------------------------------------

@router.get("/{ws_id}/cells", response_model=list[NotebookCellOut])
async def list_cells(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(NotebookCell)
        .where(NotebookCell.workspace_id == ws_id)
        .order_by(NotebookCell.position)
    )
    return [_cell_out(c) for c in result.scalars().all()]


@router.post("/{ws_id}/cells", response_model=NotebookCellOut, status_code=201)
async def create_cell(ws_id: str, body: NotebookCellCreate, db: AsyncSession = Depends(get_session)):
    ws = await db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    if body.position is None:
        result = await db.execute(
            select(func.coalesce(func.max(NotebookCell.position), -1))
            .where(NotebookCell.workspace_id == ws_id)
        )
        body.position = result.scalar() + 1

    cell = NotebookCell(
        workspace_id=ws_id,
        cell_type=body.cell_type,
        content=body.content,
        position=body.position,
    )
    cell.cell_meta = body.metadata
    db.add(cell)
    await db.commit()
    await db.refresh(cell)
    return _cell_out(cell)


@router.patch("/{ws_id}/cells/{cell_id}", response_model=NotebookCellOut)
async def update_cell(ws_id: str, cell_id: str, body: NotebookCellUpdate, db: AsyncSession = Depends(get_session)):
    cell = await db.get(NotebookCell, cell_id)
    if not cell or cell.workspace_id != ws_id:
        raise HTTPException(404, "Cell not found")
    if body.content is not None:
        cell.content = body.content
    if body.metadata is not None:
        cell.cell_meta = body.metadata
    if body.position is not None:
        cell.position = body.position
    await db.commit()
    await db.refresh(cell)
    return _cell_out(cell)


@router.delete("/{ws_id}/cells/{cell_id}", status_code=204)
async def delete_cell(ws_id: str, cell_id: str, db: AsyncSession = Depends(get_session)):
    cell = await db.get(NotebookCell, cell_id)
    if not cell or cell.workspace_id != ws_id:
        raise HTTPException(404, "Cell not found")
    await db.delete(cell)
    await db.commit()


# ---------------------------------------------------------------------------
# Context Documents
# ---------------------------------------------------------------------------

@router.get("/{ws_id}/documents", response_model=list[ContextDocOut])
async def list_documents(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(ContextDocument)
        .where(ContextDocument.workspace_id == ws_id)
        .order_by(ContextDocument.created_at.desc())
    )
    return [_doc_out(d) for d in result.scalars().all()]


@router.post("/{ws_id}/documents", response_model=ContextDocOut, status_code=201)
async def create_document(ws_id: str, body: ContextDocCreate, db: AsyncSession = Depends(get_session)):
    ws = await db.get(Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    doc = ContextDocument(
        workspace_id=ws_id,
        title=body.title,
        content=body.content,
        doc_type=body.doc_type,
        source_url=body.source_url,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


@router.delete("/{ws_id}/documents/{doc_id}", status_code=204)
async def delete_document(ws_id: str, doc_id: str, db: AsyncSession = Depends(get_session)):
    doc = await db.get(ContextDocument, doc_id)
    if not doc or doc.workspace_id != ws_id:
        raise HTTPException(404, "Document not found")
    await db.delete(doc)
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


def _cell_out(cell: NotebookCell) -> dict[str, Any]:
    return {
        "id": cell.id,
        "workspace_id": cell.workspace_id,
        "cell_type": cell.cell_type,
        "content": cell.content,
        "metadata": cell.cell_meta,
        "position": cell.position,
        "created_at": cell.created_at.isoformat() if cell.created_at else "",
        "updated_at": cell.updated_at.isoformat() if cell.updated_at else "",
    }


def _doc_out(doc: ContextDocument) -> dict[str, Any]:
    return {
        "id": doc.id,
        "workspace_id": doc.workspace_id,
        "title": doc.title,
        "content": doc.content,
        "doc_type": doc.doc_type,
        "source_url": doc.source_url,
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
    }
