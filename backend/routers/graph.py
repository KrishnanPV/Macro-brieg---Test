"""Knowledge graph CRUD endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db import get_session, GraphNode, GraphEdge
from backend.models.schemas import (
    GraphNodeCreate, GraphNodeUpdate, GraphNodeOut,
    GraphEdgeCreate, GraphEdgeOut,
)
from backend.services.derived_facts import compute_derived_facts

router = APIRouter(prefix="/api/workspaces/{ws_id}/graph", tags=["graph"])


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@router.get("/nodes", response_model=list[GraphNodeOut])
async def list_nodes(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(GraphNode).where(GraphNode.workspace_id == ws_id)
    )
    return [_node_out(n) for n in result.scalars().all()]


@router.post("/nodes", response_model=GraphNodeOut, status_code=201)
async def create_node(ws_id: str, body: GraphNodeCreate, db: AsyncSession = Depends(get_session)):
    node = GraphNode(
        workspace_id=ws_id,
        node_type=body.node_type,
        label=body.label,
        x=body.x,
        y=body.y,
    )
    node.node_meta = body.metadata
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return _node_out(node)


@router.patch("/nodes/{node_id}", response_model=GraphNodeOut)
async def update_node(ws_id: str, node_id: str, body: GraphNodeUpdate, db: AsyncSession = Depends(get_session)):
    node = await db.get(GraphNode, node_id)
    if not node or node.workspace_id != ws_id:
        raise HTTPException(404, "Node not found")
    if body.label is not None:
        node.label = body.label
    if body.metadata is not None:
        node.node_meta = body.metadata
    if body.x is not None:
        node.x = body.x
    if body.y is not None:
        node.y = body.y
    await db.commit()
    await db.refresh(node)
    return _node_out(node)


@router.delete("/nodes/{node_id}", status_code=204)
async def delete_node(ws_id: str, node_id: str, db: AsyncSession = Depends(get_session)):
    node = await db.get(GraphNode, node_id)
    if not node or node.workspace_id != ws_id:
        raise HTTPException(404, "Node not found")
    edges = await db.execute(
        select(GraphEdge).where(
            (GraphEdge.source_id == node_id) | (GraphEdge.target_id == node_id)
        )
    )
    for edge in edges.scalars().all():
        await db.delete(edge)
    await db.delete(node)
    await db.commit()


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

@router.get("/edges", response_model=list[GraphEdgeOut])
async def list_edges(ws_id: str, db: AsyncSession = Depends(get_session)):
    result = await db.execute(
        select(GraphEdge).where(GraphEdge.workspace_id == ws_id)
    )
    return [_edge_out(e) for e in result.scalars().all()]


@router.post("/edges", response_model=GraphEdgeOut, status_code=201)
async def create_edge(ws_id: str, body: GraphEdgeCreate, db: AsyncSession = Depends(get_session)):
    source = await db.get(GraphNode, body.source_id)
    target = await db.get(GraphNode, body.target_id)
    if not source or source.workspace_id != ws_id:
        raise HTTPException(404, "Source node not found")
    if not target or target.workspace_id != ws_id:
        raise HTTPException(404, "Target node not found")

    edge = GraphEdge(
        workspace_id=ws_id,
        source_id=body.source_id,
        target_id=body.target_id,
        edge_type=body.edge_type,
        label=body.label,
    )
    edge.edge_meta = body.metadata
    db.add(edge)
    await db.commit()
    await db.refresh(edge)
    return _edge_out(edge)


@router.delete("/edges/{edge_id}", status_code=204)
async def delete_edge(ws_id: str, edge_id: str, db: AsyncSession = Depends(get_session)):
    edge = await db.get(GraphEdge, edge_id)
    if not edge or edge.workspace_id != ws_id:
        raise HTTPException(404, "Edge not found")
    await db.delete(edge)
    await db.commit()


# ---------------------------------------------------------------------------
# Auto-build from KPI data
# ---------------------------------------------------------------------------

class AutoBuildRequest(BaseModel):
    results: list[dict[str, Any]]
    countries: list[str] = []


@router.post("/auto-build")
async def auto_build_graph(
    ws_id: str, body: AutoBuildRequest, db: AsyncSession = Depends(get_session),
):
    """Clear existing auto-generated nodes and rebuild from KPI results.

    Creates a KPI-movement node for each country×KPI series that has data,
    plus edges between KPIs for the same country (correlated_with).
    """
    existing = await db.execute(
        select(GraphNode).where(GraphNode.workspace_id == ws_id)
    )
    existing_nodes = existing.scalars().all()
    auto_ids = [n.id for n in existing_nodes if (n.node_meta or {}).get("auto")]
    if auto_ids:
        await db.execute(
            delete(GraphEdge).where(
                GraphEdge.workspace_id == ws_id,
                (GraphEdge.source_id.in_(auto_ids)) | (GraphEdge.target_id.in_(auto_ids)),
            )
        )
        await db.execute(
            delete(GraphNode).where(
                GraphNode.workspace_id == ws_id,
                GraphNode.id.in_(auto_ids),
            )
        )
        await db.flush()

    derived = compute_derived_facts(body.results)

    created_nodes: list[dict] = []
    country_kpi_node: dict[tuple[str, str], str] = {}

    col = 0
    for kpi_result in body.results:
        kpi_id = str(kpi_result.get("kpi_id", ""))
        kpi_name = kpi_result.get("kpi_name", kpi_id)
        series_list = kpi_result.get("series", [])
        if not series_list:
            continue

        kpi_facts = next(
            (f for f in derived if str(f.get("kpi_id")) == kpi_id), {}
        )

        row = 0
        for s in series_list:
            country = s.get("country", "")
            points = s.get("points", [])
            if not points:
                continue

            sf = next(
                (f for f in kpi_facts.get("series_facts", [])
                 if f.get("country") == country and f.get("indicator") == s.get("indicator")),
                {},
            )

            latest = sf.get("latest", {})
            earliest = sf.get("earliest", {})
            cagr = sf.get("cagr", {})
            change = sf.get("change_pct")
            inflections = sf.get("inflection_points", [])

            direction = ""
            if change is not None:
                direction = "rising" if change > 0 else "falling" if change < 0 else "flat"

            label = f"{country} — {kpi_name}"
            if direction:
                label += f" ({direction})"

            node = GraphNode(
                workspace_id=ws_id,
                node_type="kpi_movement",
                label=label,
                x=200.0 + col * 280,
                y=80.0 + row * 160,
            )
            node.node_meta = {
                "auto": True,
                "kpi_id": kpi_id,
                "country": country,
                "indicator": s.get("indicator", ""),
                "latest": latest,
                "earliest": earliest,
                "cagr": cagr if cagr else None,
                "change_pct": change,
                "inflections": inflections[:3],
            }
            db.add(node)
            await db.flush()
            country_kpi_node[(country, kpi_id)] = node.id
            created_nodes.append(_node_out(node))
            row += 1

        col += 1

    created_edges: list[dict] = []
    countries_seen = set(k[0] for k in country_kpi_node)
    kpi_ids_seen = sorted(set(k[1] for k in country_kpi_node))

    for country in countries_seen:
        for i, kid_a in enumerate(kpi_ids_seen):
            for kid_b in kpi_ids_seen[i + 1:]:
                nid_a = country_kpi_node.get((country, kid_a))
                nid_b = country_kpi_node.get((country, kid_b))
                if not nid_a or not nid_b:
                    continue
                edge = GraphEdge(
                    workspace_id=ws_id,
                    source_id=nid_a,
                    target_id=nid_b,
                    edge_type="correlated_with",
                    label="same country",
                )
                edge.edge_meta = {"auto": True}
                db.add(edge)
                await db.flush()
                created_edges.append(_edge_out(edge))

    await db.commit()

    return {"nodes": created_nodes, "edges": created_edges}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node_out(node: GraphNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "workspace_id": node.workspace_id,
        "node_type": node.node_type,
        "label": node.label,
        "metadata": node.node_meta,
        "x": node.x,
        "y": node.y,
        "created_at": node.created_at.isoformat() if node.created_at else "",
    }


def _edge_out(edge: GraphEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "workspace_id": edge.workspace_id,
        "source_id": edge.source_id,
        "target_id": edge.target_id,
        "edge_type": edge.edge_type,
        "label": edge.label,
        "metadata": edge.edge_meta,
        "created_at": edge.created_at.isoformat() if edge.created_at else "",
    }
