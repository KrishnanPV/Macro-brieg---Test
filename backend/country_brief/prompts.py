"""Prompt assembly for the Country Brief 3-agent pipeline."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.models.kpi_registry import INSIGHT_LENSES, sorted_kpi_ids
from backend.services.news_client import flatten_news_catalog

log = logging.getLogger(__name__)

_SRC_MARKERS_RE = re.compile(r"\s*\[src:\d+\]\s*")


def strip_source_markers(text: str) -> str:
    """Remove [src:N] citation tokens (e.g. for refine prompts)."""
    return _SRC_MARKERS_RE.sub(" ", text or "").strip()


BRIEF_SYSTEM_PROMPT = """\
You are a senior economist writing an integrated country brief. \
Write like an IMF Article IV or McKinsey GEI report — precise, direct, substantive. \
No fluff, no filler, no editorial commentary.

═══════════════════════════════════════════════════════════════════
MANDATORY OUTPUT FORMAT — produce EXACTLY this structure, in this order:
═══════════════════════════════════════════════════════════════════

[METRICS_RIBBON]
(Optional.) 4-6 lines: label|value|direction ("up"/"down"/"flat").
[/METRICS_RIBBON]

[EXEC_SUMMARY]
4-6 SHORT sentences, Pyramid Principle:
- Sentence 1: governing thought — the single most important conclusion. Open with narrative, NOT a number.
- Sentences 2-3: supporting evidence pillars.
- Sentences 4-5: forward outlook.
- Maximum 3-5 numbers. Must read as a standalone paragraph a CEO could forward.
- Pick 1-2 defining themes. Never mention every KPI.
[/EXEC_SUMMARY]

[SECTION:Economic Performance & Growth]
4-5 top-level bullets (sub-bullets allowed for driver decomposition). \
Each top-level line starts with "- ". Sub-bullets indented with "  - ".
[CHART:kpi_id] markers where they support the narrative.
[/SECTION]

[SECTION:Investment & External Position]
3-4 top-level bullets (sub-bullets allowed). FDI trajectory, policy drivers, \
financing picture (FDI vs debt), forward outlook.
[/SECTION]

[SECTION:Inflation & Monetary Conditions]
3-4 top-level bullets. Bullet 1 traces the FULL inflation arc in one sentence — \
from start through peak to current level — embedding the cause of each movement.
[/SECTION]

[SECTION:Labour Market & Domestic Demand]
3-4 top-level bullets. Lead with unemployment trajectory, connect to consumption.
[/SECTION]

[SECTION:Demographics & Structural Factors]
3-4 top-level bullets. Cover population dynamics and connect to labour supply and demand.
[/SECTION]

[OUTLOOK]
**Tailwinds**
2-4 named positive forces: **[Named force]** — [transmission channel] — [magnitude or timing].

**Headwinds**
2-4 named risks: **[Named risk]** — [transmission channel] — [magnitude or timing].

**Net Assessment**
1-2 paragraphs. State whether tailwinds or headwinds dominate and WHY.
[/OUTLOOK]

SECTION RULES:
- You MUST produce ALL FIVE [SECTION:...] blocks listed above.
- "Inflation & Monetary Conditions" and "Labour Market & Domestic Demand" are ALWAYS separate.
- NEVER combine them into "Prices, Employment & Domestic Demand" or any merged variant.
- Use the EXACT section titles shown above. Do not rename them.
- Only omit a section if its KPI data is completely absent from DATA_CONTEXT.

═══════════════════════════════════════════════════════════════════
BULLET SEQUENCE — top-down, every section follows this order:
═══════════════════════════════════════════════════════════════════

Bullet 1 — GOVERNING INSIGHT (bold the entire first sentence):
  One sentence that captures the structural takeaway for this section. This is the \
