"""Top-level lab pipeline orchestrator."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Iterator

from backend.lab.schemas import LabGenerateRequest
from backend.lab.workflow import (
    brief_writer,
    evaluator,
    hypotheses_generator,
    insights_generator,
    news_researcher,
    signal_extractor,
)
from backend.lab.workflow.common import ndjson
from backend.models.kpi_registry import SPECS_BY_ID
from backend.services.knoema_client import fetch_single_kpi

log = logging.getLogger(__name__)


def _event(
    event_type: str,
    *,
    stage: str | None = None,
    content: Any = None,
    meta: dict[str, Any] | None = None,
) -> str:
    payload = {"type": event_type, "stage": stage, "content": content, "meta": meta or {}}
    return ndjson(payload)


def _kpi_name(kpi_id: str) -> str:
    spec = SPECS_BY_ID.get(kpi_id)
    return spec.name if spec else f"KPI {kpi_id}"


def _kpi_payload(kpi_result: Any) -> dict[str, Any]:
    if hasattr(kpi_result, "model_dump"):
        return kpi_result.model_dump()
    if hasattr(kpi_result, "dict"):
        return kpi_result.dict()
    return dict(kpi_result)


def _split_call_meta(stage_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    payload = dict(stage_payload)
    call_meta = payload.pop("call_meta", None)
    return payload, call_meta


def run_pipeline(req: LabGenerateRequest) -> Iterator[str]:
    """Run all workflow steps and stream NDJSON updates."""
    try:
        run_id = str(uuid.uuid4())
        stage_costs: dict[str, dict[str, Any]] = {}

        if req.start_year >= req.end_year:
            raise ValueError("start_year must be less than end_year.")

        country = req.country.upper()
        kpi_name = _kpi_name(req.kpi_id)
        timerange = f"{req.start_year}-{req.end_year}"

        yield _event("status", content="Fetching KPI data...", meta={"run_id": run_id})
        kpi_result = fetch_single_kpi(
            countries=[country],
            kpi_id=req.kpi_id,
            frequency="A",
            timerange_a=timerange,
            timerange_q=timerange,
        )
        kpi_payload = _kpi_payload(kpi_result)
        yield _event(
            "stage",
            stage="data_fetch",
            content={
                "country": country,
                "kpi_id": req.kpi_id,
                "kpi_name": kpi_name,
                "series_count": len(kpi_payload.get("series", [])),
                "errors": kpi_payload.get("errors", []),
            },
            meta={"run_id": run_id, "cost": None},
        )

        yield _event("status", content="Running signal extraction...", meta={"run_id": run_id})
        signal_output = signal_extractor.run_step(kpi_payload)
        signal_content, signal_cost = _split_call_meta(signal_output)
        if signal_cost:
            stage_costs["signal_extractor"] = signal_cost
        yield _event(
            "stage",
            stage="signal_extractor",
            content=signal_content,
            meta={"run_id": run_id, "cost": signal_cost},
        )

        yield _event("status", content="Generating hypotheses...", meta={"run_id": run_id})
        hypotheses_output = hypotheses_generator.run_step(
            country=country,
            kpi_id=req.kpi_id,
            kpi_name=kpi_name,
            start_year=req.start_year,
            end_year=req.end_year,
            selected_signals=signal_content.get("selected_signals", []),
        )
        hypotheses_content, hypotheses_cost = _split_call_meta(hypotheses_output)
        if hypotheses_cost:
            stage_costs["hypotheses_generator"] = hypotheses_cost
        yield _event(
            "stage",
            stage="hypotheses_generator",
            content=hypotheses_content,
            meta={"run_id": run_id, "cost": hypotheses_cost},
        )

        yield _event("status", content="Researching external evidence...", meta={"run_id": run_id})
        news_output = news_researcher.run_step(
            country=country,
            kpi_name=kpi_name,
            start_year=req.start_year,
            end_year=req.end_year,
            hypotheses=hypotheses_content.get("hypotheses", []),
        )
        news_content, news_cost = _split_call_meta(news_output)
        if news_cost:
            stage_costs["news_researcher"] = news_cost
        yield _event(
            "stage",
            stage="news_researcher",
            content=news_content,
            meta={"run_id": run_id, "cost": news_cost},
        )

        yield _event("status", content="Generating insights...", meta={"run_id": run_id})
        first_insights = insights_generator.run_step(
            country=country,
            kpi_name=kpi_name,
            selected_signals=signal_content.get("selected_signals", []),
            hypotheses=hypotheses_content.get("hypotheses", []),
            evidence_items=news_content.get("evidence_items", []),
        )
        first_insights_content, first_insights_cost = _split_call_meta(first_insights)
        if first_insights_cost:
            stage_costs["insights_generator_first_pass"] = first_insights_cost
        yield _event(
            "stage",
            stage="insights_generator_first_pass",
            content=first_insights_content,
            meta={"run_id": run_id, "cost": first_insights_cost},
        )

        yield _event("status", content="Evaluating insight quality...", meta={"run_id": run_id})
        evaluator_output = evaluator.run_step(
            country=country,
            kpi_name=kpi_name,
            insight_payload=first_insights_content,
        )
        evaluator_content, evaluator_cost = _split_call_meta(evaluator_output)
        if evaluator_cost:
            stage_costs["evaluator"] = evaluator_cost
        yield _event(
            "stage",
            stage="evaluator",
            content=evaluator_content,
            meta={"run_id": run_id, "cost": evaluator_cost},
        )

        yield _event("status", content="Applying one revision pass...", meta={"run_id": run_id})
        revised_insights = insights_generator.run_step(
            country=country,
            kpi_name=kpi_name,
            selected_signals=signal_content.get("selected_signals", []),
            hypotheses=hypotheses_content.get("hypotheses", []),
            evidence_items=news_content.get("evidence_items", []),
            evaluator_feedback=evaluator_content.get("revision_instructions", []),
        )
        revised_insights_content, revised_insights_cost = _split_call_meta(revised_insights)
        if revised_insights_cost:
            stage_costs["insights_generator"] = revised_insights_cost
        yield _event(
            "stage",
            stage="insights_generator",
            content=revised_insights_content,
            meta={"run_id": run_id, "cost": revised_insights_cost},
        )

        yield _event("status", content="Writing final brief...", meta={"run_id": run_id})
        brief_output = brief_writer.run_step(
            country=country,
            kpi_name=kpi_name,
            start_year=req.start_year,
            end_year=req.end_year,
            selected_signals=signal_content.get("selected_signals", []),
            final_insights=revised_insights_content,
            evaluator_output=evaluator_content,
        )
        brief_content, brief_cost = _split_call_meta(brief_output)
        if brief_cost:
            stage_costs["brief_writer"] = brief_cost
        yield _event(
            "stage",
            stage="brief_writer",
            content=brief_content,
            meta={"run_id": run_id, "cost": brief_cost},
        )

        total_cost = sum(item.get("total_cost", 0.0) for item in stage_costs.values())

        yield _event(
            "result",
            stage="pipeline",
            content={
                "run_id": run_id,
                "country": country,
                "kpi_id": req.kpi_id,
                "kpi_name": kpi_name,
                "brief_markdown": brief_content.get("brief_markdown", ""),
                "stage_costs": stage_costs,
                "total_cost": total_cost,
            },
            meta={"run_id": run_id},
        )
        yield _event(
            "done",
            stage="pipeline",
            content={"ok": True, "run_id": run_id, "stage_costs": stage_costs, "total_cost": total_cost},
            meta={"run_id": run_id},
        )
    except Exception as exc:
        log.exception("Lab pipeline failed")
        yield _event("error", stage="pipeline", content={"message": str(exc)})
        yield _event("done", stage="pipeline", content={"ok": False})

