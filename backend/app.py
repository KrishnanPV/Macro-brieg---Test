"""FastAPI application factory for the Macro Brief platform."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.models.db import init_db
from backend.models.kpi_registry import SPECS
from backend.routers import data, workspace, costs
from backend.country_brief.router import router as country_brief_router
from backend.dashboard.router import router as dashboard_router
from backend.services.cost_tracker import init_cost_db
from backend.services.oxford_catalog import load_catalog, validate_indicator

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s — %(message)s",
)

log = logging.getLogger(__name__)


def _validate_kpi_indicators() -> None:
    """Check every Oxford KpiSpec.indicator against the catalog snapshot.

    In strict mode (``MACROBRIEF_STRICT_CATALOG=1``) unknown indicators
    raise on boot; otherwise they log a warning so prod doesn't refuse to
    start on a stale snapshot.
    """
    catalog = load_catalog()
    if not catalog.get("indicators"):
        log.warning("Oxford catalog snapshot is empty — skipping indicator validation.")
        return

    strict = os.environ.get("MACROBRIEF_STRICT_CATALOG") == "1"
    unknown: list[tuple[str, str]] = []
    for spec in SPECS:
        if spec.source != "oxford":
            continue
        for indicator in spec.indicators:
            if not validate_indicator(indicator):
                unknown.append((spec.id, indicator))

    if not unknown:
        log.info("Oxford indicator validation OK (%d indicators).", catalog.get("indicator_count", 0))
        return

    msg_lines = [f"  KPI {kid}: {ind!r}" for kid, ind in unknown]
    msg = "Unknown Oxford indicator(s) in kpi_registry:\n" + "\n".join(msg_lines)
    if strict:
        raise RuntimeError(msg)
    log.warning("%s\nRefresh snapshot via `python -m backend.tools.oxford_catalog.snapshot`.", msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_kpi_indicators()
    await init_db()
    init_cost_db()
    yield


app = FastAPI(title="Macro Brief Research Platform", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)
app.include_router(workspace.router)
app.include_router(country_brief_router)
app.include_router(dashboard_router)
app.include_router(costs.router)


@app.get("/api/debug-mode")
def debug_mode():
    return {"debug": os.environ.get("MACROBRIEF_DEBUG") == "1"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=8000, reload=True)
