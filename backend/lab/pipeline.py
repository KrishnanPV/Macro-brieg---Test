"""Top-level lab pipeline orchestrator."""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
from backend.lab.workflow.common import BRIEF_MODEL, REASONING_MODEL, ndjson
from backend.models.kpi_registry import SPECS_BY_ID
from backend.services.knoema_client import fetch_single_kpi

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
BASELINE_PROMPT_FILES = ("manifest.yaml", "PROMPT_CHANGES.md")


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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_json(value: Any) -> str:
    return json.dumps(value, indent=2, default=str, ensure_ascii=False)


def _git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _load_prompt_manifest() -> tuple[dict[str, Any], str | None]:
    manifest_path = PROMPTS_DIR / "manifest.yaml"
    if not manifest_path.exists():
        return {}, "manifest.yaml not found"
    text = manifest_path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, f"manifest parse error: {exc.msg}"
    return parsed if isinstance(parsed, dict) else {}, None


def _file_mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return ts.replace(microsecond=0).isoformat()


def _collect_prompt_git_changes(manifest_prompt_files: list[str]) -> dict[str, Any]:
    tracked_files = list(dict.fromkeys([*BASELINE_PROMPT_FILES, *manifest_prompt_files]))
    tracked_paths = [f"backend/lab/prompts/{name}" for name in tracked_files]
    status_text = _git(["status", "--porcelain", "--", *tracked_paths])
    if not status_text:
        return {
            "has_changes": False,
            "changed_files": [],
            "summary": "No staged or unstaged changes in prompt artifacts.",
        }

    changed_files: list[dict[str, Any]] = []
    for line in status_text.splitlines():
        if len(line) < 4:
            continue
        index_code, worktree_code = line[0], line[1]
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1]
        normalized_path = raw_path.replace("\\", "/")
        abs_path = REPO_ROOT / Path(normalized_path)
        if index_code != " " and worktree_code != " ":
            state = "staged+unstaged"
        elif index_code != " ":
            state = "staged"
        else:
            state = "unstaged"
        changed_files.append(
            {
                "path": normalized_path,
                "file": Path(normalized_path).name,
                "state": state,
                "staged": index_code != " ",
                "unstaged": worktree_code != " ",
                "last_modified": _file_mtime_iso(abs_path),
            }
        )

    changed_files.sort(key=lambda item: item["path"])
    summary_parts = [
        f"{item['file']} ({item['state']}, {item['last_modified'] or 'mtime unknown'})"
        for item in changed_files[:6]
    ]
    if len(changed_files) > 6:
        summary_parts.append(f"+{len(changed_files) - 6} more")
    return {
        "has_changes": True,
        "changed_files": changed_files,
        "summary": "; ".join(summary_parts),
    }


def _manifest_prompt_versions(manifest: dict[str, Any], executed_steps: set[str]) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    for prompt in manifest.get("prompts", []):
        if not isinstance(prompt, dict):
            continue
        used_by = [step for step in prompt.get("used_by", []) if isinstance(step, str)]
        versions.append(
            {
                "id": prompt.get("id"),
                "file": prompt.get("file"),
                "version": prompt.get("version"),
                "used_by": used_by,
                "used_in_run": any(step in executed_steps for step in used_by),
            }
        )
    return versions


