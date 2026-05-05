"""Canonical prompt manifest/file loading for insights pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt_text(file_name: str) -> str:
    """Return a prompt file contents or empty string."""
    path = PROMPTS_DIR / file_name
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_prompt_manifest() -> tuple[dict[str, Any], str | None]:
    """Parse `manifest.yaml` as JSON first, then YAML fallback."""
    manifest_path = PROMPTS_DIR / "manifest.yaml"
    if not manifest_path.exists():
        return {}, "manifest.yaml not found"
    try:
        raw = manifest_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {}, f"manifest read error: {exc}"

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "manifest is not a JSON object"
    except json.JSONDecodeError:
        pass

    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return parsed, None
        return {}, "manifest is not a YAML mapping"
    except Exception as exc:
        return {}, f"manifest parse error: {exc}"

