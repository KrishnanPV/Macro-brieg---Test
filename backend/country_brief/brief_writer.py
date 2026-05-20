"""Country brief writer and parser utilities."""
from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.country_brief.prompts import build_refine_prompt
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)

_CONFIDENCE_RE = re.compile(
    r"\s*\**\s*[Cc]onfidence\s*:?\s*\**\s*:?\s*"
    r"(High|Medium|Low|Very\s+High|Moderate)[.\s]*\**\s*$",
    re.MULTILINE,
)


def _strip_confidence_tags(text: str) -> str:
    """Remove LLM-generated 'Confidence: High' etc. from the end of lines."""
    return _CONFIDENCE_RE.sub("", text)


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


_METRICS_RE = re.compile(r"\[METRICS_RIBBON\](.*?)\[/METRICS_RIBBON\]", re.DOTALL)
_EXEC_RE = re.compile(r"\[EXEC_SUMMARY\](.*?)\[/EXEC_SUMMARY\]", re.DOTALL)
_SECTION_RE = re.compile(r"\[SECTION:([^\]]+)\](.*?)\[/SECTION\]", re.DOTALL)
_OUTLOOK_RE = re.compile(r"\[OUTLOOK\](.*?)\[/OUTLOOK\]", re.DOTALL)
_CHART_RE = re.compile(r"\[CHART:\s*(\d+)\s*\]", re.IGNORECASE)
_TW_HW_RE = re.compile(r"\*\*Tailwinds\*\*", re.IGNORECASE)
_BULLET_RE = re.compile(r"^(\s*)([-*])\s+(.*)$")


def _normalize_bullet_nesting(text: str) -> str:
    """Re-nest bullet lists so non-bold bullets become children of the preceding bold-led bullet.

    The brief contract requires top-level bullets to start with a bold lead phrase
    (``**...**``) and supporting evidence to live in indented sub-bullets. LLM output
    is inconsistent: sometimes nested, often flat. This normalizes the structure
    deterministically so the frontend can render proper indentation.

    The transformation is only applied when the text contains both bold-led and
    non-bold bullets (otherwise there is nothing to disambiguate and we leave the
    original text untouched).
    """
    lines = text.splitlines()
    bullets: list[tuple[int, str]] = []  # (indent, content)
    preface: list[str] = []
    trailing: list[str] = []
    saw_bullet = False

    for raw in lines:
        m = _BULLET_RE.match(raw)
        if m:
            saw_bullet = True
            indent = len(m.group(1))
            content = m.group(3).strip()
            bullets.append((indent, content))
            continue

        stripped = raw.strip()
        if not stripped:
            if saw_bullet:
                # Blank lines inside the bullet block — drop to keep markdown tidy.
                continue
            preface.append(raw)
            continue

        if saw_bullet and bullets:
            # Continuation of the previous bullet (no bullet marker).
            indent, content = bullets[-1]
            bullets[-1] = (indent, f"{content} {stripped}".strip())
        elif saw_bullet:
            trailing.append(raw)
        else:
            preface.append(raw)

    if not bullets:
        return text

    bold_count = sum(1 for _, c in bullets if c.startswith("**"))
    if bold_count == 0 or bold_count == len(bullets):
        # Nothing to re-nest — leave the original text untouched.
        return text

    out: list[str] = []
    if preface:
        out.extend(p.rstrip() for p in preface)
        if out and out[-1] != "":
            out.append("")

    current_parent_idx: int | None = None
    for _, content in bullets:
        if content.startswith("**"):
            out.append(f"- {content}")
            current_parent_idx = len(out) - 1
        elif current_parent_idx is None:
            # Orphan supporting bullet before any bold parent — keep at top level.
            out.append(f"- {content}")
        else:
            out.append(f"  - {content}")

    if trailing:
        out.append("")
        out.extend(t.rstrip() for t in trailing)

    return "\n".join(out).strip()


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
    seen_chart_ids: set[str] = set()
    parts = _CHART_RE.split(body)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            text = part.strip()
            if text:
                blocks.append({"type": "narrative", "content": text})
        else:
            kpi_id = part.strip()
            if kpi_id not in seen_chart_ids:
                blocks.append({"type": "chart_ref", "kpi_id": kpi_id})
                seen_chart_ids.add(kpi_id)
    return blocks


_CHART_ORDER: dict[str, int] = {"3": 0, "2": 1, "11": 2}


def _reorder_section_charts(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort chart_ref blocks by the preferred GDP display order."""
    charts = [c for c in children if c.get("type") == "chart_ref"]
    if len(charts) <= 1:
        return children
    charts.sort(key=lambda c: _CHART_ORDER.get(str(c.get("kpi_id", "")), 99))
    result: list[dict[str, Any]] = []
    chart_iter = iter(charts)
    for c in children:
        if c.get("type") == "chart_ref":
            result.append(next(chart_iter))
        else:
            result.append(c)
    return result


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
        exec_content = _normalize_bullet_nesting(_strip_confidence_tags(m.group(1).strip()))
        blocks.append({"type": "executive_summary", "content": exec_content})

    global_seen_charts: set[str] = set()
    for m in _SECTION_RE.finditer(raw_text):
        title = m.group(1).strip()
        body = _strip_confidence_tags(m.group(2).strip())
        sub_blocks = _reorder_section_charts(_split_narrative_and_charts(body))
        deduped: list[dict[str, Any]] = []
        for sb in sub_blocks:
            if sb.get("type") == "chart_ref":
                kid = str(sb.get("kpi_id", "")).strip()
                if not kid or kid in global_seen_charts:
                    continue
                global_seen_charts.add(kid)
                deduped.append({**sb, "kpi_id": kid})
                continue
            deduped.append(sb)
        blocks.append({"type": "section", "title": title, "children": deduped})

    m = _OUTLOOK_RE.search(raw_text)
    if m:
        blocks.append({"type": "outlook", "content": _strip_confidence_tags(m.group(1).strip())})
    else:
        outlook_content = _extract_outlook_fallback(raw_text)
        if outlook_content:
            blocks.append({"type": "outlook", "content": _strip_confidence_tags(outlook_content)})

    return blocks


def stream_brief(messages: list[dict[str, str]]) -> Iterator[tuple[str, str]]:
    """Stream the brief as text deltas, then final full text."""
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


def stream_refine(
    section_content: str,
    data_context: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> Iterator[tuple[str, str]]:
    """Stream a section-refinement response."""
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

