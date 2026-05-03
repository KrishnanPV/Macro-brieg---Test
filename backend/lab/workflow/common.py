"""Shared helpers for lab workflow steps."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, PERPLEXITY_API_KEY, PERPLEXITY_URL
from backend.models.kpi_registry import INSIGHT_LENSES, SPECS_BY_ID
from backend.services.cost_tracker import estimate_usage_cost, record_usage

log = logging.getLogger(__name__)

REASONING_MODEL = "gpt-5.3-chat-latest"
BRIEF_MODEL = "gpt-4.1-mini"
NEWS_MODEL = "sonar"

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def ndjson(obj: dict[str, Any]) -> str:
    """Convert an event object into one NDJSON line."""
    return json.dumps(obj, default=str) + "\n"


def load_prompt(file_name: str) -> str:
    """Load a markdown prompt file from backend/lab/prompts."""
    path = PROMPTS_DIR / file_name
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_prompt_bundle() -> dict[str, str]:
    """Load all primary prompt files used by the workflow."""
    file_names = [
        "system_base.md",
        "style_guide.md",
        "per_kpi_context.md",
        "reasoning_playbook.md",
        "causal_language_rules.md",
    ]
    return {name: load_prompt(name) for name in file_names}


def get_kpi_context(kpi_id: str) -> str:
    """Build minimal per-KPI context from the existing KPI registry."""
    spec = SPECS_BY_ID.get(kpi_id)
    lens = INSIGHT_LENSES.get(kpi_id)
    lines: list[str] = []
    if spec:
        lines.append(f"KPI: {spec.name} (id={spec.id})")
        lines.append(f"Frequency: {spec.frequency}")
        lines.append(f"Source: {spec.source}")
    if lens:
        lines.append(f"Lens headline: {lens.headline}")
        if lens.context_hooks:
            lines.append("Context hooks:")
            lines.extend(f"- {item}" for item in lens.context_hooks[:6])
        if lens.notability_cues:
            lines.append("Notability cues:")
            lines.extend(f"- {item}" for item in lens.notability_cues[:6])
    return "\n".join(lines).strip()


def _temperature_kwargs(model: str) -> dict[str, float]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.2}


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines:
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _perplexity_client() -> OpenAI:
    if not PERPLEXITY_API_KEY:
        raise RuntimeError("PERPLEXITY_API_KEY is not configured.")
    return OpenAI(api_key=PERPLEXITY_API_KEY, base_url=PERPLEXITY_URL)


def call_json_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller: str,
    use_perplexity: bool = False,
    max_completion_tokens: int = 3000,
    include_call_meta: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Run one chat completion and parse JSON response."""
    client = _perplexity_client() if use_perplexity else _openai_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        **_temperature_kwargs(model),
    )
    call_meta = {
        "model": model,
        **estimate_usage_cost(model, response.usage),
    }
    record_usage(model, response.usage, caller=caller)
    text = _strip_fence(response.choices[0].message.content or "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        log.warning("%s returned non-JSON output; falling back to wrapped text.", caller)
        fallback = {"raw_text": text}
        if include_call_meta:
            return fallback, call_meta
        return fallback
    if isinstance(parsed, dict):
        if include_call_meta:
            return parsed, call_meta
        return parsed
    wrapped = {"items": parsed}
    if include_call_meta:
        return wrapped, call_meta
    return wrapped


def call_text_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller: str,
    max_completion_tokens: int = 3500,
    include_call_meta: bool = False,
) -> str | tuple[str, dict[str, Any]]:
    """Run one chat completion and return plain text response."""
    client = _openai_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        **_temperature_kwargs(model),
    )
    call_meta = {
        "model": model,
        **estimate_usage_cost(model, response.usage),
    }
    record_usage(model, response.usage, caller=caller)
    text = (response.choices[0].message.content or "").strip()
    if include_call_meta:
        return text, call_meta
    return text

