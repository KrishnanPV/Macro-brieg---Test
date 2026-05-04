"""Extract capped IMF report excerpts and annotate reasoning units."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from backend.lab.workflow.common import REASONING_MODEL, call_json_model

TARGET_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("executive_summary", ("executive summary",)),
    ("recent_developments", ("recent developments",)),
    ("outlook_and_risks", ("outlook and risks", "outlook", "risks")),
    ("staff_appraisal", ("staff appraisal",)),
    ("policy_discussions", ("policy discussions", "policy discussion")),
)
ANNOTATION_FIELDS = (
    "signal",
    "interpretation",
    "driver",
    "mechanism",
    "offsetting_factors",
    "risk",
    "implication",
    "confidence",
)
ALLOWED_CONFIDENCE = {"low", "medium", "high"}

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_RAW_DIR = BASE_DIR / "corpus" / "imf_article_iv" / "raw"
DEFAULT_EXCERPTS_DIR = BASE_DIR / "corpus" / "imf_article_iv" / "excerpts"
DEFAULT_ANNOTATIONS_PATH = BASE_DIR / "annotations" / "imf_reasoning_units_v1.jsonl"
DEFAULT_PROMPT_PATH = BASE_DIR / "prompts" / "annotation_prompt_v1.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract IMF Article IV excerpts and annotate reasoning units."
    )
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--excerpts-dir", type=Path, default=DEFAULT_EXCERPTS_DIR)
    parser.add_argument("--annotations-path", type=Path, default=DEFAULT_ANNOTATIONS_PATH)
    parser.add_argument("--annotation-prompt", type=Path, default=DEFAULT_PROMPT_PATH)
    parser.add_argument("--report-limit", type=int, default=None)
    parser.add_argument("--excerpt-limit", type=int, default=None)
    parser.add_argument("--max-pages-per-report", type=int, default=35)
    parser.add_argument("--max-excerpts-per-report", type=int, default=24)
    parser.add_argument("--max-paragraphs-per-section", type=int, default=8)
    parser.add_argument("--min-paragraph-chars", type=int, default=220)
    parser.add_argument("--max-excerpt-chars", type=int, default=1200)
    parser.add_argument("--overwrite-excerpts", action="store_true")
    parser.add_argument("--overwrite-annotations", action="store_true")
    parser.add_argument("--append-annotations", action="store_true")
    parser.add_argument("--extract-only", action="store_true")
    return parser.parse_args()


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return cleaned or "item"


def _normalize_line(line: str) -> str:
    collapsed = re.sub(r"\s+", " ", line).strip().lower()
    return re.sub(r"[^a-z0-9 ]", "", collapsed)


def _is_probable_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 90:
        return False
    letters = [ch for ch in stripped if ch.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(ch.isupper() for ch in letters) / len(letters)
    title_like = bool(re.match(r"^[A-Z][A-Za-z0-9 ,:&\-]+$", stripped))
    return uppercase_ratio > 0.85 or title_like


def _match_target_heading(line: str) -> str | None:
    normalized = _normalize_line(line)
    if not normalized:
        return None
    for section_name, aliases in TARGET_SECTIONS:
        if any(alias in normalized for alias in aliases):
            return section_name
    return None


def _read_pdf_pages(pdf_path: Path, max_pages: int) -> list[tuple[int, str]]:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "Missing dependency 'pypdf'. Install requirements or run: pip install pypdf"
        ) from exc
    reader = PdfReader(str(pdf_path))
    pages: list[tuple[int, str]] = []
    for page_idx, page in enumerate(reader.pages[:max_pages], start=1):
        text = page.extract_text() or ""
        pages.append((page_idx, text))
    return pages


def _extract_section_buffers(pages: list[tuple[int, str]]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {name: [] for name, _ in TARGET_SECTIONS}
    current_section: str | None = None
    for _, page_text in pages:
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                if current_section:
                    buckets[current_section].append("")
                continue
            matched = _match_target_heading(line)
            if matched:
                current_section = matched
                continue
            if _is_probable_heading(line):
                current_section = None
                continue
            if current_section:
                buckets[current_section].append(line)
    return buckets


def _split_paragraphs(
    text: str,
    *,
    min_chars: int,
    max_chars: int,
    max_items: int,
) -> list[str]:
    rough_chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", text) if chunk.strip()]
    if len(rough_chunks) <= 1:
        rough_chunks = [chunk.strip() for chunk in text.split("\n") if chunk.strip()]
    paragraphs: list[str] = []
    for chunk in rough_chunks:
        compact = re.sub(r"\s+", " ", chunk).strip()
        if len(compact) < min_chars:
            continue
        if len(compact) <= max_chars:
            paragraphs.append(compact)
            if len(paragraphs) >= max_items:
                break
            continue

        sentences = re.split(r"(?<=[.!?])\s+", compact)
        current = []
        current_len = 0
        for sentence in sentences:
            extra = len(sentence) + (1 if current else 0)
            if current and current_len + extra > max_chars:
                merged = " ".join(current).strip()
                if len(merged) >= min_chars:
                    paragraphs.append(merged)
                    if len(paragraphs) >= max_items:
                        break
                current = [sentence]
                current_len = len(sentence)
                continue
            current.append(sentence)
            current_len += extra
        if len(paragraphs) >= max_items:
            break
        merged = " ".join(current).strip()
        if merged and len(merged) >= min_chars and len(paragraphs) < max_items:
            paragraphs.append(merged)
        if len(paragraphs) >= max_items:
            break
    return paragraphs[:max_items]


def _collect_excerpts_for_report(
    pdf_path: Path,
    *,
    max_pages_per_report: int,
    max_excerpts_per_report: int,
    max_paragraphs_per_section: int,
    min_paragraph_chars: int,
    max_excerpt_chars: int,
) -> list[dict[str, str]]:
    pages = _read_pdf_pages(pdf_path, max_pages=max_pages_per_report)
    section_buffers = _extract_section_buffers(pages)
    report_slug = _slugify(pdf_path.stem)
    excerpts: list[dict[str, str]] = []
    for section_name, _aliases in TARGET_SECTIONS:
        section_text = "\n".join(section_buffers.get(section_name, []))
        if not section_text.strip():
            continue
        paragraphs = _split_paragraphs(
            section_text,
            min_chars=min_paragraph_chars,
            max_chars=max_excerpt_chars,
            max_items=max_paragraphs_per_section,
        )
        for section_idx, paragraph in enumerate(paragraphs, start=1):
            excerpt_id = f"{report_slug}_{section_name}_{section_idx:02d}"
            excerpts.append(
                {
                    "excerpt_id": excerpt_id,
                    "section": section_name,
                    "source_pdf": pdf_path.name,
                    "text": paragraph,
                }
            )
            if len(excerpts) >= max_excerpts_per_report:
                return excerpts
    return excerpts


def _write_excerpt_files(
    excerpts: list[dict[str, str]],
    *,
    excerpts_dir: Path,
    overwrite_excerpts: bool,
) -> None:
    excerpts_dir.mkdir(parents=True, exist_ok=True)
    existing_files = list(excerpts_dir.glob("*.txt"))
    if existing_files and not overwrite_excerpts:
        raise RuntimeError(
            f"{excerpts_dir} already contains excerpt files. "
            "Use --overwrite-excerpts to regenerate them."
        )
    if overwrite_excerpts:
        for existing in existing_files:
            existing.unlink()
    for item in excerpts:
        output_path = excerpts_dir / f"{item['excerpt_id']}.txt"
        output_path.write_text(item["text"].strip() + "\n", encoding="utf-8")
        item["excerpt_path"] = str(output_path)


def _load_prompt(prompt_path: Path) -> str:
    if not prompt_path.exists():
        raise FileNotFoundError(f"Annotation prompt not found: {prompt_path}")
    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt_text:
        raise ValueError(f"Annotation prompt is empty: {prompt_path}")
    return prompt_text


def _validate_annotation(annotation: dict[str, Any], *, excerpt_id: str) -> dict[str, Any]:
    if not isinstance(annotation, dict):
        raise ValueError(f"{excerpt_id}: annotation is not a JSON object.")
    missing = [key for key in ANNOTATION_FIELDS if key not in annotation]
    if missing:
        raise ValueError(f"{excerpt_id}: missing fields: {', '.join(missing)}")
    confidence = str(annotation.get("confidence")).strip().lower()
    if confidence not in ALLOWED_CONFIDENCE:
        raise ValueError(
            f"{excerpt_id}: confidence must be one of {sorted(ALLOWED_CONFIDENCE)}."
        )
    normalized: dict[str, Any] = {}
    for field in ANNOTATION_FIELDS:
        value = annotation.get(field)
        if value is None:
            normalized[field] = None
        elif isinstance(value, str):
            normalized[field] = value.strip()
        else:
            normalized[field] = str(value).strip()
    normalized["confidence"] = confidence
    return normalized


def _prepare_annotations_file(
    annotations_path: Path,
    *,
    overwrite: bool,
    append: bool,
) -> None:
    annotations_path.parent.mkdir(parents=True, exist_ok=True)
    exists = annotations_path.exists()
    non_empty = exists and bool(annotations_path.read_text(encoding="utf-8").strip())
    if overwrite:
        annotations_path.write_text("", encoding="utf-8")
        return
    if non_empty and not append:
        raise RuntimeError(
            f"{annotations_path} already has content. Use --overwrite-annotations "
            "to replace it or --append-annotations to append."
        )
    if not exists:
        annotations_path.write_text("", encoding="utf-8")


def _init_cost_totals() -> dict[str, float]:
    return {
        "input_tokens": 0.0,
        "output_tokens": 0.0,
        "input_cost": 0.0,
        "output_cost": 0.0,
        "total_cost": 0.0,
    }


def _accumulate_cost(totals: dict[str, float], call_meta: dict[str, Any] | None) -> None:
    if not call_meta:
        return
    for key in ("input_tokens", "output_tokens", "input_cost", "output_cost", "total_cost"):
        totals[key] += float(call_meta.get(key, 0.0) or 0.0)


def _annotate_excerpts(
    excerpts: list[dict[str, str]],
    *,
    system_prompt: str,
    annotations_path: Path,
    excerpt_limit: int | None,
) -> tuple[int, int, list[dict[str, str]], dict[str, float]]:
    attempted = 0
    written = 0
    failures: list[dict[str, str]] = []
    cost_totals = _init_cost_totals()
    with annotations_path.open("a", encoding="utf-8") as handle:
        for excerpt in excerpts:
            if excerpt_limit is not None and attempted >= excerpt_limit:
                break
            attempted += 1
            user_prompt = (
                f"Excerpt ID: {excerpt['excerpt_id']}\n"
                f"Section: {excerpt['section']}\n\n"
                f"Excerpt:\n{excerpt['text'].strip()}"
            )
            try:
                response, call_meta = call_json_model(
                    model=REASONING_MODEL,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    caller="lab.reasoning_distillation.annotation",
                    include_call_meta=True,
                )
                _accumulate_cost(cost_totals, call_meta)
                annotation = _validate_annotation(response, excerpt_id=excerpt["excerpt_id"])
            except Exception as exc:  # noqa: BLE001
                failures.append({"excerpt_id": excerpt["excerpt_id"], "error": str(exc)})
                print(
                    f"warning: annotation skipped for {excerpt['excerpt_id']}: {exc}",
                    file=sys.stderr,
                )
                continue
            row = {
                "excerpt_id": excerpt["excerpt_id"],
                "source_pdf": excerpt["source_pdf"],
                "section": excerpt["section"],
                "excerpt_path": excerpt.get("excerpt_path"),
                "excerpt_text": excerpt["text"],
                **annotation,
            }
            serialized = json.dumps(row, ensure_ascii=True)
            json.loads(serialized)  # Row-level parseability check.
            handle.write(serialized + "\n")
            written += 1
    return attempted, written, failures, cost_totals


def _list_raw_pdfs(raw_dir: Path, report_limit: int | None) -> list[Path]:
    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw PDF directory not found: {raw_dir}")
    pdfs = sorted(raw_dir.glob("*.pdf"))
    if report_limit is not None:
        pdfs = pdfs[:report_limit]
    if not pdfs:
        raise RuntimeError(f"No PDF files found in {raw_dir}")
    return pdfs


def main() -> int:
    args = _parse_args()
    prompt_text = _load_prompt(args.annotation_prompt)
    pdf_paths = _list_raw_pdfs(args.raw_dir, args.report_limit)

    all_excerpts: list[dict[str, str]] = []
    for pdf_path in pdf_paths:
        report_excerpts = _collect_excerpts_for_report(
            pdf_path,
            max_pages_per_report=args.max_pages_per_report,
            max_excerpts_per_report=args.max_excerpts_per_report,
            max_paragraphs_per_section=args.max_paragraphs_per_section,
            min_paragraph_chars=args.min_paragraph_chars,
            max_excerpt_chars=args.max_excerpt_chars,
        )
        if report_excerpts:
            all_excerpts.extend(report_excerpts)

    if not all_excerpts:
        raise RuntimeError(
            "No excerpts matched target sections/caps. "
            "Try increasing --max-pages-per-report or lowering --min-paragraph-chars."
        )

    _write_excerpt_files(
        all_excerpts,
        excerpts_dir=args.excerpts_dir,
        overwrite_excerpts=args.overwrite_excerpts,
    )

    if args.extract_only:
        print(f"Extracted {len(all_excerpts)} excerpts into {args.excerpts_dir}")
        print("Total LLM cost (annotation): $0.000000 (input_tokens=0, output_tokens=0)")
        return 0

    _prepare_annotations_file(
        args.annotations_path,
        overwrite=args.overwrite_annotations,
        append=args.append_annotations,
    )
    attempted, written, failures, cost_totals = _annotate_excerpts(
        all_excerpts,
        system_prompt=prompt_text,
        annotations_path=args.annotations_path,
        excerpt_limit=args.excerpt_limit,
    )
    print(f"Extracted excerpts: {len(all_excerpts)}")
    print(f"Annotation attempts: {attempted}")
    print(f"Annotation rows written: {written}")
    print(f"Annotation rows failed: {len(failures)}")
    print(f"Annotations file: {args.annotations_path}")
    print(
        "Total LLM cost (annotation): "
        f"${cost_totals['total_cost']:.6f} "
        f"(input_tokens={int(cost_totals['input_tokens'])}, "
        f"output_tokens={int(cost_totals['output_tokens'])})"
    )
    if failures:
        preview = failures[:5]
        for item in preview:
            print(f"- {item['excerpt_id']}: {item['error']}", file=sys.stderr)
        if len(failures) > len(preview):
            print(
                f"... and {len(failures) - len(preview)} more failed excerpts.",
                file=sys.stderr,
            )
    if attempted > 0 and written == 0:
        raise RuntimeError("All annotation attempts failed; no rows were written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"run_annotation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
