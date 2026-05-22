"""Unit tests for exhibit label sequencing in country briefs."""
from __future__ import annotations

from backend.country_brief import pipeline


def test_compute_exhibit_map_default_profile_matches_new_flat_order():
    """Default profile flat order: 2 → 12 → 11 → 7 → 13 → 4 → 6 → 14 → 8 → 5 → 9."""
    notable = ["2", "12", "11", "1", "7", "13", "4", "6", "14", "8", "5", "9"]
    exhibit_ids = pipeline._build_exhibit_kpi_ids(
        notable_kpi_ids=notable,
        is_gcc=True,
    )
    exhibit_map = pipeline._compute_exhibit_map(exhibit_ids)

    assert exhibit_map["2"] == "1A"
    assert exhibit_map["12"] == "1B"
    assert exhibit_map["11"] == "1C"
    # KPI 1 is excluded when KPI 11 is present (shared nominal sector indicators).
    assert "1" not in exhibit_map
    assert exhibit_map["7"] == "2A"
    assert exhibit_map["13"] == "3A"
    assert exhibit_map["4"] == "3B"
    assert exhibit_map["6"] == "4A"
    assert exhibit_map["14"] == "4B"
    assert exhibit_map["8"] == "5A"
    assert exhibit_map["5"] == "5B"
    assert exhibit_map["9"] == "5C"


def test_check_exhibit_label_sequence_flags_section_gaps():
    blocks = [
        {
            "type": "section",
            "title": "Growth & Economic Structure",
            "children": [
                {"type": "chart_ref", "kpi_id": "2", "exhibit_label": "1A"},
                {"type": "chart_ref", "kpi_id": "12", "exhibit_label": "1B"},
                {"type": "chart_ref", "kpi_id": "11", "exhibit_label": "1E"},
            ],
        },
        {
            "type": "section",
            "title": "External Position & Trade",
            "children": [
                {"type": "chart_ref", "kpi_id": "13", "exhibit_label": "3A"},
                {"type": "chart_ref", "kpi_id": "4", "exhibit_label": "3B"},
            ],
        },
    ]

    issues = pipeline._check_exhibit_label_sequence(blocks)
    assert issues
    assert any("Growth & Economic Structure" in issue for issue in issues)
