"""Tests for executive-summary bullet nesting normalization and confidence stripping."""
from __future__ import annotations

from backend.country_brief.brief_writer import (
    _is_incomplete_brief,
    _normalize_bullet_nesting,
    _strip_chart_markers,
    _strip_confidence_tags,
    parse_brief_blocks,
)


def test_normalizes_flat_bullets_into_parent_and_children():
    raw = (
        "- **Oil-driven growth volatility masked steady diversification gains.** Real GDP fell.\n"
        "- Oil GDP declined from its 2022 peak before partially recovering.\n"
        "- External reporting directly links the 2024 slowdown to production restraint.\n"
        "- **Services-led non-oil expansion is structurally lifting the economic mix.** Services rose ~25%.\n"
        "- GASTAT reports non-oil activities above 53% of GDP by 2023.\n"
    )

    result = _normalize_bullet_nesting(raw)

    expected = (
        "- **Oil-driven growth volatility masked steady diversification gains.** Real GDP fell.\n"
        "  - Oil GDP declined from its 2022 peak before partially recovering.\n"
        "  - External reporting directly links the 2024 slowdown to production restraint.\n"
        "- **Services-led non-oil expansion is structurally lifting the economic mix.** Services rose ~25%.\n"
        "  - GASTAT reports non-oil activities above 53% of GDP by 2023."
    )
    assert result == expected


def test_renests_text_that_is_already_indented():
    raw = (
        "- **Parent A.** lead\n"
        "  - child a1\n"
        "- second child orphaned at top level\n"
        "- **Parent B.** lead\n"
        "  - child b1\n"
    )

    result = _normalize_bullet_nesting(raw)

    expected = (
        "- **Parent A.** lead\n"
        "  - child a1\n"
        "  - second child orphaned at top level\n"
        "- **Parent B.** lead\n"
        "  - child b1"
    )
    assert result == expected


def test_leaves_text_unchanged_when_all_bullets_are_bold():
    raw = (
        "- **Point A.** evidence\n"
        "- **Point B.** evidence\n"
    )
    assert _normalize_bullet_nesting(raw) == raw


def test_leaves_text_unchanged_when_no_bullets_are_bold():
    raw = "- plain a\n- plain b\n"
    assert _normalize_bullet_nesting(raw) == raw


def test_leaves_text_unchanged_when_no_bullets_present():
    raw = "Some narrative paragraph without bullets."
    assert _normalize_bullet_nesting(raw) == raw


def test_continuation_lines_are_attached_to_previous_bullet():
    raw = (
        "- **Parent.** opening claim\n"
        "  spanning a second physical line.\n"
        "- supporting evidence\n"
    )

    result = _normalize_bullet_nesting(raw)

    expected = (
        "- **Parent.** opening claim spanning a second physical line.\n"
        "  - supporting evidence"
    )
    assert result == expected


def test_strips_confidence_line_with_parenthetical_justification():
    raw = (
        "- supporting evidence one\n"
        "- **Confidence: High** (data + policy linkage).\n"
        "- supporting evidence two\n"
    )

    assert _strip_confidence_tags(raw) == (
        "- supporting evidence one\n"
        "- supporting evidence two\n"
    )


def test_strips_confidence_line_with_hyphenated_level():
    raw = (
        "- detail\n"
        "- **Confidence: Medium-High** (clear real share shift).\n"
    )

    assert _strip_confidence_tags(raw) == "- detail\n"


def test_strips_confidence_variants():
    cases = [
        "Confidence: Low",
        "**Confidence: Moderate**",
        "- confidence: Very High",
        "  - **Confidence: High-Medium** (mixed signals).",
        "* Confidence \u2013 High",
        "* Confidence \u2014 High",
    ]
    for line in cases:
        assert _strip_confidence_tags(line + "\n") == "", line
        assert _strip_confidence_tags(line) == "", line


def test_does_not_strip_legitimate_sentences_starting_with_confidence():
    raw = "Confidence in the recovery has improved as inflation cooled.\n"
    assert _strip_confidence_tags(raw) == raw


