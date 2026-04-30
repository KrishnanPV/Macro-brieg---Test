"""Workspace storage in SQLite (via SQLAlchemy). Legacy tables from older apps
may still exist in the DB file; ``purge_legacy_workspace_rows`` clears them on
workspace delete so nothing breaks.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Text, DateTime, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# FK-safe order for legacy tables that referenced workspaces.id
_LEGACY_ROW_PURGE_SQL = (
    "DELETE FROM flashcards WHERE deck_id IN "
    "(SELECT id FROM flashcard_decks WHERE workspace_id = :wid)",
    "DELETE FROM flashcard_decks WHERE workspace_id = :wid",
    "DELETE FROM graph_edges WHERE workspace_id = :wid",
    "DELETE FROM graph_nodes WHERE workspace_id = :wid",
    "DELETE FROM context_documents WHERE workspace_id = :wid",
    "DELETE FROM notebook_cells WHERE workspace_id = :wid",
    "DELETE FROM briefs WHERE workspace_id = :wid",
)


async def purge_legacy_workspace_rows(session: AsyncSession, workspace_id: str) -> None:
    """Remove rows in deprecated tables for this workspace (ignore missing tables)."""
    for stmt in _LEGACY_ROW_PURGE_SQL:
        try:
            await session.execute(text(stmt), {"wid": workspace_id})
        except OperationalError:
            pass


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
    """Create workspace table (idempotent) and align legacy SQLite schemas."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_migrate_sqlite_schema)


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
