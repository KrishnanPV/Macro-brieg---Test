"""Synthesize a concise reasoning playbook from annotated IMF excerpts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from backend.insights_pipeline.stages.common import REASONING_MODEL, call_text_model

REQUIRED_FIELDS = (
    "signal",
    "interpretation",
    "driver",
    "mechanism",
    "offsetting_factors",
    "risk",
    "implication",
    "confidence",
)
REQUIRED_SECTIONS = (
    "# Reasoning Playbook",
    "## Core Reasoning Loop",
    "## Required Reasoning Rules",
    "## Common Reasoning Patterns",
    "## Failure Modes to Avoid",
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ANNOTATIONS_PATH = BASE_DIR / "annotations" / "imf_reasoning_units_v1.jsonl"
DEFAULT_PROMPT_PATH = BASE_DIR / "prompts" / "pattern_synthesis_prompt_v1.md"
DEFAULT_OUTPUT_PATH = BASE_DIR / "outputs" / "reasoning_playbook_v1.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthesize a reasoning playbook from IMF annotation JSONL."
    )
    parser.add_argument("--annotations-path", type=Path, default=DEFAULT_ANNOTATIONS_PATH)
    parser.add_argument("--prompt-path", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--max-units", type=int, default=120)
    parser.add_argument("--overwrite-output", action="store_true")
    return parser.parse_args()


def _load_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Synthesis prompt not found: {prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Synthesis prompt is empty: {prompt_path}")
    return prompt


def _validate_row(row: dict[str, Any], line_no: int) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError(f"Line {line_no}: missing fields: {', '.join(missing)}")
    confidence = str(row["confidence"]).strip().lower()
    if confidence not in {"low", "medium", "high"}:
        raise ValueError(f"Line {line_no}: invalid confidence '{row['confidence']}'")


def _load_annotation_rows(path: Path, *, max_units: int) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Annotations file not found: {path}")
    rows: list[dict[str, Any]] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_no}: invalid JSON ({exc})") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Line {line_no}: expected object row.")
        _validate_row(parsed, line_no)
        rows.append(parsed)
        if len(rows) >= max_units:
            break
    if not rows:
        raise RuntimeError(f"No valid annotation rows found in {path}")
    return rows


def _trim_row(row: dict[str, Any]) -> dict[str, Any]:
    excerpt_text = str(row.get("excerpt_text", "")).strip()
    if len(excerpt_text) > 600:
        excerpt_text = excerpt_text[:600].rstrip() + "..."
    return {
        "excerpt_id": row.get("excerpt_id"),
        "section": row.get("section"),
        "source_pdf": row.get("source_pdf"),
        "signal": row.get("signal"),
        "interpretation": row.get("interpretation"),
        "driver": row.get("driver"),
        "mechanism": row.get("mechanism"),
        "offsetting_factors": row.get("offsetting_factors"),
        "risk": row.get("risk"),
        "implication": row.get("implication"),
        "confidence": row.get("confidence"),
        "excerpt_text": excerpt_text,
    }


def _build_user_prompt(rows: list[dict[str, Any]]) -> str:
    units = [_trim_row(row) for row in rows]
    payload = json.dumps(units, ensure_ascii=True, indent=2)
    return (
        "Use the following IMF reasoning units to derive recurring patterns and concise rules.\n"
        "Keep the output short, enforceable, and generalizable.\n\n"
        f"Reasoning units JSON:\n{payload}"
    )


def _validate_markdown_output(markdown: str) -> None:
    missing = [section for section in REQUIRED_SECTIONS if section not in markdown]
    if missing:
        raise ValueError(
            "Generated markdown is missing required sections: " + ", ".join(missing)
        )


def _write_output(path: Path, content: str, *, overwrite: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise RuntimeError(
            f"{path} already exists. Use --overwrite-output to replace it."
        )
    path.write_text(content.strip() + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()
    system_prompt = _load_prompt(args.prompt_path)
    rows = _load_annotation_rows(args.annotations_path, max_units=args.max_units)
    user_prompt = _build_user_prompt(rows)

    markdown, call_meta = call_text_model(
        model=REASONING_MODEL,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller="tools.reasoning_distillation.synthesis",
        include_call_meta=True,
    )
    _validate_markdown_output(markdown)
    _write_output(args.output_path, markdown, overwrite=args.overwrite_output)
    print(f"Synthesized playbook using {len(rows)} units.")
    print(f"Output written to: {args.output_path}")
    print(
        "Total LLM cost (synthesis): "
        f"${float(call_meta.get('total_cost', 0.0)):.6f} "
        f"(input_tokens={int(call_meta.get('input_tokens', 0) or 0)}, "
        f"output_tokens={int(call_meta.get('output_tokens', 0) or 0)})"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"synthesize_patterns failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
