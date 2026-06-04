"""Tests for run_step_groups post-validation and structured-outputs wiring."""
from __future__ import annotations

import json
from typing import Any

import pytest

from backend.insights_pipeline.stages import common, hypotheses_generator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _attached_group(group_id: str, signal_ids: list[str]) -> dict[str, Any]:
    return {
        "group_id": group_id,
        "group_type": "family",
        "label": group_id,
        "net_direction": "down",
        "size": 1,
        "members": [{"kpi_id": "3", "role": "member"}],
        "signals": [
            {"id": sid, "kpi_id": "3", "direction": "down"} for sid in signal_ids
        ],
    }


def _hyp(
    *,
    hypothesis_id: str,
    hypothesis_type: str = "external_shock",
    explains: list[str] | None = None,
    does_not_explain: list[str] | None = None,
    search_priority: str = "high",
) -> dict[str, Any]:
    return {
        "hypothesis_id": hypothesis_id,
        "hypothesis_type": hypothesis_type,
        "hypothesis": "Hypothesis text.",
        "mechanism": "Mechanism text.",
        "explains_signals": list(explains or []),
        "does_not_explain": list(does_not_explain or []),
        "expected_evidence": ["something supportive"],
        "neutral_search_queries": ["neutral query"],
        "search_priority": search_priority,
        "brief_use_before_evidence": "do_not_use_as_claim",
    }