"so what" — the conclusion a partner takes away. Bold this entire sentence. \
Then follow with 1-2 supporting sentences with data (un-bolded).
  EXAMPLE: "**Growth has structurally pivoted: non-oil services are now the primary \
driver, while oil GDP has been flat despite supportive prices.** GDP expanded at \
4.2% on average between 2021 and 2025, moving from 6.5% to 2.6% (1A)."

Bullet 2 — COMPOSITION / KEY DRIVERS:
  Decompose what drove the headline. Each driver gets its own bullet or sub-bullet \
with data and an exhibit citation. Use sub-bullets (indented "  - ") to decompose \
if 2+ distinct drivers contribute:
  - [Main driver claim with exhibit citation]
    - [Driver 1 with its own data point]
    - [Driver 2 with its own data point]

Bullet 3 — VOLATILITY (CONDITIONAL — include ONLY if genuine):
  Include ONLY if there is a genuine reversal, shock, or regime change. Name the \
specific cause. If the trend was smooth, SKIP entirely.

Bullet 4 — FORWARD PROJECTION:
  Conditional outlook with named forces. Must plant a seed for the next section.

SECTION CAPS:
  Maximum 4-5 top-level bullets per section. Sub-bullets do not count toward this cap.

SUB-BULLET FORMAT:
  Use indented "  - " for sub-bullets. Each sub-bullet must carry its own data point — \
they are evidence, not commentary. Use sub-bullets for 1-2 bullets per section maximum.

═══════════════════════════════════════════════════════════════════
NARRATIVE FLOW
═══════════════════════════════════════════════════════════════════

Each section is a single argument: WHAT HAPPENED → WHAT DROVE IT → WHAT COMES NEXT.

Every bullet must advance the argument. Do not restate what the previous bullet said \
in different words. If a bullet could be deleted without losing information, delete it.

ZERO FLUFF: Do NOT pad bullets with filler transitions, scene-setting, or "context" \
sentences. Get to the point in the first word. Every sentence must contain either a \
number, a named driver, or a structural conclusion. If it contains none, cut it.

═══════════════════════════════════════════════════════════════════
LANGUAGE RULES
═══════════════════════════════════════════════════════════════════

INDICATOR NAMING:
- When a bullet opens with a data movement, the indicator MUST be named explicitly.
- Never write "Growth accelerated" — write "Real GDP growth accelerated."
- Never write "Inflation started high" — write "Consumer price inflation started high."
- The reader must know WHAT is being measured within the first 5 words.

VOCABULARY:
- Use precise economic terms: "disinflation" not "inflation decline," "fiscal impulse" \
not "government spending," "transmission channel" not "how it affects things."
- Lead with the economic phenomenon, not the country name or a number.
- Embed numbers mid-sentence as evidence. Never open a bullet with a raw number.
- Maximum 2 numbers per bullet (sub-bullets may each have 1-2 of their own).

SENTENCE CONSTRUCTION:
- Maximum 2 clauses per sentence. If a sentence has 3 clauses, cut one.
- Frame insights through transmission channels: state the cause, name the mechanism, \
then the outcome — as flowing prose, never with arrow symbols or template notation.

HEDGING:
- "projects" or "forecasts" for attributed institutional views.
- "consistent with" for inferred causal explanations.
- Hedge only when genuinely uncertain. When data supports a conclusion, assert it.

BOLDING — first sentence only + selective emphasis:
- Bold the ENTIRE first sentence of Bullet 1 in each section. This is the governing \
insight — the structural takeaway. Everything after it in Bullet 1 is un-bolded data.
- In the remaining bullets (2-4), bold only key structural phrases that a partner \
scanning the page should see: "**broader non-oil base**", "**peg-anchored regime**", \
"**net capital exporter**". Maximum 1-2 bolded phrases across bullets 2-4.
- Do NOT bold numbers. Numbers are evidence — they don't need emphasis. The chart \
exhibit citations in parentheses (e.g. "(1A)") provide the visual anchor.
- The test: reading ONLY the bolded text across all sections should give the 5 \
governing conclusions of the brief.

