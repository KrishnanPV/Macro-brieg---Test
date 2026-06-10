"""Country brief writer and parser utilities."""
from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from openai import OpenAI

from backend.config import BRIEF_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL
from backend.country_brief.prompts import build_refine_prompt
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)

_CONFIDENCE_LINE_RE = re.compile(
    r"^[ \t]*(?:[-*]\s+)?\**\s*[Cc]onfidence\s*[:=\u2013\u2014].*\n?",
    re.MULTILINE,
)
# Inline confidence marker emitted by the model (e.g. ``... evidence. [conf:H]``).
# The model still assesses confidence in the background, but it is stripped here
# so it never surfaces in the rendered brief.
_CONFIDENCE_TOKEN_RE = re.compile(
    r"[ \t]*\[conf:\s*(?:high|medium|med|low|h|m|l)\s*\]",
    re.IGNORECASE,
)


def _strip_confidence_tags(text: str) -> str:
    """Remove confidence flags so they never surface in the brief output.

    Handles two forms the model may emit while assessing confidence internally:
    a whole ``Confidence: ...`` line (with or without a leading bullet or bold
    wrappers, and regardless of any trailing parenthetical justification, e.g.
    ``- **Confidence: Medium-High** (clear shift).``), and the inline
    ``[conf:H|M|L]`` token appended to a bullet. The trailing newline of a
    confidence *line* is consumed so emptied bullet rows leave no blank line.
    """
    text = _CONFIDENCE_LINE_RE.sub("", text)
    return _CONFIDENCE_TOKEN_RE.sub("", text)


_TRAILING_WS_RE = re.compile(r"[ \t]+\n")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
# Removing an inline ``[CHART:N]`` marker that sat before punctuation leaves an
# orphaned space (e.g. ``42,209bn [CHART:11].`` -> ``42,209bn .``); collapse it.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"[ \t]+([.,;:)])")
# The model often wraps chart markers in a parenthetical reference list in prose
# (e.g. ``manufacturing ([CHART:12], [CHART:11]).``). Once the markers are
# stripped, the parenthetical collapses to punctuation-only scaffolding -- ``()``,
# ``(,)``, ``(,,)`` -- which must be removed too (including any space before it).
_ORPHANED_PARENS_RE = re.compile(r"[ \t]*\([ \t,;]*\)")

# Catch-all for *any* chart token, including the literal placeholder
# ``[CHART:kpi_id]`` (no numeric id) that the model copies verbatim from the
# OUTPUT_CONTRACT's advertised format. ``_CHART_RE`` only matches markers that
# carry a real numeric id (those are the ones we can place as a chart); this
# broad pattern is used purely to scrub residue so no ``[CHART:...]`` text ever
# survives into the rendered brief, regardless of what the model emitted.
_CHART_ANY_RE = re.compile(r"\[CHART:[^\]]*\]", re.IGNORECASE)
# A bullet line whose only content was a chart token (e.g. ``- [CHART:kpi_id]``)
# collapses to an empty bullet once the token is removed; drop the whole row.
_EMPTY_BULLET_RE = re.compile(r"^[ \t]*[-*][ \t]*$\n?", re.MULTILINE)


