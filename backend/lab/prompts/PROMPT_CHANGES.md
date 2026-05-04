# Prompt Changes

Append-only log for lab prompt updates. Do not edit past entries; add a new entry for each change.

## 2026-05-03 - v0.1.0 baseline
- Initialized lab prompt bundle and manifest for the first lab pipeline scaffold.
- Added baseline system, style, KPI context, reasoning, and causal language prompt files.
- Set model profile metadata in `manifest.yaml` for reproducible prompt+model snapshots.

## [SB-001] 2026-05-04 — system_base.md (0.1.1)

**Change**
- First system prompt developed from scratch
- Added rules for:
  - significance of data movements
  - component-level analysis
  - long-period coverage and trend analysis
  - stronger causality discipline (drivers, mechanisms, transmission channels)

**Reason**
- Ensure outputs reflect IMF-style analysis: not just trends + news, but data significance and structured reasoning (no specific IMF guidance yet, though)

**Impact**
- Improves analytical depth and consistency across long time horizons.

## [SG-001] 2026-05-04 — style_guide.md (0.1.1)

**Change**
- Created initial style guide for macroeconomic briefs
- Enforced bullet + sub-bullet structure with one idea per bullet
- Added CXO-focused writing requirement (clarity and speed of understanding)
- Introduced “so what” / answer-first framing with allowance for movement-led structure
- Added rule to balance observation (data movement) with implication and analysis
- Enforced concise, non-redundant, no-filler writing
- Added comparative framing and precise directional language

**Reason**
- Ensure outputs are sharp, executive-ready, and analytically structured
- Align writing style with a hybrid of IMF analytical flow and consulting clarity
- Prevent descriptive or verbose outputs lacking clear implications

**Impact**
- Improves readability and decision-relevance of outputs
- Increases consistency in insight structure across the pipeline
- Reduces verbosity and redundancy