def _build_report_payload(
    *,
    run_id: str,
    req: LabGenerateRequest,
    country: str,
    kpi_name: str,
    stage_outputs: dict[str, Any],
    stage_costs: dict[str, dict[str, Any]],
    total_cost: float,
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    started_iso = started_at.replace(microsecond=0).isoformat()
    finished_iso = finished_at.replace(microsecond=0).isoformat()
    manifest, manifest_error = _load_prompt_manifest()
    prompt_versions = _manifest_prompt_versions(manifest, set(stage_outputs.keys()))
    manifest_prompt_files = [item["file"] for item in prompt_versions if isinstance(item.get("file"), str)]
    prompt_git_changes = _collect_prompt_git_changes(manifest_prompt_files)

    model_by_stage = {
        stage: cost.get("model")
        for stage, cost in stage_costs.items()
        if isinstance(cost, dict) and cost.get("model")
    }
    steps = [
        {
            "stage": stage,
            "content": content,
            "cost": stage_costs.get(stage),
        }
        for stage, content in stage_outputs.items()
    ]

    metadata: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "run": {
            "run_id": run_id,
            "country": country,
            "kpi_id": req.kpi_id,
            "kpi_name": kpi_name,
            "start_year": req.start_year,
            "end_year": req.end_year,
            "generation_mode": req.generation_mode,
            "started_at": started_iso,
            "finished_at": finished_iso,
            "duration_seconds": round((finished_at - started_at).total_seconds(), 2),
        },
        "prompts": {
            "manifest_version": manifest.get("manifest_version"),
            "prompt_bundle_version": manifest.get("prompt_bundle_version"),
            "manifest_updated_at": manifest.get("updated_at"),
            "manifest_parse_error": manifest_error,
            "prompt_versions": prompt_versions,
            "has_uncommitted_prompt_changes": prompt_git_changes["has_changes"],
            "prompt_change_summary": prompt_git_changes["summary"],
            "prompt_changed_files": prompt_git_changes["changed_files"],
        },
        "git": {
            "branch": _git(["rev-parse", "--abbrev-ref", "HEAD"]) or None,
            "commit": _git(["rev-parse", "HEAD"]) or None,
            "commit_short": _git(["rev-parse", "--short", "HEAD"]) or None,
            "commit_time": _git(["show", "-s", "--format=%cI", "HEAD"]) or None,
        },
        "models": {
            "manifest_models": manifest.get("models", {}),
            "requested_reasoning_model": req.reasoning_model or REASONING_MODEL,
            "requested_brief_model": req.brief_model or BRIEF_MODEL,
            "stage_model_map": model_by_stage,
            "models_used": sorted(set(model_by_stage.values())),
        },
        "runtime": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
    }

    report_json = {
        "metadata": metadata,
        "steps": steps,
        "stage_costs": stage_costs,
        "total_cost": total_cost,
        "final_brief_markdown": stage_outputs.get("brief_writer", {}).get("brief_markdown", ""),
    }
    report_sha = hashlib.sha256(_safe_json(report_json).encode("utf-8")).hexdigest()
    report_json["report_sha256"] = report_sha
    metadata["report_sha256"] = report_sha

    markdown_lines = [
        "# Macrobrief Lab Final Report",
        "",
        f"- Generated (UTC): {metadata['generated_at']}",
        f"- Run ID: {run_id}",
        f"- Scope: {country} | {req.kpi_id} ({kpi_name}) | {req.start_year}-{req.end_year}",
        f"- Total Cost: ${total_cost:.6f}",
        "",
        "## Reproducibility Metadata",
        "",
        f"- Git Commit: {metadata['git']['commit'] or 'unknown'}",
        f"- Git Branch: {metadata['git']['branch'] or 'unknown'}",
        f"- Prompt Bundle Version: {metadata['prompts']['prompt_bundle_version'] or 'unknown'}",
        f"- Prompt Files Dirty: {'yes' if metadata['prompts']['has_uncommitted_prompt_changes'] else 'no'}",
        f"- Prompt Changes: {metadata['prompts']['prompt_change_summary']}",
        f"- Models Used: {', '.join(metadata['models']['models_used']) or 'none'}",
        "",
        "## Prompt Versions (From manifest.yaml)",
        "",
    ]
    if prompt_versions:
        markdown_lines.extend(
            [
                "| Prompt ID | File | Version | Used In Run |",
                "|---|---|---|---|",
            ]
        )
        for item in prompt_versions:
            markdown_lines.append(
                f"| {item.get('id', '')} | {item.get('file', '')} | {item.get('version', '')} | "
                f"{'yes' if item.get('used_in_run') else 'no'} |"
            )
    else:
        markdown_lines.append("- No prompt entries found in manifest.")
    markdown_lines.extend(
        [
            "",
            "## Stage Costs",
            "",
            "| Stage | Model | Tokens (In/Out) | Cost |",
            "|---|---|---|---|",
        ]
    )
    for stage_name, stage_content in stage_outputs.items():
        cost = stage_costs.get(stage_name, {})
        markdown_lines.append(
            f"| {stage_name} | {cost.get('model', '-')} | "
            f"{cost.get('input_tokens', 0)} / {cost.get('output_tokens', 0)} | "
            f"${float(cost.get('total_cost', 0.0)):.6f} |"
        )
        markdown_lines.extend(
            [
                "",
                f"## Stage: {stage_name}",
                "",
                "```json",
                _safe_json(stage_content),
                "```",
            ]
        )
    markdown_lines.extend(
        [
            "",
            "## Final Brief",
            "",
            report_json["final_brief_markdown"] or "_No final brief generated._",
        ]
    )

    report_markdown = "\n".join(markdown_lines).strip() + "\n"
    file_stub = f"{country.lower()}_{req.kpi_id}_{run_id[:8]}"
    return {
        "report_markdown": report_markdown,
        "report_filename": f"macrobrief_lab_report_{file_stub}.md",
        "report_json_filename": f"macrobrief_lab_report_{file_stub}.json",
        "report_json": report_json,
    }