def _strip_chart_markers(text: str) -> str:
    """Remove every ``[CHART:...]`` token and clean up the residue it leaves.

    ``[CHART:kpi_id]`` is a chart-placement directive that only has a
    rendering target inside a ``[SECTION:...]`` body (where
    ``_split_narrative_and_charts`` converts numeric markers into ``chart_ref``
    blocks). Anywhere else -- ``[EXEC_SUMMARY]``, ``[OUTLOOK]``, or a section's
    narrative text after the numeric markers have been split out -- a chart
    token has nowhere to place a chart and would otherwise leak as literal
    text in the rendered brief.

    This is a belt-and-suspenders parser-side guarantee so the user never sees
    a raw marker even if the model misbehaves. It scrubs the broad
    ``[CHART:...]`` form, which covers all three failure modes observed in the
    wild: the bare numeric ``[CHART:2]``, the prefixed ``[CHART:kpi_2]``, and
    the verbatim placeholder ``[CHART:kpi_id]`` (no numeric id at all). A
    bullet that held nothing but the token is dropped so no empty bullet rows
    remain.
    """
    if not text:
        return text
    cleaned = _CHART_ANY_RE.sub("", text)
    cleaned = _ORPHANED_PARENS_RE.sub("", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", cleaned)
    cleaned = _EMPTY_BULLET_RE.sub("", cleaned)
    cleaned = _TRAILING_WS_RE.sub("\n", cleaned)
    cleaned = _MULTI_BLANK_RE.sub("\n\n", cleaned)
    return cleaned.strip()


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


# Truncated briefs frequently arrive with an opening tag whose matching close
# tag never made it into the stream. To avoid silently dropping that partial
# (often final) block, every block regex accepts EITHER its own close tag OR a
# zero-width lookahead at the next known opening marker / end-of-string. A
# well-formed brief still matches at its real close tag (it appears before any
# subsequent opening marker), so this only changes behavior for unclosed blocks.
_NEXT_OPEN = r"(?=\[METRICS_RIBBON\]|\[EXEC_SUMMARY\]|\[SECTION:|\[OUTLOOK\]|\Z)"
_METRICS_RE = re.compile(r"\[METRICS_RIBBON\](.*?)(?:\[/METRICS_RIBBON\]|" + _NEXT_OPEN + ")", re.DOTALL)
_EXEC_RE = re.compile(r"\[EXEC_SUMMARY\](.*?)(?:\[/EXEC_SUMMARY\]|" + _NEXT_OPEN + ")", re.DOTALL)
_SECTION_RE = re.compile(r"\[SECTION:([^\]]+)\](.*?)(?:\[/SECTION\]|" + _NEXT_OPEN + ")", re.DOTALL)
_OUTLOOK_RE = re.compile(r"\[OUTLOOK\](.*?)(?:\[/OUTLOOK\]|" + _NEXT_OPEN + ")", re.DOTALL)
# Accept an optional ``kpi_`` prefix on the id. The OUTPUT_CONTRACT advertises
# the marker format as the literal ``[CHART:kpi_id]``, and the model frequently
# takes that placeholder at face value and emits ``[CHART:kpi_12]`` instead of
# the bare ``[CHART:12]``. We capture only the numeric id so chart_ref ids stay
# consistent with the bare numeric KPI ids used everywhere else in the pipeline.
_CHART_RE = re.compile(r"\[CHART:\s*(?:kpi[_\s-]?)?(\d+)\s*\]", re.IGNORECASE)
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
    """Extract chart refs, then emit the section prose as one normalized block.

    Charts are rendered in a separate region from the prose (a dedicated chart
    column in the brief view), so a ``[CHART:N]`` marker's position *inside* the
    narrative is irrelevant to layout. Splitting the prose at each marker, on the
    other hand, fractures the bullet list: the model routinely places a chart
    marker inline within the first bold lead bullet, which would strand that
    lead in one chunk and its supporting sub-bullets in the next, defeating the
    bold-lead/indented-evidence nesting.

    So we pull every chart ref out first (in document order, de-duplicated),
    then strip all chart markers from the prose and normalize the *entire*
    contiguous bullet list once. This makes the lead-line + indented-sub-points
    structure deterministic regardless of where the model dropped its markers.
    """
    blocks: list[dict[str, Any]] = []
    seen_chart_ids: set[str] = set()
    for m in _CHART_RE.finditer(body):
        kpi_id = m.group(1).strip()
        if kpi_id and kpi_id not in seen_chart_ids:
            blocks.append({"type": "chart_ref", "kpi_id": kpi_id})
            seen_chart_ids.add(kpi_id)
    narrative = _normalize_bullet_nesting(_strip_chart_markers(body))
    if narrative:
        blocks.append({"type": "narrative", "content": narrative})
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
        exec_content = _normalize_bullet_nesting(
            _strip_chart_markers(_strip_confidence_tags(m.group(1).strip()))
        )
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
        blocks.append({
            "type": "outlook",
            "content": _strip_chart_markers(_strip_confidence_tags(m.group(1).strip())),
        })
    else:
        outlook_content = _extract_outlook_fallback(raw_text)
        if outlook_content:
            blocks.append({
                "type": "outlook",
                "content": _strip_chart_markers(_strip_confidence_tags(outlook_content)),
            })

    return blocks


_BRIEF_MAX_TOKENS = 8000
_BRIEF_RETRY_MAX_TOKENS = 12000


def _is_incomplete_brief(text: str) -> bool:
    """True when the markdown looks truncated mid-block.

    An opening block tag without its matching close tag is the canonical
    truncation symptom (the stream was cut before the model could emit the
    closing marker). We also treat empty output as incomplete.
    """
    if not text or not text.strip():
        return True
    if text.count("[EXEC_SUMMARY]") > text.count("[/EXEC_SUMMARY]"):
        return True
    if text.count("[OUTLOOK]") > text.count("[/OUTLOOK]"):
        return True
    if text.count("[SECTION:") > text.count("[/SECTION]"):
        return True
    return False


def stream_brief(messages: list[dict[str, str]]) -> Iterator[tuple[str, str]]:
    """Stream the brief as text deltas, then final full text.

    ``max_completion_tokens`` is set explicitly to give the gpt-5.4-mini
    reasoning model enough head-room for both its hidden reasoning trace and
    the visible markdown brief. The QuantumBlack OpenAI gateway lumps
    reasoning tokens and visible tokens into one usage counter without
    exposing the split, so a too-small cap silently starves the visible
    output - the model emits ``[SECTION:...][/SECTION]`` skeletons with no
    narrative body. 8000 tokens comfortably covers an 8-section deep-mode
    brief at ~2,500-3,000 visible tokens plus the reasoning the model needs
    to satisfy the EXHIBIT MAP + CITATION POLICY constraints.

    If the first attempt is still truncated (``finish_reason == "length"``) or
    arrives with an unclosed block, the brief is regenerated once with a higher
    token budget so the user is never served a half-written brief. The retry is
    not re-streamed as ``text_delta`` (that would duplicate the preview); a
    ``status`` event is emitted instead and the final ``full_text`` carries the
    better result.
    """
    client = _get_client()
    model = BRIEF_MODEL

    def _run(cap: int, emit_deltas: bool) -> Iterator[tuple[str, str]]:
        full_parts: list[str] = []
        usage = None
        finish_reason: str | None = None
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=cap,
            stream=True,
            stream_options={"include_usage": True},
            **_model_kwargs(model),
        )
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            delta = choice.delta
            if delta.content:
                full_parts.append(delta.content)
                if emit_deltas:
                    yield ("text_delta", delta.content)
        record_usage(model, usage, caller="brief_writer.stream_brief")
        return "".join(full_parts), finish_reason

    full_text, finish_reason = yield from _run(_BRIEF_MAX_TOKENS, True)

    if finish_reason == "length" or _is_incomplete_brief(full_text):
        log.warning(
            "brief_writer.stream_brief produced truncated/incomplete output "
            "(finish_reason=%s, chars=%d); regenerating with a higher token budget.",
            finish_reason,
            len(full_text or ""),
        )
        yield ("truncated", finish_reason or "incomplete")
        yield ("status", "Brief came back truncated; regenerating with more room...")
        retry_text, _retry_finish = yield from _run(_BRIEF_RETRY_MAX_TOKENS, False)
        # Keep the retry only if it is a genuine improvement: complete output,
        # or simply more content than the truncated first attempt.
        if retry_text and (not _is_incomplete_brief(retry_text) or len(retry_text) > len(full_text or "")):
            full_text = retry_text

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
    model = BRIEF_MODEL

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

