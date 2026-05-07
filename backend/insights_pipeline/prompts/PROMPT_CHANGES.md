# Prompt Changes

Append-only log for lab prompt updates. Do not edit past entries; add a new entry for each change.

## 2026-05-03 - v0.1.0 baseline
- Initialized lab prompt bundle and manifest for the first lab pipeline scaffold.
- Added baseline system, style, KPI context, reasoning, and causal language prompt files.
- Set model profile metadata in `manifest.yaml` for reproducible prompt+model snapshots.

## [SB-001] 2026-05-04 - system_base.md (0.1.1)

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

## [SG-001] 2026-05-04 - style_guide.md (0.1.1)

**Change**
- Created initial style guide for macroeconomic briefs
- Enforced bullet + sub-bullet structure with one idea per bullet
- Added CXO-focused writing requirement (clarity and speed of understanding)
- Introduced "so what" / answer-first framing with allowance for movement-led structure
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

## [RP-001] 2026-05-04 - reasoning_playbook.md (0.1.1)

**Change**
- First test of reasoning_distillation workflow
- Created initial reasoning playbook based on IMF Article IV analysis patterns
- Defined core reasoning loop: signal -> driver -> mechanism -> impact -> offsets -> net effect -> risks -> implication
- Added rules for:
  - separating driver vs. mechanism
  - identifying transmission channels and second-round effects
  - handling offsets, buffers, and external vs. domestic factors
  - calibrating confidence based on evidence strength
- Introduced common reasoning patterns (terms-of-trade, financial conditions, buffers, reform upside, component decomposition)
- Added failure modes (e.g., false causality, ignoring offsets, lack of transmission logic)

**Reason**
- Encode structured, repeatable macroeconomic reasoning derived from IMF Article IV reports
- Improve analytical depth and reduce superficial or descriptive outputs

**Impact**
- Standardizes reasoning across pipeline steps
- Improves causal clarity, consistency, and robustness of insights

## [GDP-L2-001] 2026-05-05 - per_kpi_context.md (0.1.1), reasoning_playbook.md (0.1.2), style_guide.md (0.1.2)

**Change**
- Updated `per_kpi_context.md` to add top-down storyline guidance and KPI-3-specific decomposition instructions.
- Added explicit direction for GDP driver mapping using available splits (oil/non-oil, sector, expenditure when present).
- Added volatility gating (only mention volatility when materially supported) and real-vs-nominal discipline language.
- Updated `reasoning_playbook.md` with required top-down ordering for insight construction.
- Updated `style_guide.md` to require a bold lead sentence for each top-level bullet and tighter sub-bullet usage.

**Reason**
- Improve GDP L2 insight quality with explicit driver linkage and clearer narrative structure.
- Reduce descriptive or noisy commentary by enforcing meaningful volatility references only.
- Improve executive readability by making top-level claims clearer and evidence hierarchy more consistent.

**Impact**
- More consistent growth narratives: trend -> drivers -> implication.
- Better alignment between hypothesis generation and final brief writing style.
- Clearer bullet hierarchy with stronger claim-first structure.

## [EXEC-SUM-001] 2026-05-05 - system_base.md (0.1.2), style_guide.md (0.1.3)

**Change**
- Updated `style_guide.md` with explicit Executive Summary requirements:
  - 4-6 substantive bullets (beefier synthesis),
  - cross-KPI coverage,
  - each line starts with a bold lead phrase followed by the analytical point.
- Updated `system_base.md` to require Executive Summary synthesis across major KPI domains instead of a single-thread narrative.

**Reason**
- Improve Executive Summary usefulness for decision-makers by increasing breadth and depth in a compact format.
- Enforce consistent line structure for faster scanability.

**Impact**
- Executive summaries should be more comprehensive and better balanced across KPIs.
- Stronger, more consistent formatting with bold lead-in on every line.

## [SUB-BULLET-001] 2026-05-05 - style_guide.md (0.1.4)

**Change**
- Strengthened section-body guidance so non-executive sections default to parent bullet + 1-2 indented sub-bullets when supporting evidence exists.
- Clarified structure split: parent bullet carries the claim; sub-bullets carry evidence, mechanism, and implication.
- Kept flexibility for standalone claims where sub-bullets would be artificial.

**Reason**
- Restore sub-bullet presentation in the insights body after recent style tightening led to flatter bullet lists.
- Preserve readability while improving analytical hierarchy.

**Impact**
- More consistent nested bullet structure in body sections.
- Better separation of headline insight vs supporting proof/mechanism.

## [RP-002] 2026-05-06 - reasoning_playbook.md (0.1.3)

**Change**
- Failure modes to avoid additions:
  - Ignoring outlier effects; Example: Saudi 2022 GDP growth was a post-COVID rebound, so 2023–2026 should not be described as a “sharp decline” without broader macro context.
  - Forecasts treated as observed outcomes; Example: “Growth moderated again in 2026” where 2026 data is forecasted.
  - Agent doesn't seem to be able to connect 'services-led reallocation' with 'non-oil growth', even though services is wholly non-oil.

**Reason**
- Comments and suggestions provided before report sent out for review.

**Impact**
- Examples seem to have been understood better.
- Need to consider if the point on forecasts is actually being reflected since perplexity search may pull 2026 data even when Oxford Economics tags the data as forecasted.
- Can reword 3rd failure mode to start with a title