def test_parse_brief_blocks_drops_confidence_subbullets_end_to_end():
    raw = (
        "[EXEC_SUMMARY]\n"
        "- **Headline.** lead\n"
        "- supporting evidence\n"
        "- **Confidence: High** (data + policy linkage).\n"
        "[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\n"
        "- claim\n"
        "  - **Confidence: Medium-High** (clear shift).\n"
        "[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    exec_block = next(b for b in blocks if b["type"] == "executive_summary")
    section = next(b for b in blocks if b["type"] == "section")

    assert "Confidence" not in exec_block["content"]
    assert exec_block["content"] == (
        "- **Headline.** lead\n"
        "  - supporting evidence"
    )

    section_text = "\n".join(
        c.get("content", "") for c in section["children"] if c.get("type") == "narrative"
    )
    assert "Confidence" not in section_text


def test_parse_brief_blocks_normalizes_executive_summary():
    raw = (
        "[EXEC_SUMMARY]\n"
        "- **Headline one.** lead\n"
        "- supporting evidence one\n"
        "- **Headline two.** lead\n"
        "- supporting evidence two\n"
        "[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody\n[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    exec_block = next(b for b in blocks if b["type"] == "executive_summary")

    assert exec_block["content"] == (
        "- **Headline one.** lead\n"
        "  - supporting evidence one\n"
        "- **Headline two.** lead\n"
        "  - supporting evidence two"
    )


def test_strip_chart_markers_removes_single_marker():
    raw = "Real GDP grew 3.1% in 2024 [CHART:2] before slowing."
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Real GDP grew 3.1% in 2024" in cleaned
    assert "before slowing." in cleaned


def test_strip_chart_markers_removes_consecutive_markers():
    raw = "Inflation eased [CHART:6][CHART:13] across the period."
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Inflation eased" in cleaned
    assert "across the period." in cleaned


def test_strip_chart_markers_removes_kpi_prefixed_marker():
    raw = "Real growth slowed materially [CHART:kpi_12] but diversified."
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Real growth slowed materially" in cleaned
    assert "but diversified." in cleaned


def test_strip_chart_markers_removes_mixed_prefixed_and_bare_markers():
    raw = "Inflation eased [CHART:6][CHART:kpi_13] across the period."
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Inflation eased" in cleaned
    assert "across the period." in cleaned


def test_strip_chart_markers_removes_verbatim_placeholder():
    raw = "Population is expanding [CHART:kpi_id] which lifts demand."
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Population is expanding" in cleaned
    assert "which lifts demand." in cleaned


def test_strip_chart_markers_drops_bullet_that_was_only_a_placeholder():
    raw = (
        "- **Demand keeps rising.** Consumption stays firm.\n"
        "- [CHART:kpi_id]\n"
    )
    cleaned = _strip_chart_markers(raw)
    assert "[CHART:" not in cleaned
    assert "Demand keeps rising." in cleaned
    # The placeholder-only bullet must not leave a dangling empty bullet behind.
    assert not any(line.strip() in {"-", "*"} for line in cleaned.splitlines())


def test_strip_chart_markers_handles_empty_string():
    assert _strip_chart_markers("") == ""


def test_strip_chart_markers_collapses_excessive_blank_lines():
    raw = "line one\n\n\n\nline two"
    cleaned = _strip_chart_markers(raw)
    assert cleaned == "line one\n\nline two"


def test_parse_brief_blocks_strips_chart_markers_from_exec_summary():
    raw = (
        "[EXEC_SUMMARY]\n"
        "- **Growth slowed in 2024** as oil output fell [CHART:2].\n"
        "- Non-oil activity remained resilient [CHART:6][CHART:13].\n"
        "[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody\n[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    exec_block = next(b for b in blocks if b["type"] == "executive_summary")

    assert "[CHART:" not in exec_block["content"]
    assert "Growth slowed in 2024" in exec_block["content"]
    assert "Non-oil activity remained resilient" in exec_block["content"]


def test_parse_brief_blocks_converts_kpi_prefixed_section_marker_to_chart_ref():
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\n"
        "Real growth slowed materially [CHART:kpi_12] but diversified.\n"
        "[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    section = next(b for b in blocks if b["type"] == "section")
    chart_refs = [c for c in section["children"] if c.get("type") == "chart_ref"]

    assert len(chart_refs) == 1
    # The numeric id is captured without the kpi_ prefix so it matches the bare
    # numeric KPI ids used throughout the pipeline.
    assert chart_refs[0]["kpi_id"] == "12"
    narrative = " ".join(
        c["content"] for c in section["children"] if c.get("type") == "narrative"
    )
    assert "[CHART:" not in narrative


def test_parse_brief_blocks_drops_verbatim_placeholder_in_section():
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Labour Market & Domestic Demand]\n"
        "- **Population growth lifts demand.** Consumption stays firm.\n"
        "- [CHART:kpi_id]\n"
        "[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    section = next(b for b in blocks if b["type"] == "section")

    assert not any(c.get("type") == "chart_ref" for c in section["children"])
    narrative = " ".join(
        c["content"] for c in section["children"] if c.get("type") == "narrative"
    )
    assert "[CHART:" not in narrative
    assert "Population growth lifts demand." in narrative


def test_parse_brief_blocks_strips_chart_markers_from_outlook():
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody\n[/SECTION]\n"
        "[OUTLOOK]\n"
        "**Tailwinds**\n"
        "- Fiscal expansion continues [CHART:13][CHART:8][CHART:4].\n"
        "**Headwinds**\n"
        "- Oil price volatility persists [CHART:2].\n"
        "**Net Assessment**\n"
        "- Balanced.\n"
        "[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    outlook = next(b for b in blocks if b["type"] == "outlook")

    assert "[CHART:" not in outlook["content"]
    assert "Tailwinds" in outlook["content"]
    assert "Headwinds" in outlook["content"]


def test_parse_brief_blocks_strips_chart_markers_from_outlook_fallback():
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody\n[/SECTION]\n"
        "## Outlook\n"
        "**Tailwinds**\n"
        "- Diversification gains [CHART:2][CHART:11].\n"
        "**Headwinds**\n"
        "- External demand risk [CHART:6].\n"
        "**Net Assessment**\n"
        "- Cautiously positive.\n"
    )

    blocks = parse_brief_blocks(raw)
    outlook_blocks = [b for b in blocks if b["type"] == "outlook"]
    if outlook_blocks:
        assert "[CHART:" not in outlook_blocks[0]["content"]


# --- Truncation / unclosed-tag recovery -----------------------------------


def test_parse_brief_blocks_recovers_unclosed_final_section():
    # Truncated mid-stream: the last section opened but never closed.
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nfirst body\n[/SECTION]\n"
        "[SECTION:External Position]\npartial body before the stream was cut"
    )

    blocks = parse_brief_blocks(raw)
    sections = [b for b in blocks if b["type"] == "section"]
    titles = [s["title"] for s in sections]

    assert "External Position" in titles
    external = next(s for s in sections if s["title"] == "External Position")
    narrative = "\n".join(
        c.get("content", "") for c in external["children"] if c.get("type") == "narrative"
    )
    assert "partial body before the stream was cut" in narrative