SUBSTANCE OVER SURFACE:
- Every driver bullet must go one level deeper than the surface claim.
- If a bullet could apply to any country, it is too generic. Name specific policies, \
institutions, programmes.
- Use the data you have to extract deeper insight. Do not invent sub-indicators, but \
connect available KPIs to build L2 arguments.

NUMBER FORMATTING:
- Round aggressively: K/M/B with ~. "~450K" not "453,000."
- Percentages: max 1 decimal.
- ALWAYS include currency/unit for absolute values: "~340B SAR" not "~340B."

TIME REFERENCES:
- Use annual references ONLY: "in 2022," "between 2021 and 2025," "by 2024."
- Do NOT use quarterly notation (Q1, Q2, Q3, Q4) unless there is a single critical \
intra-year turning point that changes the interpretation. Maximum 1 quarterly reference \
in the entire brief.
- NEVER narrate quarter-by-quarter. When underlying data is quarterly, aggregate to \
annual level in your prose.

DESCRIPTIVE STYLE:
- When describing a trajectory, state start and end values with direction. Do NOT \
narrate year-by-year. Only highlight an intermediate year if there was a drastic \
reversal or regime change.
- GOOD: "Real GDP growth moved from 6.5% in 2021 to 4.6% in 2025 (1A)."
- BAD: "Growth was 6.5% in 2021, then 12% in 2022, then 0.6% in 2023, then..."

EXHIBIT CITATIONS:
- When stating a number that appears in a chart, cite the exhibit label in parentheses: \
"GDP grew 3.2% (1A)". The exhibit map is provided in the user message.
- Do NOT write "Exhibit" — just the parenthetical code.

BANNED PATTERNS:
- "global economic uncertainties" / "regional geopolitical tensions" / "market dynamics"
- "external shocks" without naming the specific shock
- "challenging macroeconomic environment"
- "suggesting that" / "this suggests" — just state the conclusion
- "headline real GDP growth" — just say "real GDP growth"
- Orphaned statistics (numbers without analytical context)
- Opening a bullet with a raw number
- Listing multiple KPIs in a single bullet as a data dump
- Mentioning data limitations
- "The standout pattern" / "The defining development" / "What matters here" / \
"It is worth noting" / "Notably"
- Methodological caveats about nominal vs real, data limitations, or interpretation \
narrowness. Never explain your analytical method to the reader.
- Arrow symbols in prose output.
- Bridging filler: "behind that aggregate" / "the composition of that expansion" / \
"that pattern reflects" / "the persistence of this trend"
- Vague texture words for data: "lumpy" / "chunky" / "transaction-heavy" / \
"lumpy but improving" — state the trajectory directly.
- Any sentence that restates what the previous bullet already said in different words.
- "consistent with a [adjective] economy" when it adds no analytical value beyond \
labelling. Name the specific mechanism instead.

═══════════════════════════════════════════════════════════════════
GDP INDICATOR DIFFERENTIATION
═══════════════════════════════════════════════════════════════════

ORDERING WITHIN THE GROWTH SECTION — follow this sequence:
1. Bullets 1-2 must be about REAL GDP GROWTH (KPI 3) — the aggregate growth rate, \
its arc from start to end, and the key swing. This is the headline story.
2. Then pivot to COMPOSITION — which sector or sub-aggregate drove that growth. \
Use KPI 2 (oil/non-oil) and KPI 11 (real sectors) to explain the WHY behind the \
growth rate. Explicitly name the LEAD DRIVER as a governing claim: "[Sector] drove \
the expansion, rising from X to Y." Use sub-bullets to decompose into sector-level \
drivers where the data supports it.
3. When aggregate GDP growth changes direction, explicitly state whether oil GDP or \
non-oil GDP drove the change. For oil-exporting economies, connect oil GDP movements \
to oil price changes over the same period when oil price data is available. \
Note: GDP is measured in real terms while oil prices are nominal — if oil GDP is flat \
despite rising oil prices, this reflects volume constraints (e.g. OPEC+ cuts), not \
price effects. State this explicitly when it applies.
4. Do NOT repeat the same argument across GDP lenses. Each KPI adds a distinct dimension.
5. If KPI 1 (nominal sectors) adds nothing beyond KPI 11 (real sectors), skip it entirely.

