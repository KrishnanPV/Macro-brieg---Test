"""Shared helpers for insights pipeline stages."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

from backend.config import (
    BRIEF_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    PERPLEXITY_API_KEY,
    PERPLEXITY_MODEL,
    PERPLEXITY_URL,
    REASONING_MODEL,
)
from backend.insights_pipeline.runtime import PROMPTS_DIR, load_prompt_text
from backend.models.kpi_registry import INSIGHT_LENSES, SPECS_BY_ID
from backend.services.cost_tracker import estimate_usage_cost, record_usage

log = logging.getLogger(__name__)

NEWS_MODEL = PERPLEXITY_MODEL


def ndjson(obj: dict[str, Any]) -> str:
    """Convert an event object into one NDJSON line."""
    return json.dumps(obj, default=str) + "\n"


def load_prompt(file_name: str) -> str:
    """Load a markdown prompt file from backend/insights_pipeline/prompts."""
    return load_prompt_text(file_name)


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


_FENCED_JSON_RE = re.compile(r"```(?:json|JSON)?\s*(.+?)```", re.DOTALL)


def _extract_embedded_json(text: str) -> str | None:
    """Best-effort recovery for prose responses that hide JSON inside them.

    Many LLMs (notably Perplexity Sonar without ``response_format``) will
    return text like::

        Here are the events I found:
        ```json
        [{"title": "..."}, ...]
        ```
        Let me know if you need more!

    or::

        I found 8 events:
        {"events": [{...}, {...}]}

    Strict ``json.loads`` rejects all of these. This helper tries three
    increasingly liberal extraction strategies and returns the first one that
    parses cleanly:

    1. Content inside the first ```json ... ``` fence anywhere in the text.
    2. The substring from the first ``{`` to the last ``}``.
    3. The substring from the first ``[`` to the last ``]`` (wrapped as
       ``{"events": [...]}`` for downstream consumers that expect a dict).

    Returns the recovered JSON *text* (not the parsed object) so the caller
    can keep its existing parse/validate flow, or ``None`` if no candidate
    parses.
    """
    if not text:
        return None

    fence_match = _FENCED_JSON_RE.search(text)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidate = text[first_brace : last_brace + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    first_bracket = text.find("[")
    last_bracket = text.rfind("]")
    if first_bracket >= 0 and last_bracket > first_bracket:
        candidate = text[first_bracket : last_bracket + 1]
        try:
            parsed_list = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed_list, list):
            return json.dumps({"events": parsed_list})

    return None


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


# Upper bound for retry token-budget escalation. A truncated/unparseable JSON
# response is retried with a doubled cap, clamped to this ceiling, so a single
# bad call can never silently produce an empty downstream stage.
MAX_COMPLETION_TOKENS_HARD_CAP = 16000


def _run_json_attempt(
    *,
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller: str,
    max_completion_tokens: int,
    extra_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Run a single chat completion and parse it into a payload dict.

    Returns ``(payload, call_meta, retry_recommended)``. ``retry_recommended``
    is ``True`` when the response was truncated (``finish_reason == "length"``)
    or could not be parsed as JSON, signalling the caller to retry with a
    larger token budget.
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=max_completion_tokens,
        **_temperature_kwargs(model),
        **extra_kwargs,
    )
    finish_reason = getattr(response.choices[0], "finish_reason", None)
    completion_details = getattr(response.usage, "completion_tokens_details", None)
    reasoning_tokens = int(getattr(completion_details, "reasoning_tokens", 0) or 0)
    total_completion_tokens = int(getattr(response.usage, "completion_tokens", 0) or 0)
    visible_tokens = max(total_completion_tokens - reasoning_tokens, 0)
    call_meta = {
        "model": model,
        "finish_reason": finish_reason,
        "reasoning_tokens": reasoning_tokens,
        "visible_tokens": visible_tokens,
        **estimate_usage_cost(model, response.usage),
    }
    record_usage(model, response.usage, caller=caller)
    text = _strip_fence(response.choices[0].message.content or "")

    truncated = finish_reason == "length"
    if truncated:
        log.warning(
            "%s hit max_completion_tokens cap (reasoning_tokens=%d, visible_tokens=%d, "
            "cap=%d); response truncated -- raise max_completion_tokens or lower reasoning_effort",
            caller,
            reasoning_tokens,
            visible_tokens,
            max_completion_tokens,
        )

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Truncation is the only case where embedded-JSON recovery is unlikely
        # to help (the trailing brace/bracket is gone), but we still try -- a
        # truncated array with a partial last element won't recover, but a
        # truncated string mid-prose with an earlier complete JSON block might.
        recovered_text = _extract_embedded_json(text)
        if recovered_text is not None:
            try:
                parsed = json.loads(recovered_text)
            except json.JSONDecodeError:
                recovered_text = None
        if recovered_text is None:
            if truncated:
                log.error(
                    "%s returned non-JSON output because the response was truncated "
                    "(finish_reason=length, reasoning_tokens=%d, visible_tokens=%d).",
                    caller,
                    reasoning_tokens,
                    visible_tokens,
                )
            else:
                log.warning(
                    "%s returned non-JSON output (finish_reason=%s); falling back to "
                    "wrapped text.",
                    caller,
                    finish_reason,
                )
            fallback: dict[str, Any] = {
                "raw_text": text,
                "_truncated": truncated,
                "_finish_reason": finish_reason,
            }
            # Unparseable output is always worth retrying with more head-room.
            return fallback, call_meta, True
        log.info(
            "%s recovered JSON from prose response via embedded-extraction "
            "(finish_reason=%s).",
            caller,
            finish_reason,
        )
    if isinstance(parsed, dict):
        if truncated:
            # Surface truncation flag on parsed dicts too so callers can detect
            # partial-but-valid JSON (rare, but possible with reasoning models).
            parsed.setdefault("_truncated", True)
            parsed.setdefault("_finish_reason", finish_reason)
        return parsed, call_meta, truncated
    wrapped: dict[str, Any] = {"items": parsed}
    if truncated:
        wrapped["_truncated"] = True
        wrapped["_finish_reason"] = finish_reason
    return wrapped, call_meta, truncated


def call_json_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    caller: str,
    use_perplexity: bool = False,
    max_completion_tokens: int = 3000,
    include_call_meta: bool = False,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "output",
    max_retries: int = 1,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    """Run one chat completion and parse JSON response.

    When ``response_schema`` is provided, the call is constrained via
    structured outputs (``response_format`` of type ``json_schema``). On
    OpenAI the request adds ``strict=True``; Perplexity Sonar accepts the
    same ``json_schema`` shape but does NOT accept ``strict`` (per
    https://docs.perplexity.ai/docs/agent-api/output-control).

    If the model still returns text that is not pure JSON (e.g. wrapping
    its JSON in a code fence or sandwiching it between prose/citation
    blocks, which Sonar does fairly often), the response is run through
    :func:`_extract_embedded_json` before the wrapped-text fallback. This
    salvages otherwise-billed-but-useless calls.

    Truncation (``finish_reason == "length"``) and outright parse failure are
    the most common causes of an empty downstream stage. To prevent that, the
    call is retried up to ``max_retries`` times, doubling ``max_completion_tokens``
    each attempt (clamped to :data:`MAX_COMPLETION_TOKENS_HARD_CAP`). The best
    available payload is always returned -- callers keep their existing
    parse/validate flow regardless of how many attempts ran.
    """
    client = _perplexity_client() if use_perplexity else _openai_client()
    extra_kwargs: dict[str, Any] = {}
    if response_schema is not None:
        json_schema_body: dict[str, Any] = {
            "name": response_schema_name,
            "schema": response_schema,
        }
        if not use_perplexity:
            json_schema_body["strict"] = True
        extra_kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": json_schema_body,
        }

    current_cap = max_completion_tokens
    attempt = 0
    payload, call_meta, retry_recommended = _run_json_attempt(
        client=client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        caller=caller,
        max_completion_tokens=current_cap,
        extra_kwargs=extra_kwargs,
    )
    while retry_recommended and attempt < max_retries:
        new_cap = min(current_cap * 2, MAX_COMPLETION_TOKENS_HARD_CAP)
        if new_cap <= current_cap:
            # Already at the hard cap; another attempt would not help.
            break
        attempt += 1
        log.warning(
            "%s retrying after truncated/unparseable output: max_completion_tokens "
            "%d -> %d (attempt %d/%d).",
            caller,
            current_cap,
            new_cap,
            attempt,
            max_retries,
        )
        current_cap = new_cap
        payload, call_meta, retry_recommended = _run_json_attempt(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            caller=caller,
            max_completion_tokens=current_cap,
            extra_kwargs=extra_kwargs,
        )

    if include_call_meta:
        return payload, call_meta
    return payload


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

