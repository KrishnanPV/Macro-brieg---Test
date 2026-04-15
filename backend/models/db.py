"""SQLAlchemy models and database setup for persistence."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Text, Float, Integer, DateTime, ForeignKey, event, inspect, text,
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, relationship

from backend.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    countries_json = Column(Text, default="[]")
    kpi_ids_json = Column(Text, default="[]")
    country_brief_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    cells = relationship("NotebookCell", back_populates="workspace", cascade="all, delete-orphan")
    graph_nodes = relationship("GraphNode", back_populates="workspace", cascade="all, delete-orphan")
    graph_edges = relationship("GraphEdge", back_populates="workspace", cascade="all, delete-orphan")
    context_docs = relationship("ContextDocument", back_populates="workspace", cascade="all, delete-orphan")
    flashcard_decks = relationship("FlashCardDeck", back_populates="workspace", cascade="all, delete-orphan")
    briefs = relationship("Brief", back_populates="workspace", cascade="all, delete-orphan")

    @property
    def countries(self) -> list[str]:
        return json.loads(self.countries_json or "[]")

    @countries.setter
    def countries(self, val: list[str]) -> None:
        self.countries_json = json.dumps(val)

    @property
    def kpi_ids(self) -> list[str]:
        return json.loads(self.kpi_ids_json or "[]")

    @kpi_ids.setter
    def kpi_ids(self, val: list[str]) -> None:
        self.kpi_ids_json = json.dumps(val)

    @property
    def country_brief(self) -> dict:
        return json.loads(self.country_brief_json or "{}")

    @country_brief.setter
    def country_brief(self, val: dict) -> None:
        self.country_brief_json = json.dumps(val)


# ---------------------------------------------------------------------------
# Notebook Cells
# ---------------------------------------------------------------------------

class NotebookCell(Base):
    __tablename__ = "notebook_cells"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    cell_type = Column(String, nullable=False)  # markdown | data | ai | insight | source
    content = Column(Text, default="")
    meta_json = Column(Text, default="{}")
    position = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    workspace = relationship("Workspace", back_populates="cells")

    @property
    def cell_meta(self) -> dict:
        return json.loads(self.meta_json or "{}")

    @cell_meta.setter
    def cell_meta(self, val: dict) -> None:
        self.meta_json = json.dumps(val, default=str)


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

class GraphNode(Base):
    __tablename__ = "graph_nodes"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    node_type = Column(String, nullable=False)
    label = Column(String, nullable=False)
    meta_json = Column(Text, default="{}")
    x = Column(Float, nullable=True)
    y = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    workspace = relationship("Workspace", back_populates="graph_nodes")

    @property
    def node_meta(self) -> dict:
        return json.loads(self.meta_json or "{}")

    @node_meta.setter
    def node_meta(self, val: dict) -> None:
        self.meta_json = json.dumps(val, default=str)


class GraphEdge(Base):
    __tablename__ = "graph_edges"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    source_id = Column(String, ForeignKey("graph_nodes.id"), nullable=False)
    target_id = Column(String, ForeignKey("graph_nodes.id"), nullable=False)
    edge_type = Column(String, nullable=False)
    label = Column(String, default="")
    meta_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)

    workspace = relationship("Workspace", back_populates="graph_edges")

    @property
    def edge_meta(self) -> dict:
        return json.loads(self.meta_json or "{}")

    @edge_meta.setter
    def edge_meta(self, val: dict) -> None:
        self.meta_json = json.dumps(val, default=str)


# ---------------------------------------------------------------------------
# Context Documents
# ---------------------------------------------------------------------------

class ContextDocument(Base):
    __tablename__ = "context_documents"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    doc_type = Column(String, default="text")
    source_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    workspace = relationship("Workspace", back_populates="context_docs")


# ---------------------------------------------------------------------------
# Flash Cards
# ---------------------------------------------------------------------------

class FlashCardDeck(Base):
    __tablename__ = "flashcard_decks"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    name = Column(String, nullable=False)
    tags_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=_utcnow)

    workspace = relationship("Workspace", back_populates="flashcard_decks")
    cards = relationship("FlashCard", back_populates="deck", cascade="all, delete-orphan")

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json or "[]")

    @tags.setter
    def tags(self, val: list[str]) -> None:
        self.tags_json = json.dumps(val)


class FlashCard(Base):
    __tablename__ = "flashcards"

    id = Column(String, primary_key=True, default=_uuid)
    deck_id = Column(String, ForeignKey("flashcard_decks.id"), nullable=False)
    front = Column(Text, nullable=False)
    back = Column(Text, nullable=False)
    source_cell_id = Column(String, nullable=True)
    tags_json = Column(Text, default="[]")
    ease_factor = Column(Float, default=2.5)
    interval_days = Column(Integer, default=1)
    repetitions = Column(Integer, default=0)
    next_review = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    deck = relationship("FlashCardDeck", back_populates="cards")

    @property
    def tags(self) -> list[str]:
        return json.loads(self.tags_json or "[]")

    @tags.setter
    def tags(self, val: list[str]) -> None:
        self.tags_json = json.dumps(val)


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------

class Brief(Base):
    __tablename__ = "briefs"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    title = Column(String, nullable=False)
    template = Column(String, default="country_overview")
    content_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    workspace = relationship("Workspace", back_populates="briefs")

    @property
    def content(self) -> dict:
        return json.loads(self.content_json or "{}")

    @content.setter
    def content(self, val: dict) -> None:
        self.content_json = json.dumps(val, default=str)


# ---------------------------------------------------------------------------
# Engine & session factory
# ---------------------------------------------------------------------------

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _migrate_sqlite_schema(sync_conn) -> None:
    """Add columns missing from older DB files (create_all does not ALTER)."""
    if sync_conn.dialect.name != "sqlite":
        return
    insp = inspect(sync_conn)
    if not insp.has_table("workspaces"):
        return
    cols = {c["name"] for c in insp.get_columns("workspaces")}
    if "country_brief_json" not in cols:
        sync_conn.execute(
            text("ALTER TABLE workspaces ADD COLUMN country_brief_json TEXT DEFAULT '{}'")
        )


async def init_db() -> None:
    """Create all tables (idempotent) and align legacy SQLite schemas."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite_schema)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
