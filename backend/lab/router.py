"""HTTP endpoints for lab pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.lab.pipeline import run_pipeline
from backend.lab.schemas import LabGenerateRequest
from backend.lab.workflow.common import BRIEF_MODEL, REASONING_MODEL
from backend.services.cost_tracker import MODEL_PRICING

router = APIRouter(prefix="/api/lab", tags=["lab"])
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt_manifest() -> dict[str, Any]:
    manifest_path = PROMPTS_DIR / "manifest.yaml"
    if not manifest_path.exists():
        return {}
    try:
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _lookup_model_cost(model_name: str) -> tuple[float, float] | None:
    model_key = model_name.lower().strip()
    if model_key in MODEL_PRICING:
        return MODEL_PRICING[model_key]
    best = ""
    for key in MODEL_PRICING:
        if model_key.startswith(key) and len(key) > len(best):
            best = key
    if best:
        return MODEL_PRICING[best]
    return None


def _to_model_option(model_name: str, io_cost: Any | None = None) -> dict[str, Any]:
    inferred = _lookup_model_cost(model_name)
    if isinstance(io_cost, (list, tuple)) and len(io_cost) == 2:
        inferred = (float(io_cost[0]), float(io_cost[1]))
    return {
        "model": model_name,
        "io_cost": [float(inferred[0]), float(inferred[1])] if inferred else None,
    }


def _normalize_model_options(
    raw: Any,
    *,
    fallback_model: str,
) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                options.append(_to_model_option(item))
            elif isinstance(item, dict):
                name = str(item.get("model") or item.get("name") or "").strip()
                if not name:
                    continue
                options.append(_to_model_option(name, item.get("io_cost")))
    if not any(opt["model"] == fallback_model for opt in options):
        options.insert(0, _to_model_option(fallback_model))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for option in options:
        model = option["model"]
        if model in seen:
            continue
        seen.add(model)
        deduped.append(option)
    return deduped


@router.get("/health")
def health() -> dict[str, bool]:
    """Simple endpoint for frontend readiness checks."""
    return {"ok": True}


@router.post("/generate")
def generate_lab_insights(req: LabGenerateRequest):
    """Run the lab workflow and stream stage events as NDJSON."""
    return StreamingResponse(
        run_pipeline(req),
        media_type="application/x-ndjson",
    )


@router.get("/options")
def lab_options() -> dict[str, Any]:
    """Return frontend selector options from manifest and backend pricing config."""
    manifest = _load_prompt_manifest()
    manifest_models = manifest.get("models", {}) if isinstance(manifest.get("models"), dict) else {}
    model_options = manifest.get("model_options", {}) if isinstance(manifest.get("model_options"), dict) else {}

    default_reasoning = str(manifest_models.get("reasoning") or REASONING_MODEL)
    default_brief = str(manifest_models.get("brief_writer") or BRIEF_MODEL)
    reasoning_options = _normalize_model_options(
        model_options.get("reasoning"),
        fallback_model=default_reasoning,
    )
    brief_options = _normalize_model_options(
        model_options.get("brief_writer"),
        fallback_model=default_brief,
    )
    return {
        "generation_modes": ["deep", "light"],
        "models": {
            "reasoning": reasoning_options,
            "brief_writer": brief_options,
        },
        "defaults": {
            "generation_mode": "deep",
            "reasoning_model": default_reasoning,
            "brief_model": default_brief,
        },
    }

