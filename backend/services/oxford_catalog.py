"""In-process loader + helpers for the Oxford EAP indicator catalog snapshot.

The snapshot is produced by ``backend.tools.oxford_catalog.snapshot`` and
committed at ``backend/data/oxford_catalog.json``. This module is the single
import point for any runtime code that needs to validate or search the
indicator catalog.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "oxford_catalog.json"


@lru_cache(maxsize=1)
def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    """Read the catalog JSON. Returns an empty stub if the file is missing."""
    if not path.exists():
        log.warning("Oxford catalog not found at %s — run `python -m backend.tools.oxford_catalog.snapshot`.", path)
        return {"dataset": "", "snapshot_at": "", "indicator_count": 0, "indicators": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.error("Failed to read Oxford catalog at %s: %s", path, exc)
        return {"dataset": "", "snapshot_at": "", "indicator_count": 0, "indicators": []}


@lru_cache(maxsize=1)
def known_indicators() -> frozenset[str]:
    """All indicator ``name`` strings present in the snapshot (lowercased)."""
    catalog = load_catalog()
    return frozenset(
        str(row.get("name", "")).strip().lower()
        for row in catalog.get("indicators", [])
        if row.get("name")
    )


@lru_cache(maxsize=1)
def _name_index() -> dict[str, dict[str, Any]]:
    catalog = load_catalog()
    return {
        str(row["name"]).strip().lower(): row
        for row in catalog.get("indicators", [])
        if row.get("name")
    }


def validate_indicator(name: str) -> bool:
    """Return True iff *name* matches a known Indicator dimension member."""
    if not name:
        return False
    return name.strip().lower() in known_indicators()


def search(term: str, limit: int = 25) -> list[dict[str, Any]]:
    """Fuzzy substring search across indicator names. Case-insensitive."""
    if not term:
        return []
    needle = term.strip().lower()
    if not needle:
        return []
    catalog = load_catalog()
    matches: list[dict[str, Any]] = []
    for row in catalog.get("indicators", []):
        name = str(row.get("name", ""))
        if needle in name.lower():
            matches.append(row)
            if len(matches) >= limit:
                break
    return matches


def get_indicator(name: str) -> dict[str, Any] | None:
    """Return the catalog row for *name* (case-insensitive), or None."""
    if not name:
        return None
    return _name_index().get(name.strip().lower())


def reset_cache() -> None:
    """Invalidate cached catalog state (use after snapshot refresh in tests)."""
    load_catalog.cache_clear()
    known_indicators.cache_clear()
    _name_index.cache_clear()