def _make_run(
    monkeypatch: pytest.MonkeyPatch,
    parsed_payload: dict[str, Any],
) -> dict[str, Any]:
    """Patch call_json_model to return parsed_payload, return its document."""
    captured: dict[str, Any] = {}

    def fake_call_json_model(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return parsed_payload, {"model": "stub", "usd_cost": 0.0}

    monkeypatch.setattr(hypotheses_generator, "call_json_model", fake_call_json_model)

    attached_groups = [
        _attached_group("family:growth", ["sig_001", "sig_002"]),
        _attached_group("family:fiscal", ["sig_003"]),
    ]
    result = hypotheses_generator.run_step_groups(
        country="Saudi Arabia",
        period="2014-2024",
        archetype_tags=["oil_exporter"],
        attached_groups=attached_groups,
    )
    return {"result": result, "captured": captured, "attached": attached_groups}


# ---------------------------------------------------------------------------
# Forced null/data hypothesis injection
# ---------------------------------------------------------------------------

def test_missing_null_hypothesis_is_injected_for_every_group(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "Growth weakness",
                "group_level_question": "What explains growth weakness?",
                "hypotheses": [
                    _hyp(
                        hypothesis_id="G1_H1",
                        hypothesis_type="external_shock",
                        explains=["sig_001"],
                    ),
                ],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "Fiscal pressure",
                "group_level_question": "What explains fiscal pressure?",
                "hypotheses": [
                    _hyp(
                        hypothesis_id="G2_H1",
                        hypothesis_type="fiscal_policy",
                        explains=["sig_003"],
                    ),
                ],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    bundle = _make_run(monkeypatch, parsed)
    doc = bundle["result"]["document"]

    for group in doc["hypothesis_groups"]:
        types = [h["hypothesis_type"] for h in group["hypotheses"]]
        assert types.count("null_data_hypothesis") == 1

    growth_group = next(
        g for g in doc["hypothesis_groups"] if g["group_id"] == "family:growth"
    )
    null_hyp = next(
        h
        for h in growth_group["hypotheses"]
        if h["hypothesis_type"] == "null_data_hypothesis"
    )
    assert set(null_hyp["explains_signals"]) == {"sig_001", "sig_002"}
    assert null_hyp["hypothesis_id"] == "family:growth_H_null"
    assert null_hyp["search_priority"] == "low"


def test_existing_null_hypothesis_is_preserved_not_duplicated(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "Growth weakness",
                "group_level_question": "?",
                "hypotheses": [
                    _hyp(
                        hypothesis_id="H_null_custom",
                        hypothesis_type="null_data_hypothesis",
                        explains=["sig_001"],
                        search_priority="low",
                    ),
                ],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "Fiscal pressure",
                "group_level_question": "?",
                "hypotheses": [
                    _hyp(hypothesis_id="G2_H1", explains=["sig_003"]),
                ],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    growth = next(
        g for g in doc["hypothesis_groups"] if g["group_id"] == "family:growth"
    )
    null_hyps = [
        h for h in growth["hypotheses"] if h["hypothesis_type"] == "null_data_hypothesis"
    ]
    assert len(null_hyps) == 1


def test_group_omitted_by_llm_is_synthesized_with_null_hypothesis(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "Growth",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G1_H1")],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    group_ids = {g["group_id"] for g in doc["hypothesis_groups"]}
    assert "family:growth" in group_ids
    assert "family:fiscal" in group_ids
    fiscal = next(
        g for g in doc["hypothesis_groups"] if g["group_id"] == "family:fiscal"
    )
    assert len(fiscal["hypotheses"]) == 1
    assert fiscal["hypotheses"][0]["hypothesis_type"] == "null_data_hypothesis"


# ---------------------------------------------------------------------------
# Type whitelist enforcement (post-LLM, not just schema)
# ---------------------------------------------------------------------------

def test_hypothesis_type_outside_whitelist_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [
                    _hyp(
                        hypothesis_id="G1_H1",
                        hypothesis_type="alien_invasion",
                        explains=["sig_001"],
                    ),
                ],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }

    def fake_call_json_model(**kwargs: Any) -> Any:
        return parsed, {"model": "stub", "usd_cost": 0.0}

    monkeypatch.setattr(hypotheses_generator, "call_json_model", fake_call_json_model)

    attached = [_attached_group("family:growth", ["sig_001"])]
    with pytest.raises(ValueError):
        hypotheses_generator.run_step_groups(
            country="Saudi Arabia",
            period="2014-2024",
            archetype_tags=None,
            attached_groups=attached,
        )


# ---------------------------------------------------------------------------
# Signal-id filtering
# ---------------------------------------------------------------------------

def test_explains_signals_with_unknown_id_is_filtered_out(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [
                    _hyp(
                        hypothesis_id="G1_H1",
                        hypothesis_type="external_shock",
                        explains=["sig_001", "sig_999"],
                        does_not_explain=["sig_002", "sig_404"],
                    ),
                ],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G2_H1", explains=["sig_003"])],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    growth = next(
        g for g in doc["hypothesis_groups"] if g["group_id"] == "family:growth"
    )
    hyp = next(h for h in growth["hypotheses"] if h["hypothesis_id"] == "G1_H1")
    assert hyp["explains_signals"] == ["sig_001"]
    assert hyp["does_not_explain"] == ["sig_002"]


# ---------------------------------------------------------------------------
# Cross-group dedup filtering
# ---------------------------------------------------------------------------

def test_cross_group_with_unknown_group_id_is_dropped(monkeypatch: pytest.MonkeyPatch):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G1_H1", explains=["sig_001"])],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G2_H1", explains=["sig_003"])],
            },
        ],
        "cross_group_hypotheses": [
            {
                "hypothesis": "Cross story",
                "related_groups": ["family:growth", "family:fiscal"],
                "search_once": True,
                "preferred_search_query": "q",
            },
            {
                "hypothesis": "Bogus",
                "related_groups": ["family:imaginary", "family:another_imaginary"],
                "search_once": True,
                "preferred_search_query": "q2",
            },
        ],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    cross_hyps = doc["cross_group_hypotheses"]
    assert len(cross_hyps) == 1
    assert cross_hyps[0]["related_groups"] == ["family:growth", "family:fiscal"]


# ---------------------------------------------------------------------------
# Hypothesis-id renumbering on collisions
# ---------------------------------------------------------------------------

