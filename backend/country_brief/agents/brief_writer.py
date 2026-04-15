"""Agent 3 — Brief Writer.

Single streaming GPT call that combines KPI data, signal interpretation,
and (optionally) Perplexity research into a structured country brief.
Also owns the block parser that converts raw LLM markers into typed blocks,
and the section-refinement chat.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterator

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.country_brief.prompts import build_brief_prompt, build_refine_prompt
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _model_kwargs(model: str) -> dict[str, Any]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.3}


# ---------------------------------------------------------------------------
# Block parser — converts raw LLM text with markers into typed blocks
# ---------------------------------------------------------------------------

_METRICS_RE = re.compile(r"\[METRICS_RIBBON\](.*?)\[/METRICS_RIBBON\]", re.DOTALL)
_EXEC_RE = re.compile(r"\[EXEC_SUMMARY\](.*?)\[/EXEC_SUMMARY\]", re.DOTALL)
_SECTION_RE = re.compile(r"\[SECTION:([^\]]+)\](.*?)\[/SECTION\]", re.DOTALL)
_OUTLOOK_RE = re.compile(r"\[OUTLOOK\](.*?)\[/OUTLOOK\]", re.DOTALL)
_CHART_RE = re.compile(r"\[CHART:(\d+)\]")
_TW_HW_RE = re.compile(r"\*\*Tailwinds\*\*", re.IGNORECASE)


def _parse_metrics_ribbon(text: str) -> list[dict[str, str]]:
    metrics = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            metrics.append({"label": parts[0], "value": parts[1], "direction": parts[2]})
        elif len(parts) == 2:
            metrics.append({"label": parts[0], "value": parts[1], "direction": "flat"})
    return metrics


def _split_narrative_and_charts(body: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    parts = _CHART_RE.split(body)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            text = part.strip()
            if text:
                blocks.append({"type": "narrative", "content": text})
        else:
            blocks.append({"type": "chart_ref", "kpi_id": part.strip()})
    return blocks


def _extract_outlook_fallback(raw_text: str) -> str | None:
    m = _TW_HW_RE.search(raw_text)
    if not m:
        return None
    for sm in _SECTION_RE.finditer(raw_text):
        if sm.start() <= m.start() < sm.end():
            return None
    remainder = raw_text[m.start():]
    for marker in ("[/SECTION]", "[METRICS_RIBBON]", "[EXEC_SUMMARY]"):
        idx = remainder.find(marker)
        if idx > 0:
            remainder = remainder[:idx]
    return remainder.strip() or None


def parse_brief_blocks(raw_text: str) -> list[dict[str, Any]]:
    """Parse LLM output markers into structured blocks for the frontend."""
    blocks: list[dict[str, Any]] = []

    m = _METRICS_RE.search(raw_text)
    if m:
        metrics = _parse_metrics_ribbon(m.group(1))
        if metrics:
            blocks.append({"type": "metrics_ribbon", "metrics": metrics})

    m = _EXEC_RE.search(raw_text)
    if m:
        blocks.append({"type": "executive_summary", "content": m.group(1).strip()})

    for m in _SECTION_RE.finditer(raw_text):
        title = m.group(1).strip()
        body = m.group(2).strip()
        sub_blocks = _split_narrative_and_charts(body)
        blocks.append({"type": "section", "title": title, "children": sub_blocks})

    m = _OUTLOOK_RE.search(raw_text)
    if m:
        blocks.append({"type": "outlook", "content": m.group(1).strip()})
    else:
        outlook_content = _extract_outlook_fallback(raw_text)
        if outlook_content:
            blocks.append({"type": "outlook", "content": outlook_content})

    return blocks


# ---------------------------------------------------------------------------
# Streaming brief generation
# ---------------------------------------------------------------------------

def stream_brief(
    messages: list[dict[str, str]],
) -> Iterator[tuple[str, str]]:
    """Stream the brief, yielding (event_type, payload) tuples.

    Yields:
        ("text_delta", chunk)  — incremental text
        ("full_text", text)    — final accumulated text (last yield)
    """
    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        **_model_kwargs(model),
    )

    full_text = ""
    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            full_text += delta.content
            yield ("text_delta", delta.content)

    record_usage(model, usage, caller="brief_writer.stream_brief")
    yield ("full_text", full_text)


# ---------------------------------------------------------------------------
# Section refinement
# ---------------------------------------------------------------------------

def stream_refine(
    section_content: str,
    data_context: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> Iterator[tuple[str, str]]:
    """Stream a section-refinement response.

    Yields ("text", chunk) and finally ("done", "").
    """
    messages = build_refine_prompt(
        section_content=section_content,
        data_context=data_context,
        message=message,
        history=history,
    )

    client = _get_client()
    model = OPENAI_MODEL

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        max_completion_tokens=2048,
        stream=True,
        stream_options={"include_usage": True},
        **_model_kwargs(model),
    )

    usage = None
    for chunk in stream:
        if chunk.usage:
            usage = chunk.usage
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            yield ("text", delta.content)

    record_usage(model, usage, caller="brief_writer.stream_refine")
    yield ("done", "")
