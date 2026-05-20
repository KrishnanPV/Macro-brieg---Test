"""Tests for executive-summary bullet nesting normalization and confidence stripping."""
from __future__ import annotations

from backend.country_brief.brief_writer import (
    _normalize_bullet_nesting,
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