def test_colliding_hypothesis_ids_are_renumbered_with_stable_pattern(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [
                    _hyp(hypothesis_id="dupe", explains=["sig_001"]),
                    _hyp(hypothesis_id="dupe", explains=["sig_002"]),
                    _hyp(hypothesis_id="dupe", explains=["sig_001"]),
                ],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G2_H1", explains=["sig_003"])],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    growth = next(
        g for g in doc["hypothesis_groups"] if g["group_id"] == "family:growth"
    )
    non_null_ids = [
        h["hypothesis_id"]
        for h in growth["hypotheses"]
        if h["hypothesis_type"] != "null_data_hypothesis"
    ]
    assert non_null_ids == [
        "family:growth_H1",
        "family:growth_H2",
        "family:growth_H3",
    ]
    null_hyp = next(
        h
        for h in growth["hypotheses"]
        if h["hypothesis_type"] == "null_data_hypothesis"
    )
    assert null_hyp["hypothesis_id"] == "family:growth_H_null"


# ---------------------------------------------------------------------------
# Standard warning + period/country preservation
# ---------------------------------------------------------------------------

def test_standard_warning_appended_when_missing(monkeypatch: pytest.MonkeyPatch):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    assert any(
        "unverified" in w.lower() and "evidence" in w.lower() for w in doc["warnings"]
    )


def test_response_schema_is_passed_to_call_json_model(monkeypatch: pytest.MonkeyPatch):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    captured = _make_run(monkeypatch, parsed)["captured"]
    assert captured.get("response_schema") is hypotheses_generator.HYPOTHESES_OUTPUT_SCHEMA
    assert captured.get("response_schema_name") == "hypotheses_document"


# ---------------------------------------------------------------------------
# Structured-outputs wiring at the call_json_model layer
# ---------------------------------------------------------------------------

def test_call_json_model_passes_structured_outputs_response_format(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeUsage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    class FakeChatCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(common, "_openai_client", lambda: FakeClient())
    monkeypatch.setattr(
        common,
        "estimate_usage_cost",
        lambda model, usage: {"usd_cost": 0.0},
    )
    monkeypatch.setattr(common, "record_usage", lambda *a, **kw: None)

    schema = {"type": "object", "additionalProperties": False, "required": [], "properties": {}}
    parsed = common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
        response_schema=schema,
        response_schema_name="my_output",
    )

    assert parsed == {"ok": True}
    response_format = captured.get("response_format")
    assert response_format is not None
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "my_output"
    assert response_format["json_schema"]["schema"] is schema
    assert response_format["json_schema"]["strict"] is True


def test_call_json_model_does_not_pass_response_format_when_schema_omitted(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, Any] = {}

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeUsage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    class FakeChatCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(common, "_openai_client", lambda: FakeClient())
    monkeypatch.setattr(
        common,
        "estimate_usage_cost",
        lambda model, usage: {"usd_cost": 0.0},
    )
    monkeypatch.setattr(common, "record_usage", lambda *a, **kw: None)

    common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test",
    )
    assert "response_format" not in captured


# ---------------------------------------------------------------------------
# Schema-level guarantees for the trimmed contract (issue 4c)
# ---------------------------------------------------------------------------

def test_hypothesis_schema_does_not_require_contradictory_evidence():
    schema = hypotheses_generator._hypothesis_object_schema()
    assert "contradictory_evidence" not in schema["required"]
    assert "contradictory_evidence" not in schema["properties"]


def test_hypothesis_schema_caps_evidence_and_query_arrays():
    schema = hypotheses_generator._hypothesis_object_schema()
    assert schema["properties"]["expected_evidence"]["maxItems"] == 3
    assert schema["properties"]["neutral_search_queries"]["maxItems"] == 3


def test_validate_hypothesis_truncates_oversized_arrays():
    hyp = {
        "hypothesis_id": "H1",
        "hypothesis_type": "external_shock",
        "hypothesis": "x",
        "mechanism": "y",
        "explains_signals": ["sig_001"],
        "does_not_explain": [],
        "expected_evidence": ["e1", "e2", "e3", "e4", "e5"],
        "neutral_search_queries": ["q1", "q2", "q3", "q4"],
        "search_priority": "high",
        "brief_use_before_evidence": "do_not_use_as_claim",
    }
    out = hypotheses_generator._validate_hypothesis(
        hyp,
        group_id="G",
        valid_signal_ids={"sig_001"},
    )
    assert out["expected_evidence"] == ["e1", "e2", "e3"]
    assert out["neutral_search_queries"] == ["q1", "q2", "q3"]
    assert "contradictory_evidence" not in out