def test_parse_brief_blocks_recovers_unclosed_outlook():
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody\n[/SECTION]\n"
        "[OUTLOOK]\n**Tailwinds**\n- momentum continues"
    )

    blocks = parse_brief_blocks(raw)
    outlook = next(b for b in blocks if b["type"] == "outlook")
    assert "Tailwinds" in outlook["content"]
    assert "momentum continues" in outlook["content"]


def test_parse_brief_blocks_unclosed_exec_does_not_swallow_section():
    # Exec opened without a close, followed by a real section: the tolerant
    # regex must stop exec at the next opening marker, not consume the section.
    raw = (
        "[EXEC_SUMMARY]\n- summary point\n"
        "[SECTION:Economic Performance & Growth]\nsection body\n[/SECTION]\n"
        "[OUTLOOK]o[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    exec_block = next(b for b in blocks if b["type"] == "executive_summary")
    section = next(b for b in blocks if b["type"] == "section")

    assert "summary point" in exec_block["content"]
    assert "[SECTION" not in exec_block["content"]
    assert section["title"] == "Economic Performance & Growth"


def test_parse_brief_blocks_wellformed_brief_unchanged_by_tolerant_regex():
    # A normal closed brief must parse exactly as before (no over-capture).
    raw = (
        "[EXEC_SUMMARY]\n- summary\n[/EXEC_SUMMARY]\n"
        "[SECTION:Economic Performance & Growth]\nbody one\n[/SECTION]\n"
        "[SECTION:External Position]\nbody two\n[/SECTION]\n"
        "[OUTLOOK]\n**Tailwinds**\n- x\n[/OUTLOOK]\n"
    )

    blocks = parse_brief_blocks(raw)
    sections = [b for b in blocks if b["type"] == "section"]
    assert [s["title"] for s in sections] == [
        "Economic Performance & Growth",
        "External Position",
    ]
    first = "\n".join(
        c.get("content", "") for c in sections[0]["children"] if c.get("type") == "narrative"
    )
    assert first == "body one"
    assert "body two" not in first


def test_is_incomplete_brief_detection():
    assert _is_incomplete_brief("") is True
    assert _is_incomplete_brief("   ") is True
    assert _is_incomplete_brief("[SECTION:X]\nbody with no close") is True
    assert _is_incomplete_brief("[EXEC_SUMMARY]\n- a") is True
    assert _is_incomplete_brief("[OUTLOOK]\n**Tailwinds**") is True
    assert _is_incomplete_brief(
        "[EXEC_SUMMARY]\n- a\n[/EXEC_SUMMARY]\n[OUTLOOK]\nx\n[/OUTLOOK]"
    ) is False
