"""FastAPI application factory for the Macro Brief platform."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.models.db import init_db
from backend.routers import data, workspace, costs
from backend.country_brief.router import router as country_brief_router
from backend.dashboard.router import router as dashboard_router
from backend.services.cost_tracker import init_cost_db

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