def test_validated_document_never_contains_contradictory_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    parsed = {
        "country": "Saudi Arabia",
        "period": "2014-2024",
        "hypothesis_groups": [
            {
                "group_id": "family:growth",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G1_H1", explains=["sig_001"])],
            },
            {
                "group_id": "family:fiscal",
                "group_theme": "?",
                "group_level_question": "?",
                "hypotheses": [_hyp(hypothesis_id="G2_H1", explains=["sig_003"])],
            },
        ],
        "cross_group_hypotheses": [],
        "search_plan_seed": {
            "highest_priority_questions": [],
            "queries_to_run_first": [],
            "queries_to_skip_unless_needed": [],
        },
        "warnings": [],
    }
    doc = _make_run(monkeypatch, parsed)["result"]["document"]
    for group in doc["hypothesis_groups"]:
        for hyp in group["hypotheses"]:
            assert "contradictory_evidence" not in hyp


# ---------------------------------------------------------------------------
# Input-trim: _trim_signal_for_prompt drops noisy fields (issue 4b)
# ---------------------------------------------------------------------------

def test_trim_signal_for_prompt_keeps_only_essential_fields():
    sig = {
        "id": "sig_001",
        "signal_type": "shock",
        "kpi": "Real GDP",
        "kpi_id": "3",
        "direction": "down",
        "pct_change": 0.12345678,
        "period_start": "2022-01-01",
        "period_end": "2024-12-31",
        "country": "Saudi Arabia",
        "frequency": "annual",
        "unit": "%",
        "start_value": 100.0,
        "end_value": 88.0,
        "abs_change": -12.0,
        "period_length_months": 36,
        "metrics": {"z_score": 1.8, "pivot_date": "2023-06-01"},
    }
    trimmed = hypotheses_generator._trim_signal_for_prompt(sig)
    assert set(trimmed.keys()) == {
        "id",
        "signal_type",
        "kpi",
        "kpi_id",
        "direction",
        "pct_change",
        "period",
    }
    assert trimmed["pct_change"] == 0.123
    assert trimmed["period"] == "2022-01-01..2024-12-31"


def test_trim_signal_for_prompt_handles_malformed_pct_change():
    trimmed = hypotheses_generator._trim_signal_for_prompt({"id": "x", "pct_change": "not-a-number"})
    assert trimmed["pct_change"] == 0.0


def test_summarize_attached_group_projects_signals_through_trimmer():
    group = {
        "group_id": "family:growth",
        "group_type": "family",
        "label": "growth",
        "net_direction": "down",
        "size": 1,
        "members": [{"kpi_id": "3", "role": "member"}],
        "signals": [
            {
                "id": "sig_001",
                "signal_type": "shock",
                "kpi_id": "3",
                "direction": "down",
                "pct_change": 0.5,
                "period_start": "2022-01",
                "period_end": "2024-12",
                "metrics": {"z_score": 1.5},
                "frequency": "annual",
            }
        ],
    }
    out = hypotheses_generator._summarize_attached_group_for_prompt(group)
    sig = out["signals"][0]
    assert "metrics" not in sig
    assert "frequency" not in sig
    assert sig["period"] == "2022-01..2024-12"


# ---------------------------------------------------------------------------
# Truncation visibility (issue 4a)
# ---------------------------------------------------------------------------

def _patch_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str,
    finish_reason: str | None,
    completion_tokens: int = 100,
    reasoning_tokens: int = 0,
) -> None:
    class FakeMessage:
        def __init__(self, c: str) -> None:
            self.content = c

    class FakeChoice:
        def __init__(self, msg: FakeMessage, fr: str | None) -> None:
            self.message = msg
            self.finish_reason = fr

    class FakeCompletionDetails:
        def __init__(self, r: int) -> None:
            self.reasoning_tokens = r

    class FakeUsage:
        def __init__(self, ct: int, r: int) -> None:
            self.prompt_tokens = 50
            self.completion_tokens = ct
            self.total_tokens = ct + 50
            self.completion_tokens_details = FakeCompletionDetails(r)

    class FakeResponse:
        def __init__(self) -> None:
            self.choices = [FakeChoice(FakeMessage(content), finish_reason)]
            self.usage = FakeUsage(completion_tokens, reasoning_tokens)

    class FakeChatCompletions:
        def create(self, **kwargs: Any) -> Any:
            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(common, "_openai_client", lambda: FakeClient())
    monkeypatch.setattr(common, "_perplexity_client", lambda: FakeClient())
    monkeypatch.setattr(common, "estimate_usage_cost", lambda m, u: {"usd_cost": 0.0})
    monkeypatch.setattr(common, "record_usage", lambda *a, **kw: None)