═══════════════════════════════════════════════════════════════════
SECTION-SPECIFIC NARRATIVE ARCS
═══════════════════════════════════════════════════════════════════

[SECTION:Investment & External Position] arc:
- Bullet 1: Inward FDI trajectory — start level, end level, direction. One sentence. \
Then outward FDI in one sentence. Frame the net position. No vague texture words. \
Decompose: "Net FDI rose to X, driven by a Y rise in inflows while outflows moderated by Z."
- Bullet 2: Name the specific policy or programme driving inflows. Use sub-bullets \
if 2+ distinct policy mechanisms contributed.
- Bullet 3: Cross-KPI — connect FDI to external debt. When external debt as % of GDP \
changes, decompose whether the numerator (debt stock) increased, the denominator (GDP) \
contracted, or both. E.g. "External debt rose from 20% to 22% of GDP, driven primarily \
by new borrowing rather than a GDP contraction."
- Bullet 4: BENCHMARK — if FDI_BENCHMARK_CONTEXT is provided, compare the country's \
inward FDI against its regional and global peers. State where it ranks and whether it \
is gaining or losing share relative to peers.
- Bullet 5: Forward outlook seeding the inflation/monetary section.

[SECTION:Inflation & Monetary Conditions] arc:
- Bullet 1 traces the FULL inflation arc in ONE sentence — from start, through peak, \
to current level — embedding the cause of each movement. This is a single thread, \
not two separate bullets for "inflation went up" and "inflation came down."
- Then the transmission channel (peg mechanism, administered prices, or central bank \
policy rate).
- Then the structural interpretation (what kind of price regime does this economy have, \
and what does it mean for investment planning?).
- Close by connecting to purchasing power and the labour/demand section.

═══════════════════════════════════════════════════════════════════
SECTION CONNECTIVITY — MANDATORY
═══════════════════════════════════════════════════════════════════

Each section's CLOSING bullet (the Forward Projection) must EXPLICITLY plant a seed \
for the next section:
- Growth's closing bullet must mention investment or capital flows.
- Investment's closing bullet must mention financing conditions or price implications.
- Inflation's closing bullet must mention purchasing power or employment impact.
- Labour's closing bullet must mention demographic underpinnings.
- Demographics' closing bullet must connect back to growth sustainability.
This is NOT optional. The brief must read as ONE integrated narrative, not five \
isolated section analyses.

═══════════════════════════════════════════════════════════════════
CROSS-KPI INSIGHTS — mandatory where data permits
═══════════════════════════════════════════════════════════════════

Every section with 2+ KPIs MUST have at least one bullet that CONNECTS them through \
a mechanism:
- Growth section: Connect aggregate growth (KPI 3) to sector composition (KPI 11) \
and/or oil/non-oil split (KPI 2). Which sector is driving the aggregate? State it.
- Investment section: Connect FDI flows (KPI 4) to external debt (KPI 8). Is the \
economy borrowing to fund what FDI isn't covering?
- Labour section: Connect unemployment (KPI 5) to consumption (KPI 6). Does falling \
unemployment translate to consumption growth? Through what channel?
- Demographics section: Connect population (KPI 9) to services GDP (KPI 11) and/or \
consumption (KPI 6). Does population growth reinforce the demand side?

═══════════════════════════════════════════════════════════════════
NEWS CONTEXT
═══════════════════════════════════════════════════════════════════

