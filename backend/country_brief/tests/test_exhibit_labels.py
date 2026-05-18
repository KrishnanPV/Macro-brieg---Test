"""Unit tests for exhibit label sequencing in country briefs."""
from __future__ import annotations

from backend.country_brief import pipeline


def test_compute_exhibit_map_includes_gcc_oil_split_in_sequence():
    exhibit_ids = pipeline._build_exhibit_kpi_ids(
        notable_kpi_ids=["3", "2", "11", "1", "4", "8", "7", "5", "6", "9"],
        is_gcc=True,
    )
    exhibit_map = pipeline._compute_exhibit_map(exhibit_ids)

    assert exhibit_map["3"] == "1A"
    assert exhibit_map["2"] == "1B"
    assert exhibit_map["2-oil"] == "1C"
    assert exhibit_map["11"] == "1D"
    # KPI 1 is excluded when KPI 11 is present (combined Real/Nominal toggle)
    assert "1" not in exhibit_map
    assert exhibit_map["4"] == "2A"
    assert exhibit_map["8"] == "2B"
    assert exhibit_map["7"] == "3A"
    assert exhibit_map["5"] == "4A"
    assert exhibit_map["6"] == "4B"
    assert exhibit_map["9"] == "5A"


def test_check_exhibit_label_sequence_flags_section_gaps():
    blocks = [
        {
            "type": "section",
            "title": "Economic Performance & Growth",
            "children": [
                {"type": "chart_ref", "kpi_id": "3", "exhibit_label": "1A"},
                {"type": "chart_ref", "kpi_id": "2", "exhibit_label": "1B"},
                {"type": "chart_ref", "kpi_id": "2-oil", "exhibit_label": "1E"},
                {"type": "chart_ref", "kpi_id": "11", "exhibit_label": "1C"},
            ],
        },
        {
            "type": "section",
            "title": "Investment & External Position",
            "children": [
                {"type": "chart_ref", "kpi_id": "4", "exhibit_label": "2A"},
                {"type": "chart_ref", "kpi_id": "8", "exhibit_label": "2B"},
            ],
        },
    ]

    issues = pipeline._check_exhibit_label_sequence(blocks)
    assert issues
    assert any("Economic Performance & Growth" in issue for issue in issues)