def test_call_json_model_flags_truncated_non_json_response(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _patch_fake_openai(
        monkeypatch,
        content='{"hypothesis_groups": [{"group_id": "g1", "hypotheses": [',
        finish_reason="length",
        completion_tokens=12000,
        reasoning_tokens=8123,
    )
    caplog.set_level("WARNING", logger=common.log.name)
    result = common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.truncation",
    )
    assert isinstance(result, dict)
    assert result.get("_truncated") is True
    assert result.get("_finish_reason") == "length"
    assert "raw_text" in result
    # Loud warning AND error path (truncated + non-JSON).
    all_messages = " ".join(r.getMessage() for r in caplog.records)
    assert "max_completion_tokens" in all_messages
    assert "reasoning_tokens" in all_messages


def test_call_json_model_flags_truncated_but_parseable_json(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    _patch_fake_openai(
        monkeypatch,
        content='{"ok": true}',
        finish_reason="length",
        completion_tokens=12000,
        reasoning_tokens=5000,
    )
    caplog.set_level("WARNING", logger=common.log.name)
    result = common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.partial_truncation",
    )
    assert result.get("ok") is True
    assert result.get("_truncated") is True
    assert result.get("_finish_reason") == "length"
    assert any("max_completion_tokens" in r.getMessage() for r in caplog.records)


def test_call_json_model_does_not_flag_completed_response(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_fake_openai(
        monkeypatch,
        content='{"ok": true}',
        finish_reason="stop",
        completion_tokens=200,
        reasoning_tokens=50,
    )
    result = common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.no_truncation",
    )
    assert result.get("ok") is True
    assert "_truncated" not in result
    assert "_finish_reason" not in result


def test_call_json_model_call_meta_includes_truncation_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_fake_openai(
        monkeypatch,
        content='{"ok": true}',
        finish_reason="stop",
        completion_tokens=200,
        reasoning_tokens=50,
    )
    parsed, meta = common.call_json_model(
        model="gpt-5.3-chat-latest",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.meta",
        include_call_meta=True,
    )
    assert meta["finish_reason"] == "stop"
    assert meta["reasoning_tokens"] == 50
    assert meta["visible_tokens"] == 150


# ---------------------------------------------------------------------------
# Embedded-JSON recovery (Sonar-style prose responses with JSON inside)
# ---------------------------------------------------------------------------

def test_extract_embedded_json_pulls_from_code_fence():
    text = (
        "Here are the events I found:\n"
        "```json\n"
        '{"events": [{"title": "x"}]}\n'
        "```\n"
        "Let me know if you need more!"
    )
    recovered = common._extract_embedded_json(text)
    assert recovered is not None
    assert json.loads(recovered) == {"events": [{"title": "x"}]}


def test_extract_embedded_json_pulls_object_from_prose():
    text = (
        "I found 2 events for the time window: "
        '{"events": [{"title": "a"}, {"title": "b"}]} '
        "(citations [1][2] above)."
    )
    recovered = common._extract_embedded_json(text)
    assert recovered is not None
    parsed = json.loads(recovered)
    assert parsed["events"][0]["title"] == "a"


def test_extract_embedded_json_wraps_bare_array_under_events():
    text = "Events:\n[{\"title\": \"a\"}, {\"title\": \"b\"}]\n-- end --"
    recovered = common._extract_embedded_json(text)
    assert recovered is not None
    parsed = json.loads(recovered)
    assert parsed == {"events": [{"title": "a"}, {"title": "b"}]}


def test_extract_embedded_json_returns_none_for_pure_prose():
    text = "I could not find any events matching your query. Sorry about that."
    assert common._extract_embedded_json(text) is None


