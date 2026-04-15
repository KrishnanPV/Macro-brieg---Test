"""Export endpoints: PPT, PDF, Markdown generation from briefs."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db import get_session, Brief
from backend.models.schemas import BriefCreate, BriefUpdate, BriefOut
from backend.services.export_engine import brief_to_export_format

router = APIRouter(prefix="/api/workspaces/{ws_id}/briefs", tags=["briefs"])


# ---------------------------------------------------------------------------
# Brief CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[BriefOut])
async def list_briefs(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(Brief).where(Brief.workspace_id == ws_id).order_by(Brief.updated_at.desc())
    )
    return [_brief_out(b) for b in result.scalars().all()]


@router.post("", response_model=BriefOut, status_code=201)
async def create_brief(ws_id: str, body: BriefCreate, db: AsyncSession = Depends(get_session)):
    brief = Brief(
        workspace_id=ws_id,
        title=body.title,
        template=body.template,
    )
    brief.content = body.content
    db.add(brief)
    await db.commit()
    await db.refresh(brief)
    return _brief_out(brief)


@router.get("/{brief_id}", response_model=BriefOut)
async def get_brief(ws_id: str, brief_id: str, db: AsyncSession = Depends(get_session)):
    brief = await db.get(Brief, brief_id)
    if not brief or brief.workspace_id != ws_id:
        raise HTTPException(404, "Brief not found")
    return _brief_out(brief)


@router.patch("/{brief_id}", response_model=BriefOut)
async def update_brief(ws_id: str, brief_id: str, body: BriefUpdate, db: AsyncSession = Depends(get_session)):
    brief = await db.get(Brief, brief_id)
    if not brief or brief.workspace_id != ws_id:
        raise HTTPException(404, "Brief not found")
    if body.title is not None:
        brief.title = body.title
    if body.content is not None:
        brief.content = body.content
    await db.commit()
    await db.refresh(brief)
    return _brief_out(brief)


@router.delete("/{brief_id}", status_code=204)
async def delete_brief(ws_id: str, brief_id: str, db: AsyncSession = Depends(get_session)):
    brief = await db.get(Brief, brief_id)
    if not brief or brief.workspace_id != ws_id:
        raise HTTPException(404, "Brief not found")
    await db.delete(brief)
    await db.commit()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/{brief_id}/export/{fmt}")
async def export_brief(ws_id: str, brief_id: str, fmt: str, db: AsyncSession = Depends(get_session)):
    """Export a brief as PPTX, Markdown, or JSON."""
    brief = await db.get(Brief, brief_id)
    if not brief or brief.workspace_id != ws_id:
        raise HTTPException(404, "Brief not found")

    brief_data = {
        "title": brief.title,
        "template": brief.template,
        "content": brief.content,
    }

    try:
        content, mime = brief_to_export_format(brief_data, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if isinstance(content, bytes):
        filename = f"{brief.title.replace(' ', '_')}.{fmt}"
        return Response(
            content=content,
            media_type=mime,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(content=content, media_type=mime)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brief_out(brief: Brief) -> dict[str, Any]:
    return {
        "id": brief.id,
        "workspace_id": brief.workspace_id,
        "title": brief.title,
        "template": brief.template,
        "content": brief.content,
        "created_at": brief.created_at.isoformat() if brief.created_at else "",
        "updated_at": brief.updated_at.isoformat() if brief.updated_at else "",
    }
