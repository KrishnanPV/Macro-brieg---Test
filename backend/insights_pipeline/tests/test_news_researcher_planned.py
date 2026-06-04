"""Tests for news_researcher.run_planned_queries."""
from __future__ import annotations

import threading
from typing import Any

import pytest

from backend.insights_pipeline.stages import news_researcher


def _planned(
    query_id: str,
    query: str,
    *,
    hypothesis_id: str = "G1_H1",
    group_ids: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "query": query,
        "source": "hypothesis",
        "hypothesis_id": hypothesis_id,
        "group_ids": list(group_ids or ["g1"]),
        "priority": "high",
        "search_priority_rank": 0,
    }


def _good_event(
    url: str,
    *,
    actor: str = "SAMA",
    action: str = "raised rate",
    event_type: str = "monetary_policy",
) -> dict[str, Any]:
    return {
        "title": "Title",
        "date": "2020-06-15",
        "country": "Saudi Arabia",
        "summary": "An event.",
        "source": "Reuters",
        "url": url,
        "event_type": event_type,
        "actor": actor,
        "action": action,
        "kpi_keywords": ["rate"],
    }


def _set_fake_call(monkeypatch: pytest.MonkeyPatch, responses: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Patch call_json_model. Returns a stats dict (call counter, args list)."""
    state: dict[str, Any] = {"calls": 0, "args": [], "lock": threading.Lock()}

    def fake_call_json_model(**kwargs: Any) -> Any:
        with state["lock"]:
            state["calls"] += 1
            state["args"].append(kwargs)
        caller = kwargs.get("caller") or ""
        query_id = ""
        if "[" in caller and caller.endswith("]"):
            query_id = caller.rsplit("[", 1)[1].rstrip("]")
        events = responses.get(query_id, [])
        parsed = {"events": events}
        call_meta = {
            "input_tokens": 1,
            "output_tokens": 1,
            "input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
        }
        return parsed, call_meta

    monkeypatch.setattr(news_researcher, "call_json_model", fake_call_json_model)
    return state


# ---------------------------------------------------------------------------
# One Sonar call per planned query
# ---------------------------------------------------------------------------

def test_one_sonar_call_per_planned_query(monkeypatch: pytest.MonkeyPatch):
    planned = [
        _planned("q_001", "first query"),
        _planned("q_002", "second query"),
        _planned("q_003", "third query"),
    ]
    state = _set_fake_call(monkeypatch, {})
    news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert state["calls"] == 3


def test_empty_planned_list_makes_no_calls(monkeypatch: pytest.MonkeyPatch):
    state = _set_fake_call(monkeypatch, {})
    result = news_researcher.run_planned_queries(
        planned_queries=[],
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert state["calls"] == 0
    assert result["events"] == []
    assert result["by_query"] == []


def test_blank_query_string_is_skipped(monkeypatch: pytest.MonkeyPatch):
    planned = [
        _planned("q_001", "   "),
        _planned("q_002", "real"),
    ]
    state = _set_fake_call(monkeypatch, {})
    news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert state["calls"] == 1


# ---------------------------------------------------------------------------
# Event attribution
# ---------------------------------------------------------------------------

def test_every_emitted_event_is_tagged_with_planned_query_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    planned = [
        _planned("q_001", "first", hypothesis_id="G1_H1", group_ids=["g1"]),
        _planned("q_002", "second", hypothesis_id="G2_H1", group_ids=["g2", "g3"]),
    ]
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [_good_event("https://reuters.com/a")],
            "q_002": [_good_event("https://reuters.com/b")],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    events_by_query = {e["query_id"]: e for e in result["events"]}
    assert events_by_query["q_001"]["hypothesis_id"] == "G1_H1"
    assert events_by_query["q_001"]["group_ids"] == ["g1"]
    assert events_by_query["q_002"]["hypothesis_id"] == "G2_H1"
    assert events_by_query["q_002"]["group_ids"] == ["g2", "g3"]


def test_event_ids_are_sequential(monkeypatch: pytest.MonkeyPatch):
    planned = [_planned("q_001", "first"), _planned("q_002", "second")]
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [_good_event("https://r.com/1"), _good_event("https://r.com/2")],
            "q_002": [_good_event("https://r.com/3")],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    ids = [e["id"] for e in result["events"]]
    assert ids == ["ev_1", "ev_2", "ev_3"]


# ---------------------------------------------------------------------------
# Host + shape + dedup filtering
# ---------------------------------------------------------------------------

def test_statistical_host_filter_drops_known_aggregator_urls(
    monkeypatch: pytest.MonkeyPatch,
):
    planned = [_planned("q_001", "first")]
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [
                _good_event("https://www.gastat.gov.sa/release/123"),
                _good_event("https://reuters.com/keep"),
            ],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    urls = {e["url"] for e in result["events"]}
    assert "https://reuters.com/keep" in urls
    assert all("gastat.gov.sa" not in u for u in urls)
    assert result["by_query"][0]["dropped_host"] == 1
    assert result["by_query"][0]["kept"] == 1


def test_missing_actor_or_action_is_filtered_out(monkeypatch: pytest.MonkeyPatch):
    planned = [_planned("q_001", "first")]
    bad_event = _good_event("https://reuters.com/x")
    bad_event["actor"] = ""
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [bad_event, _good_event("https://reuters.com/y")],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert len(result["events"]) == 1
    assert result["by_query"][0]["dropped_missing_actor_or_action"] == 1


def test_duplicate_urls_are_deduped_across_queries(monkeypatch: pytest.MonkeyPatch):
    planned = [_planned("q_001", "first"), _planned("q_002", "second")]
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [_good_event("https://reuters.com/same")],
            "q_002": [_good_event("https://reuters.com/same")],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert len(result["events"]) == 1
    by_q2 = next(b for b in result["by_query"] if b["query_id"] == "q_002")
    assert by_q2["dropped_duplicate"] == 1


# ---------------------------------------------------------------------------
# by_query summary structure
# ---------------------------------------------------------------------------

def test_by_query_summary_has_one_row_per_planned_query(
    monkeypatch: pytest.MonkeyPatch,
):
    planned = [
        _planned("q_001", "first"),
        _planned("q_002", "second"),
        _planned("q_003", "third"),
    ]
    _set_fake_call(
        monkeypatch,
        {
            "q_001": [_good_event("https://r.com/1")],
            "q_002": [],
            "q_003": [_good_event("https://r.com/3")],
        },
    )
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert len(result["by_query"]) == 3
    by_id = {row["query_id"]: row for row in result["by_query"]}
    assert by_id["q_001"]["kept"] == 1
    assert by_id["q_002"]["kept"] == 0
    assert by_id["q_003"]["kept"] == 1


def test_by_query_row_has_required_keys(monkeypatch: pytest.MonkeyPatch):
    planned = [_planned("q_001", "first")]
    _set_fake_call(monkeypatch, {"q_001": [_good_event("https://r.com/1")]})
    result = news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    row = result["by_query"][0]
    for key in (
        "query_id",
        "query",
        "hypothesis_id",
        "group_ids",
        "raw_count",
        "kept",
        "dropped_host",
        "dropped_missing_actor_or_action",
        "dropped_duplicate",
    ):
        assert key in row


# ---------------------------------------------------------------------------
# Parallelism bound
# ---------------------------------------------------------------------------

def test_max_workers_is_capped_at_max_parallel_sonar_calls(
    monkeypatch: pytest.MonkeyPatch,
):
    captured_workers: dict[str, int] = {}
    original_executor = news_researcher.ThreadPoolExecutor

    class CapturingExecutor(original_executor):
        def __init__(self, max_workers: int | None = None, *args: Any, **kwargs: Any) -> None:
            captured_workers["max_workers"] = int(max_workers or 0)
            super().__init__(max_workers=max_workers, *args, **kwargs)

    monkeypatch.setattr(news_researcher, "ThreadPoolExecutor", CapturingExecutor)
    _set_fake_call(monkeypatch, {})
    planned = [_planned(f"q_{i:03d}", f"q{i}") for i in range(20)]
    news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert captured_workers["max_workers"] <= news_researcher.MAX_PARALLEL_SONAR_CALLS


# ---------------------------------------------------------------------------
# Sonar structured-output wiring
# ---------------------------------------------------------------------------

def test_planned_calls_pass_sonar_events_schema_to_call_json_model(
    monkeypatch: pytest.MonkeyPatch,
):
    """Every planned Sonar call must request structured output, so Sonar
    cannot quietly fall back to prose."""
    state = _set_fake_call(monkeypatch, {})
    planned = [_planned("q_001", "first"), _planned("q_002", "second")]
    news_researcher.run_planned_queries(
        planned_queries=planned,
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    assert state["calls"] == 2
    for kwargs in state["args"]:
        assert kwargs.get("use_perplexity") is True
        assert kwargs.get("response_schema") is news_researcher.SONAR_EVENTS_SCHEMA
        assert kwargs.get("response_schema_name") == "sonar_events"


def test_planned_user_prompts_explicitly_request_json_only(
    monkeypatch: pytest.MonkeyPatch,
):
    """Belt-and-suspenders: even with response_format, the prompt must say
    'JSON only' so older Sonar tiers / fallback paths also comply."""
    state = _set_fake_call(monkeypatch, {})
    news_researcher.run_planned_queries(
        planned_queries=[_planned("q_001", "first")],
        country_name="Saudi Arabia",
        start_year=2014,
        end_year=2024,
    )
    user_prompt = state["args"][0]["user_prompt"]
    assert "JSON" in user_prompt
    assert "events" in user_prompt
    assert "No prose" in user_prompt or "no prose" in user_prompt.lower()


def test_sonar_events_schema_is_perplexity_compliant():
    """Schema must satisfy Perplexity's hard constraints:
    additionalProperties=False on every object, all properties required,
    and a valid response_schema_name will be supplied at call sites.
    """
    schema = news_researcher.SONAR_EVENTS_SCHEMA
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["events"]

    event_schema = schema["properties"]["events"]["items"]
    assert event_schema["additionalProperties"] is False
    expected_required = {
        "title",
        "date",
        "country",
        "summary",
        "source",
        "url",
        "event_type",
        "actor",
        "action",
        "kpi_keywords",
    }
    assert set(event_schema["required"]) == expected_required
    assert set(event_schema["properties"].keys()) == expected_required