def run_pipeline(req: LabGenerateRequest) -> Iterator[str]:
    """Run all workflow steps and stream NDJSON updates."""
    try:
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        stage_costs: dict[str, dict[str, Any]] = {}
        stage_outputs: dict[str, Any] = {}

        if req.start_year >= req.end_year:
            raise ValueError("start_year must be less than end_year.")

        country = req.country.upper()
        kpi_name = _kpi_name(req.kpi_id)
        timerange = f"{req.start_year}-{req.end_year}"
        generation_mode = req.generation_mode
        reasoning_model = (req.reasoning_model or REASONING_MODEL).strip() or REASONING_MODEL
        brief_model = (req.brief_model or BRIEF_MODEL).strip() or BRIEF_MODEL

        yield _event("status", content="Fetching KPI data...", meta={"run_id": run_id})
        kpi_result = fetch_single_kpi(
            countries=[country],
            kpi_id=req.kpi_id,
            frequency="A",
            timerange_a=timerange,
            timerange_q=timerange,
        )
        kpi_payload = _kpi_payload(kpi_result)
        data_fetch_content = {
            "country": country,
            "kpi_id": req.kpi_id,
            "kpi_name": kpi_name,
            "series_count": len(kpi_payload.get("series", [])),
            "errors": kpi_payload.get("errors", []),
        }
        stage_outputs["data_fetch"] = data_fetch_content
        yield _event(
            "stage",
            stage="data_fetch",
            content=data_fetch_content,
            meta={"run_id": run_id, "cost": None},
        )

        yield _event("status", content="Running signal extraction...", meta={"run_id": run_id})
        signal_output = signal_extractor.run_step(
            kpi_payload,
            reasoning_model=reasoning_model,
        )
        signal_content, signal_cost = _split_call_meta(signal_output)
        stage_outputs["signal_extractor"] = signal_content
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
            reasoning_model=reasoning_model,
        )
        hypotheses_content, hypotheses_cost = _split_call_meta(hypotheses_output)
        stage_outputs["hypotheses_generator"] = hypotheses_content
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
        stage_outputs["news_researcher"] = news_content
        if news_cost:
            stage_costs["news_researcher"] = news_cost
        yield _event(
            "stage",
            stage="news_researcher",
            content=news_content,
            meta={"run_id": run_id, "cost": news_cost},
        )

        evaluator_content: dict[str, Any] = {}
        revised_insights_content: dict[str, Any] = {}
        if generation_mode == "deep":
            yield _event("status", content="Generating insights...", meta={"run_id": run_id})
            first_insights = insights_generator.run_step(
                country=country,
                kpi_name=kpi_name,
                selected_signals=signal_content.get("selected_signals", []),
                hypotheses=hypotheses_content.get("hypotheses", []),
                evidence_items=news_content.get("evidence_items", []),
                reasoning_model=reasoning_model,
            )
            first_insights_content, first_insights_cost = _split_call_meta(first_insights)
            stage_outputs["insights_generator_first_pass"] = first_insights_content
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
                reasoning_model=reasoning_model,
            )
            evaluator_content, evaluator_cost = _split_call_meta(evaluator_output)
            stage_outputs["evaluator"] = evaluator_content
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
                reasoning_model=reasoning_model,
            )
            revised_insights_content, revised_insights_cost = _split_call_meta(revised_insights)
            stage_outputs["insights_generator"] = revised_insights_content
            if revised_insights_cost:
                stage_costs["insights_generator"] = revised_insights_cost
            yield _event(
                "stage",
                stage="insights_generator",
                content=revised_insights_content,
                meta={"run_id": run_id, "cost": revised_insights_cost},
            )
        else:
            yield _event("status", content="Generating light executive summary...", meta={"run_id": run_id})
            light_insights = insights_generator.run_step(
                country=country,
                kpi_name=kpi_name,
                selected_signals=signal_content.get("selected_signals", []),
                hypotheses=hypotheses_content.get("hypotheses", []),
                evidence_items=news_content.get("evidence_items", []),
                generation_mode="light",
                reasoning_model=reasoning_model,
            )
            revised_insights_content, revised_insights_cost = _split_call_meta(light_insights)
            stage_outputs["insights_generator"] = revised_insights_content
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
            generation_mode=generation_mode,
            brief_model=brief_model,
        )
        brief_content, brief_cost = _split_call_meta(brief_output)
        stage_outputs["brief_writer"] = brief_content
        if brief_cost:
            stage_costs["brief_writer"] = brief_cost
        yield _event(
            "stage",
            stage="brief_writer",
            content=brief_content,
            meta={"run_id": run_id, "cost": brief_cost},
        )

        total_cost = sum(item.get("total_cost", 0.0) for item in stage_costs.values())
        finished_at = datetime.now(timezone.utc)
        final_report = _build_report_payload(
            run_id=run_id,
            req=req,
            country=country,
            kpi_name=kpi_name,
            stage_outputs=stage_outputs,
            stage_costs=stage_costs,
            total_cost=total_cost,
            started_at=started_at,
            finished_at=finished_at,
        )

        yield _event(
            "result",
            stage="pipeline",
            content={
                "run_id": run_id,
                "country": country,
                "kpi_id": req.kpi_id,
                "kpi_name": kpi_name,
                "generation_mode": generation_mode,
                "reasoning_model": reasoning_model,
                "brief_model": brief_model,
                "brief_markdown": brief_content.get("brief_markdown", ""),
                "stage_costs": stage_costs,
                "total_cost": total_cost,
                "full_report_markdown": final_report["report_markdown"],
                "full_report_filename": final_report["report_filename"],
                "full_report_json_filename": final_report["report_json_filename"],
                "full_report": final_report["report_json"],
            },
            meta={"run_id": run_id},
        )
        yield _event(
            "done",
            stage="pipeline",
            content={
                "ok": True,
                "run_id": run_id,
                "generation_mode": generation_mode,
                "reasoning_model": reasoning_model,
                "brief_model": brief_model,
                "stage_costs": stage_costs,
                "total_cost": total_cost,
            },
            meta={"run_id": run_id},
        )
    except Exception as exc:
        log.exception("Lab pipeline failed")
        yield _event("error", stage="pipeline", content={"message": str(exc)})
        yield _event("done", stage="pipeline", content={"ok": False})

