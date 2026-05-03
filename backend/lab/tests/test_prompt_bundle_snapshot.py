"""Snapshot guard for lab prompt bundle composition."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.lab.workflow.common import PROMPTS_DIR, build_prompt_bundle


def _load_manifest() -> dict:
    return json.loads((PROMPTS_DIR / "manifest.yaml").read_text(encoding="utf-8"))


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_current_snapshot() -> dict:
    manifest = _load_manifest()
    bundle = build_prompt_bundle()
    files = {
        name: {
            "chars": len(text),
            "sha256": _hash_text(text),
        }
        for name, text in sorted(bundle.items())
    }
    return {
        "prompt_bundle_version": manifest.get("prompt_bundle_version"),
        "files": files,
    }


def test_prompt_bundle_snapshot_matches_fixture():
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "prompt_bundle_snapshot.json"
    expected = json.loads(fixture_path.read_text(encoding="utf-8"))
    actual = _build_current_snapshot()
    assert actual == expected, (
        "Prompt snapshot mismatch. If intentional, update "
        "backend/lab/prompts/PROMPT_CHANGES.md and refresh fixture."
    )

