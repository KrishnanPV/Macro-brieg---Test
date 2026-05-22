"""Snapshot the Oxford EAP Indicator dimension to a committed JSON catalog.

Usage:
    python -m backend.tools.oxford_catalog.snapshot

Writes ``backend/data/oxford_catalog.json`` with every Indicator dimension
member from the EAP dataset. Treat the resulting file as code: re-run +
commit whenever Oxford updates the dataset.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import knoema
import pandas as pd

from backend.config import DATASET, EAP_APP_ID, EAP_APP_SECRET, EAP_HOST

log = logging.getLogger(__name__)

CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "oxford_catalog.json"


def _configure_api() -> None:
    cfg = knoema.ApiConfig()
    cfg.host = EAP_HOST
    cfg.app_id = EAP_APP_ID
    cfg.app_secret = EAP_APP_SECRET


def _safe_str(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    return str(val).strip()


def fetch_indicators() -> list[dict[str, object]]:
    """Pull the full ``Indicator`` dimension from the EAP dataset.

    Returns a list of ``{"key", "id", "name", "parent_name", "has_data"}``
    rows. Only members with non-empty names are kept.
    """
    _configure_api()
    dim = knoema.dimension(DATASET, "indicator")
    members: pd.DataFrame = dim.members
    if members is None or members.empty:
        return []

    rows: list[dict[str, object]] = []
    for _, row in members.iterrows():
        name = _safe_str(row.get("name"))
        if not name:
            continue
        rows.append({
            "key": int(row["key"]) if pd.notna(row.get("key")) else None,
            "id": _safe_str(row.get("id")),
            "name": name,
            "parent_name": _safe_str(row.get("parent name") or row.get("parentname")),
            "has_data": bool(row.get("hasdata")) if pd.notna(row.get("hasdata")) else False,
        })
    rows.sort(key=lambda r: r["name"].lower())
    return rows


def write_catalog(indicators: list[dict[str, object]], path: Path = CATALOG_PATH) -> Path:
    payload = {
        "dataset": DATASET,
        "snapshot_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indicator_count": len(indicators),
        "indicators": indicators,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log.info("Fetching Indicator dimension from EAP dataset %s ...", DATASET)
    indicators = fetch_indicators()
    out = write_catalog(indicators)
    log.info("Wrote %d indicators to %s", len(indicators), out)


if __name__ == "__main__":
    main()
