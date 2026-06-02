"""Tests for run_step_groups post-validation and structured-outputs wiring."""
from __future__ import annotations

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
        "contradictory_evidence": ["something contradicting"],
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