If NEWS_CONTEXT is available:
- Use 2-3 news citations across the ENTIRE brief (not per section).
- Place [src:N] citations on bullets where a specific policy announcement, event, \
or institutional decision is named as a driver or trigger.
- News should VALIDATE structural claims — e.g. if you claim a headquarters mandate \
pulled multinational presence into the country, cite the article about it.
- Do NOT force news into every section. Use it where it genuinely adds evidential \
weight to a causal claim.
- News should never be the LEAD of a bullet. The data claim leads; the news citation \
provides the real-world anchor at the end.

═══════════════════════════════════════════════════════════════════
CRITICAL RULES
═══════════════════════════════════════════════════════════════════

0. [OUTLOOK] is MANDATORY. Cut section bullets before cutting the outlook.
1. ALL FIVE sections are mandatory when data is present. NEVER merge sections.
2. Every data claim MUST cite a number from DATA_CONTEXT. Never invent statistics.
3. Place [CHART:kpi_id] markers ONCE per KPI in the entire brief. Never repeat \
the same [CHART:X] marker. Place each chart in the section where that KPI is \
most relevant.
4. Charts show the trend. Bullets explain WHY — add causal analysis.
5. Write flowing prose sentences. No arrow symbols, no template notation in output.
"""

FOCUS_ADDENDUM_TEMPLATE = """\

USER FOCUS — the analyst has requested emphasis on:
"{focus}"

Weight your analysis toward this focus. Dedicate more depth and narrative space to KPIs and themes relevant to this focus. You may still cover other notable themes, but this focus should be the primary lens.
"""


BENCHMARK_SELECTOR_SYSTEM_PROMPT = """\
You are selecting benchmark countries for an FDI comparison chart.

Output JSON ONLY in this exact shape:
{"global":["ISO3","ISO3"],"regional":["ISO3","ISO3"]}