def test_extract_embedded_json_returns_none_for_empty():
    assert common._extract_embedded_json("") is None
    assert common._extract_embedded_json(None) is None  # type: ignore[arg-type]


def test_call_json_model_recovers_json_embedded_in_prose(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """Simulates the exact Sonar failure mode from terminal 7:
    prose response with JSON in a code fence -> must recover, not fall back.
    """
    _patch_fake_openai(
        monkeypatch,
        content=(
            "Here are the events I found in the 2014-2024 window:\n"
            "```json\n"
            '{"events": [{"title": "Saudi Vision 2030 launched", "country": "SA"}]}\n'
            "```\n"
            "Sources: [1] Reuters, [2] Bloomberg."
        ),
        finish_reason="stop",
    )
    caplog.set_level("INFO", logger=common.log.name)
    result = common.call_json_model(
        model="sonar",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.sonar_recovery",
        use_perplexity=True,
    )
    assert result["events"][0]["title"] == "Saudi Vision 2030 launched"
    # No "non-JSON output" warning -- we recovered.
    assert not any("non-JSON output" in r.getMessage() for r in caplog.records)
    # An INFO log noting recovery should appear.
    assert any("recovered JSON" in r.getMessage() for r in caplog.records)


def test_call_json_model_passes_response_format_to_perplexity_without_strict(
    monkeypatch: pytest.MonkeyPatch,
):
    """Sonar's response_format takes the same json_schema shape as OpenAI
    but does NOT accept the `strict` flag."""
    captured: dict[str, Any] = {}

    class FakeMessage:
        content = '{"events": []}'

    class FakeChoice:
        message = FakeMessage()
        finish_reason = "stop"

    class FakeUsage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

    class FakeResponse:
        choices = [FakeChoice()]
        usage = FakeUsage()

    class FakeChatCompletions:
        def create(self, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(common, "_perplexity_client", lambda: FakeClient())
    monkeypatch.setattr(common, "estimate_usage_cost", lambda m, u: {"usd_cost": 0.0})
    monkeypatch.setattr(common, "record_usage", lambda *a, **kw: None)

    schema = {"type": "object", "additionalProperties": False, "required": [], "properties": {}}
    common.call_json_model(
        model="sonar",
        system_prompt="sys",
        user_prompt="usr",
        caller="test.sonar_schema",
        use_perplexity=True,
        response_schema=schema,
        response_schema_name="sonar_events",
    )
    rf = captured.get("response_format")
    assert rf is not None, "response_format must be passed to Perplexity when schema set"
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "sonar_events"
    assert rf["json_schema"]["schema"] is schema
    # CRITICAL: no strict flag for Perplexity -- their API rejects it.
    assert "strict" not in rf["json_schema"]


def test_run_step_groups_logs_error_when_response_truncated(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """When call_json_model returns _truncated, run_step_groups must log an ERROR."""
    truncated_payload = {
        "_truncated": True,
        "_finish_reason": "length",
        "raw_text": "{partial",
    }

    def fake_call_json_model(**kwargs: Any) -> Any:
        return truncated_payload, {
            "model": "stub",
            "finish_reason": "length",
            "reasoning_tokens": 8000,
            "visible_tokens": 4000,
            "usd_cost": 0.0,
        }

    monkeypatch.setattr(hypotheses_generator, "call_json_model", fake_call_json_model)
    caplog.set_level("ERROR", logger=hypotheses_generator.log.name)

    attached = [_attached_group("family:growth", ["sig_001"])]
    result = hypotheses_generator.run_step_groups(
        country="Saudi Arabia",
        period="2014-2024",
        archetype_tags=None,
        attached_groups=attached,
    )
    doc = result["document"]
    # Doc still degrades gracefully -- null hypotheses for every group.
    assert doc["hypothesis_groups"][0]["hypotheses"][0]["hypothesis_type"] == "null_data_hypothesis"
    # Loud ERROR about truncation -- never silently lose news flow again.
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("truncated" in r.getMessage() for r in error_records)
    assert any("finish_reason=length" in r.getMessage() for r in error_records)
