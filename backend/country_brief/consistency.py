"""Numeric-consistency support for the country brief.

Two halves of WS3:

- ``build_canonical_figures`` / ``format_canonical_figures_block`` produce the
  authoritative latest-period headline values (the same set the metrics ribbon
  and charts render) so they can be injected into the brief-writer prompt. The
  model is told to quote these verbatim, which keeps the executive summary's
  headline numbers aligned with the ribbon and charts.

- ``audit_headline_consistency`` is a deterministic, warn-only safety net: it
  scans the generated prose for a headline rate KPI's latest-year value and
  flags any contradicting percentage. It never mutates the brief; it only
  returns human-readable warnings for logging.
"""
from __future__ import annotations

import re
from typing import Any

from backend.country_brief.metrics_ribbon import compute_ribbon_metrics

# Rate KPIs whose latest-period headline value we audit in prose. Levels (FDI,
# consumption) are abbreviated differently in prose vs ribbon, so auditing them
# textually is unreliable; we inject them as canonical figures but do not audit.
_AUDITED_PERCENT_KPIS: dict[str, tuple[str, ...]] = {
    "3": ("gdp growth", "real gdp", "headline growth"),
    "5": ("unemployment", "jobless"),
    "7": ("inflation", "cpi", "consumer price"),
    "8": ("external debt",),
}

_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+")
_AUDIT_TOLERANCE_PP = 0.3


def build_canonical_figures(derived_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the ribbon headline metrics — the single source of truth for headline values."""
    return compute_ribbon_metrics(derived_facts)


def format_canonical_figures_block(metrics: list[dict[str, Any]]) -> str:
    """Render the canonical figures as a compact prompt block."""
    lines: list[str] = []
    for m in metrics:
        label = m.get("label", "")
        value = m.get("value", "")
        if not label or not value:
            continue
        prior = m.get("prior_value")
        prior_label = m.get("prior_label")
        if prior and prior_label:
            lines.append(f"- {label}: {value} (prior {prior_label}: {prior})")
        else:
            lines.append(f"- {label}: {value}")
    if not lines:
        return ""
    return (
        "\n\nCANONICAL_FIGURES (authoritative) — these are the exact latest-period "
        "headline values shown in the metrics ribbon and charts. When you state any "
        "of these headline metrics in prose, use these exact numbers; never restate a "
        "headline metric with a different value:\n"
        + "\n".join(lines)
        + "\n"
    )


def _latest_year(metric: dict[str, Any]) -> str | None:
    label = metric.get("label", "")
    m = re.search(r"\((\d{4})\)", label)
    return m.group(1) if m else None


def _canonical_pct(metric: dict[str, Any]) -> float | None:
    raw = str(metric.get("value", ""))
    m = _PCT_RE.search(raw)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _collect_prose(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "executive_summary":
            parts.append(str(b.get("content", "")))
        elif t == "section":
            for child in b.get("children", []):
                if child.get("type") == "narrative":
                    parts.append(str(child.get("content", "")))
    return "\n".join(parts)


def audit_headline_consistency(
    blocks: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
) -> list[str]:
    """Flag prose that contradicts a headline rate KPI's latest-year value.

    Conservative by design: only fires when a sentence mentions the KPI keyword
    *and* its latest year *and* a percentage that differs from the canonical
    value by more than ``_AUDIT_TOLERANCE_PP``. Warn-only; returns messages.
    """
    prose = _collect_prose(blocks)
    if not prose:
        return []
    sentences = _SENTENCE_SPLIT_RE.split(prose)

    warnings: list[str] = []
    for metric in metrics:
        kid = str(metric.get("kpi_id", ""))
        keywords = _AUDITED_PERCENT_KPIS.get(kid)
        if not keywords:
            continue
        year = _latest_year(metric)
        canonical = _canonical_pct(metric)
        if year is None or canonical is None:
            continue

        for sentence in sentences:
            low = sentence.lower()
            if year not in sentence:
                continue
            if not any(kw in low for kw in keywords):
                continue
            for pm in _PCT_RE.finditer(sentence):
                try:
                    stated = float(pm.group(1))
                except ValueError:
                    continue
                if abs(stated - canonical) > _AUDIT_TOLERANCE_PP:
                    warnings.append(
                        f"{metric.get('label', kid)}: prose states {stated:g}% for "
                        f"{year} but canonical value is {canonical:g}%"
                    )
                    break

    # De-duplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return deduped
