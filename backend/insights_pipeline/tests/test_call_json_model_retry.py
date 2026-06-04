"""Tests for call_json_model truncation/parse-failure retry with token escalation."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.insights_pipeline.stages import common


def _usage() -> SimpleNamespace:
    return SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=20,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )


def _response(content: str, finish_reason: str) -> SimpleNamespace:
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(finish_reason=finish_reason, message=message)
    return SimpleNamespace(choices=[choice], usage=_usage())


class _FakeCompletions:
    def __init__(self, responses: list[Any], calls: list[dict[str, Any]]):
        self._responses = responses
        self._calls = calls

    def create(self, **kwargs: Any) -> Any:
        idx = len(self._calls)
        self._calls.append(kwargs)
        return self._responses[min(idx, len(self._responses) - 1)]


class _FakeClient:
    def __init__(self, responses: list[Any], calls: list[dict[str, Any]]):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses, calls))


@pytest.fixture(autouse=True)
def _no_db_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid touching the cost-tracker persistence layer during unit tests.
    monkeypatch.setattr(common, "record_usage", lambda *a, **k: None)


def _patch_client(monkeypatch: pytest.MonkeyPatch, responses: list[Any]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(common, "_openai_client", lambda: _FakeClient(responses, calls))
    return calls


def test_retries_and_escalates_tokens_on_truncation(monkeypatch: pytest.MonkeyPatch):
    responses = [
        _response('{"insights": [', "length"),  # truncated, unparseable
        _response('{"insights": ["ok"]}', "stop"),  # clean retry
    ]
    calls = _patch_client(monkeypatch, responses)

    result = common.call_json_model(
        model="reasoning-test",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        max_completion_tokens=3000,
    )

    assert result == {"insights": ["ok"]}
    assert len(calls) == 2
    assert calls[0]["max_completion_tokens"] == 3000
    assert calls[1]["max_completion_tokens"] == 6000


def test_retries_on_unparseable_non_truncated_output(monkeypatch: pytest.MonkeyPatch):
    responses = [
        _response("here is some prose with no json at all", "stop"),
        _response('{"score": 7}', "stop"),
    ]
    calls = _patch_client(monkeypatch, responses)

    result = common.call_json_model(
        model="reasoning-test",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        max_completion_tokens=4000,
    )

    assert result == {"score": 7}
    assert len(calls) == 2
    assert calls[1]["max_completion_tokens"] == 8000


def test_no_retry_when_disabled_returns_fallback(monkeypatch: pytest.MonkeyPatch):
    responses = [_response('{"insights": [', "length")]
    calls = _patch_client(monkeypatch, responses)

    result = common.call_json_model(
        model="reasoning-test",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        max_completion_tokens=3000,
        max_retries=0,
    )

    assert "raw_text" in result
    assert result["_truncated"] is True
    assert len(calls) == 1


def test_clean_first_attempt_does_not_retry(monkeypatch: pytest.MonkeyPatch):
    responses = [_response('{"insights": ["a"]}', "stop")]
    calls = _patch_client(monkeypatch, responses)

    result = common.call_json_model(
        model="reasoning-test",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        max_completion_tokens=3000,
    )

    assert result == {"insights": ["a"]}
    assert len(calls) == 1


def test_token_escalation_clamped_to_hard_cap(monkeypatch: pytest.MonkeyPatch):
    # Starting near the hard cap, the doubled budget must clamp, not overshoot.
    responses = [
        _response("not json", "length"),
        _response('{"ok": true}', "stop"),
    ]
    calls = _patch_client(monkeypatch, responses)

    common.call_json_model(
        model="reasoning-test",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        max_completion_tokens=12000,
    )

    assert calls[1]["max_completion_tokens"] == common.MAX_COMPLETION_TOKENS_HARD_CAP