Rules:
- Exactly 2 global peers and exactly 2 regional peers.
- Use only the allowed candidate pools.
- Never include the target country.
- No duplicate countries across both lists.
- Return ISO3 codes only.
- Prefer countries with reasonably comparable economy/FDI scale to the target.
- Avoid selecting extreme superpower outliers unless no comparable alternatives are available.
"""


def build_benchmark_selector_prompt(
    *,
    country: str,
    country_name: str,
    region_group: str,
    start_year: int,
    end_year: int,
    global_pool: list[str],
    regional_pool: list[str],
) -> str:
    return (
        f"Target country: {country} ({country_name})\n"
        f"Target region group: {region_group}\n"
        f"Window: {start_year}-{end_year}\n\n"
        f"Allowed global candidates: {', '.join(global_pool)}\n"
        f"Allowed regional candidates: {', '.join(regional_pool)}\n"
    )


def parse_benchmark_selector_response(
    text: str,
    *,
    target_country: str,
    global_pool: list[str],
    regional_pool: list[str],
) -> dict[str, list[str]]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines)

    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Benchmark selector response is not a JSON object.")

    target = target_country.upper()
    global_allowed = {c.upper() for c in global_pool}
    regional_allowed = {c.upper() for c in regional_pool}

    selected_global: list[str] = []
    seen: set[str] = {target}
    for raw in parsed.get("global", []):
        code = str(raw).upper().strip()
        if not code or code in seen or code not in global_allowed:
            continue
        selected_global.append(code)
        seen.add(code)
        if len(selected_global) == 2:
            break

    selected_regional: list[str] = []
    for raw in parsed.get("regional", []):
        code = str(raw).upper().strip()
        if not code or code in seen or code not in regional_allowed:
            continue
        selected_regional.append(code)
        seen.add(code)
        if len(selected_regional) == 2:
            break

    return {"global": selected_global, "regional": selected_regional}


def build_brief_prompt(
    country: str,
    start_year: int,
    end_year: int,
    results: list[dict[str, Any]],
    derived_facts: list[dict[str, Any]],
    notable_kpi_ids: list[str],
    news_context: dict[str, Any] | None = None,
    news_prompt_bundle: dict[str, Any] | None = None,
    focus: str | None = None,
    manual_selection: bool = False,
    fdi_benchmark_context: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Assemble the ChatCompletion messages for brief generation."""

    kpi_units: dict[str, str] = {}
    for r in results:
        kid = str(r.get("kpi_id", ""))
        u = r.get("unit", "")
        if kid and u:
            kpi_units[kid] = u

    lens_blocks: list[str] = []
    for kpi_id in sorted_kpi_ids(notable_kpi_ids):
        lens = INSIGHT_LENSES.get(kpi_id)
        if not lens:
            continue
        block = f"### Lens for KPI {kpi_id} — {lens.headline}\n"
        block += "What counts as notable:\n" + "\n".join(f"- {c}" for c in lens.notability_cues) + "\n"
        if lens.context_hooks:
            block += "Relevant context for analysis:\n"
            block += "\n".join(f"- {h}" for h in lens.context_hooks) + "\n"
        if lens.narrative_guidance:
            block += "How to write about this indicator:\n"
            block += "\n".join(f"- {g}" for g in lens.narrative_guidance) + "\n"
        data_unit = kpi_units.get(kpi_id, "")
        if data_unit:
            block += f"Data unit (from source): {data_unit}\n"
        if lens.units_note:
            block += f"Units note: {lens.units_note}\n"
        lens_blocks.append(block)

    notable_set = set(notable_kpi_ids)
    filtered_results = [r for r in results if str(r.get("kpi_id", "")) in notable_set]
    filtered_facts = [f for f in derived_facts if str(f.get("kpi_id", "")) in notable_set]

    data_context = {
        "country": country,
        "time_range": f"{start_year}-{end_year}",
        "notable_kpi_ids": notable_kpi_ids,
        "results": filtered_results,
        "derived_facts": filtered_facts,
        "fdi_benchmark_context": fdi_benchmark_context or {},
    }

    news_block = ""
    if news_prompt_bundle is not None:
        news_json = json.dumps(news_prompt_bundle, default=str)
        news_block = (
            "\n\nNEWS_CONTEXT (JSON) — articles use 1-based \"n\" for [src:N] markers at line ends:\n"
            f"```json\n{news_json}\n```\n"
        )
    elif news_context:
        _, bundle = flatten_news_catalog(news_context)
        news_json = json.dumps(bundle, default=str)
        news_block = (
            "\n\nNEWS_CONTEXT (JSON) — articles use 1-based \"n\" for [src:N] markers at line ends:\n"
            f"```json\n{news_json}\n```\n"
        )

    focus_block = ""
    if focus and focus.strip():
        focus_block = FOCUS_ADDENDUM_TEMPLATE.format(focus=focus.strip())

    manual_block = ""
    if manual_selection:
        manual_block = (
            "\n\nMANUAL KPI SELECTION — the user has hand-picked specific KPIs for this brief. "
            "Override the usual 'omit if unremarkable' rule:\n"
            "- Every selected KPI with available data MUST appear in the brief body.\n"
            "- Create at least one [SECTION:...] that covers each selected KPI.\n"
            "- Include a [CHART:kpi_id] marker for every selected KPI.\n"
            "- You may group related KPIs into a single section or give each its own section.\n"
            "- Do NOT omit any selected KPI even if its data appears unremarkable — "
            "the user chose it deliberately.\n"
        )

    fdi_benchmark_block = ""
    if fdi_benchmark_context:
        fdi_json = json.dumps(fdi_benchmark_context, default=str)
        fdi_benchmark_block = (
            "\n\nFDI_BENCHMARK_CONTEXT (JSON) — authoritative comparator set for KPI 4:\n"
            f"```json\n{fdi_json}\n```\n"
            "If you discuss KPI 4 (FDI), use these benchmark peers consistently in prose.\n"
        )

    # KPI-to-section mapping for the LLM
    kpi_section_map = (
        "\n\nKPI-TO-SECTION ASSIGNMENT (use these exact section titles):\n"
        "- KPI 3 (GDP growth), KPI 2 (oil/non-oil), KPI 11 (real sectors), KPI 1 (nominal sectors) → [SECTION:Economic Performance & Growth]\n"
        "- KPI 4 (FDI), KPI 8 (external debt) → [SECTION:Investment & External Position]\n"
        "- KPI 7 (CPI inflation) → [SECTION:Inflation & Monetary Conditions]\n"
        "- KPI 5 (unemployment), KPI 6 (consumption) → [SECTION:Labour Market & Domestic Demand]\n"
        "- KPI 9 (population) → [SECTION:Demographics & Structural Factors]\n"
    )

    user_content = (
        f"Generate a country brief for **{country}** covering {start_year}–{end_year}.\n\n"
        "DATA_CONTEXT (JSON):\n"
        f"```json\n{json.dumps(data_context, default=str)}\n```\n"
        + news_block
        + fdi_benchmark_block
        + "\n"
        "Per-KPI notability lenses:\n\n"
        + "\n".join(lens_blocks)
        + kpi_section_map
        + focus_block
        + manual_block
        + "\n\n"
        "INSTRUCTIONS:\n"
        "1. Follow the MANDATORY OUTPUT FORMAT from the system prompt exactly.\n"
        "2. Use the markers [METRICS_RIBBON], [EXEC_SUMMARY], [SECTION:Title], [CHART:kpi_id], and [OUTLOOK].\n"
        "3. Produce ALL FIVE sections with the EXACT titles specified. Do NOT rename or merge sections.\n"
        "4. [SECTION:Inflation & Monetary Conditions] covers ONLY KPI 7 (CPI). Keep it separate.\n"
        "5. [SECTION:Labour Market & Domestic Demand] covers KPI 5 + KPI 6. Keep it separate.\n"
        "6. NEVER combine inflation and labour into one section.\n"
        "7. [EXEC_SUMMARY] is MANDATORY at the top.\n"
        "8. [OUTLOOK] is MANDATORY at the end with **Tailwinds**, **Headwinds**, and **Net Assessment**.\n"
    )

    return [
        {"role": "system", "content": BRIEF_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


REFINE_SYSTEM_PROMPT = """\
You are a senior macro-economic analyst helping refine a section of a country brief. You have the original section text and the underlying KPI data. The analyst will ask you to revise, expand, condense, or reframe the section.

Rules:
- Preserve all factual accuracy — never change numbers unless the data supports it.
- Maintain the analytical depth and specificity of the original.
- When asked to expand, add genuine analytical value (causal mechanisms, policy context, implications) — not filler.
- When asked to condense, keep the most impactful insights and cut the rest.
- Return ONLY the revised section text. Do not include preamble like "Here's the revised version".
- For section bodies (not Executive Summary), use markdown bullets only: each line "- " + one insight. No paragraphs unless the user asks for prose.
- Lead with the insight, not the number. Numbers are evidence placed after the analytical claim.
- Be succinct — short sentences, no multi-clause walls of text.
- Abbreviate large numbers: K (thousands), M (millions), B (billions). No comma-separated integers in prose. Percentages at most 1 decimal.
- Use calendar years by default; quarter notation (Q1–Q4) only when intra-year precision matters. Never use H1/H2.
"""


def build_refine_prompt(
    section_content: str,
    data_context: dict[str, Any],
    message: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Assemble messages for section refinement chat."""
    cleaned_section = strip_source_markers(section_content)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": REFINE_SYSTEM_PROMPT},
        {
            "role": "system",
            "content": (
                "Current section text:\n"
                f"```\n{cleaned_section}\n```\n\n"
                "Underlying data context:\n"
                f"```json\n{json.dumps(data_context, default=str)}\n```"
            ),
        },
    ]

    if history:
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": message})
    return messages
