# Prompt Changes

Append-only log for lab prompt updates. Do not edit past entries; add a new entry for each change.

## 2026-05-03 - v0.1.0 baseline
- Initialized lab prompt bundle and manifest for the first lab pipeline scaffold.
- Added baseline system, style, KPI context, reasoning, and causal language prompt files.
- Set model profile metadata in `manifest.yaml` for reproducible prompt+model snapshots.

## [SB-002] 2026-05-04 — system_base.md (0.1.1)

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