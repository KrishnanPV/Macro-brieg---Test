"""Tests for the run_pipeline safety net: never emit a blank/errored brief."""
from __future__ import annotations

import json

import pytest

from backend.country_brief import pipeline


def test_emergency_blocks_is_non_empty():
    blocks = pipeline._emergency_blocks()
    assert isinstance(blocks, list) and len(blocks) > 0
    types = {b["type"] for b in blocks}
    assert "executive_summary" in types


def test_run_pipeline_emits_error_blocks_done_on_failure(monkeypatch: pytest.MonkeyPatch):
    def _boom(req, *, deep_analysis=False):
        yield pipeline._ndjson({"type": "status", "content": "working"})
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline, "_run_pipeline_impl", _boom)

    events = [json.loads(line) for line in pipeline.run_pipeline(None, deep_analysis=False)]
    types = [e["type"] for e in events]

    assert "error" in types
    assert types[-1] == "done"
    blocks_event = next(e for e in events if e["type"] == "blocks")
    assert isinstance(blocks_event["content"], list)
    assert len(blocks_event["content"]) > 0


def test_run_pipeline_does_not_duplicate_blocks_when_already_emitted(
    monkeypatch: pytest.MonkeyPatch,
):
    def _partial(req, *, deep_analysis=False):
        yield pipeline._ndjson(
            {"type": "blocks", "content": [{"type": "executive_summary", "content": "x"}]}
        )
        raise RuntimeError("after blocks")

    monkeypatch.setattr(pipeline, "_run_pipeline_impl", _partial)

    events = [json.loads(line) for line in pipeline.run_pipeline(None)]
    block_events = [e for e in events if e["type"] == "blocks"]

    assert len(block_events) == 1
    assert any(e["type"] == "error" for e in events)
    assert events[-1]["type"] == "done"


def test_run_pipeline_passes_through_clean_stream(monkeypatch: pytest.MonkeyPatch):
    def _clean(req, *, deep_analysis=False):
        yield pipeline._ndjson({"type": "blocks", "content": [{"type": "outlook", "content": "ok"}]})
        yield pipeline._ndjson({"type": "done"})

    monkeypatch.setattr(pipeline, "_run_pipeline_impl", _clean)

    events = [json.loads(line) for line in pipeline.run_pipeline(None)]
    types = [e["type"] for e in events]

    assert types == ["blocks", "done"]
    assert not any(e["type"] == "error" for e in events)
