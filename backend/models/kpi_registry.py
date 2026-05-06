"""KPI specifications, insight lenses, and news query templates."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# KPI catalogue
# ---------------------------------------------------------------------------

@dataclass
class KpiSpec:
    id: str
    name: str
    source: str          # "oxford" | "imf"
    frequency: str       # "Q" | "A"
    indicators: list[str]
    timerange_env: str
    notes: str = ""


def _kpi_specs() -> list[KpiSpec]:
    return [
        KpiSpec("3", "GDP growth by economic activity", "oxford", "Q",
                ["GDP real, annual growth"],
                "EAP_TIMERANGE_Q",
                "Aggregate real GDP growth (y/y)."),
        KpiSpec("11", "GDP - Real (Sector Split)", "oxford", "Q",
                ["GDP, agriculture", "GDP, industry", "GDP, manufacturing", "GDP, services"],
                "EAP_TIMERANGE_Q",
                "Real GDP by 4 sectors: agriculture, industry, manufacturing, services."),
        KpiSpec("2", "GDP - Real (Oil vs Non-Oil)", "oxford", "Q",
                ["GDP, oil, real, LCU", "GDP, non-oil, real, LCU"],
                "EAP_TIMERANGE_Q",
                "Real GDP split: oil vs non-oil."),
        KpiSpec("1", "GDP - Nominal (Split by industry)", "oxford", "Q",
                ["GDP, agriculture", "GDP, industry", "GDP, manufacturing", "GDP, services"],
                "EAP_TIMERANGE_Q",
                "Sector GDP in LCU (current prices)."),
        KpiSpec("4", "FDI inflow & outflow", "oxford", "Q",
                ["Foreign direct investment, inward", "Foreign direct investment, outward"],
                "EAP_TIMERANGE_Q",
                "Dual-line time series."),
        KpiSpec("5", "Unemployment rate, %", "oxford", "A",
                ["Unemployment rate"],
                "EAP_TIMERANGE_A",
                "Annual."),
        KpiSpec("6", "Consumption, private, PPP exchange rate, real", "oxford", "A",
                ["Consumption, private, PPP exchange rate, real"],
                "EAP_TIMERANGE_A"),
        KpiSpec("7", "Inflation - Consumer price index", "oxford", "Q",
                ["Inflation, consumer price index - % year-on-year"],
                "EAP_TIMERANGE_Q",
                "YoY CPI inflation."),
        KpiSpec("8", "External debt, total, share of GDP", "oxford", "Q",
                ["External debt, total, share of GDP"],
                "EAP_TIMERANGE_Q"),
        KpiSpec("9", "Population, total", "oxford", "A",
                ["Population, total"],
                "EAP_TIMERANGE_A"),
        KpiSpec("10", "GDP contribution from GDP categories (expenditure / NEA)", "imf", "A",
                [], "EAP_TIMERANGE_A",
                "IMF NEA — not available via Oxford EAP."),
    ]


SPECS = _kpi_specs()
SPECS_BY_ID: dict[str, KpiSpec] = {s.id: s for s in SPECS}
_KPI_CATALOG_ORDER: dict[str, int] = {s.id: i for i, s in enumerate(SPECS)}


def sorted_kpi_ids(ids: list[str]) -> list[str]:
    """Catalog order (as listed in SPECS)."""
    return sorted(ids, key=lambda k: (_KPI_CATALOG_ORDER.get(k, len(SPECS)), k))


# ---------------------------------------------------------------------------
# Auxiliary indicators (not KPIs — used for overlays / enrichment)
# ---------------------------------------------------------------------------

# Oil price — available per-country in LCU (already converted by Oxford).
# Fetched using the target country code, not a global/world location.
OIL_PRICE_INDICATOR = "Oil price"
OIL_PRICE_FALLBACKS: list[str] = []


# ---------------------------------------------------------------------------
# Per-KPI Insight Lens Registry
# ---------------------------------------------------------------------------

@dataclass
class InsightLens:
    headline: str
    notability_cues: list[str]
    context_hooks: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    units_note: str = ""
    narrative_guidance: list[str] = field(default_factory=list)


INSIGHT_LENSES: dict[str, InsightLens] = {
    "1": InsightLens(
        headline="Nominal GDP by Sector",
        notability_cues=[
            "Sector-share shifts >3pp between periods signal structural change (diversification or concentration).",
            "The composition data now includes pre-computed share percentages — use them directly.",
        ],
        context_hooks=[
            "National economic diversification programs (e.g. Saudi Vision 2030, UAE Economic Vision 2030, Qatar National Vision 2030).",
            "Sector-specific industrial policy, privatization drives, or mega-project spending (e.g. NEOM, tourism gigaprojects).",
            "Commodity price cycles and their pass-through to nominal GDP composition.",
        ],
        forbidden_claims=[
            "Do not infer real growth from nominal series — nominal changes can reflect price, not output.",
            "Do not compare absolute LCU values across countries with different currencies.",
            "Do not infer sector productivity from nominal output changes.",
        ],
        units_note="Local currency units at current prices (nominal). Synthesize sectors — do not bullet each one separately.",
        narrative_guidance=[
            "Synthesize agriculture, industry, and services into a single composition story; do not bullet each sector separately.",
            "This is a NOMINAL series — caveat that share changes can reflect price effects, not just real output shifts.",
            "Lead with which sector is largest and how its share moved, then explain the driver.",
        ],
    ),
    "2": InsightLens(
        headline="Real GDP by Industry (Oil vs Non-Oil)",
        notability_cues=[
            "Oil-vs-non-oil growth divergence — non-oil growing faster is a diversification signal.",
            "Sharp drops in oil GDP (volume) suggesting production cuts or demand shocks.",
            "Growth gap data is pre-computed — use it to quantify the divergence directly.",
        ],
        context_hooks=[
            "OPEC+ production agreements, voluntary production cuts, and quota compliance.",
            "Economic diversification milestones and non-oil sector reform programs.",
            "Global energy transition pressures and their impact on hydrocarbon-dependent economies.",
        ],
        forbidden_claims=[
            "Do not attribute oil GDP changes to price — this is a real (volume) series.",
            "Do not claim diversification from a single quarter of non-oil growth.",
            "Do not reference oil prices as a driver of oil real GDP — production volume is the mechanism.",
        ],
        units_note="Real LCU (constant prices). Report the oil/non-oil split only.",
        narrative_guidance=[
            "Lead with the oil/non-oil divergence — state which is outpacing and by how much.",
            "Connect oil GDP volume to specific OPEC+ decisions. Frame non-oil as a structural story.",
            "This is the PRIMARY economic identity lens for oil-exporting economies.",
        ],
    ),
    "3": InsightLens(
        headline="Real GDP Growth (YoY)",
        notability_cues=[
            "Growth inflection points — sign changes or swings >2pp between periods.",
            "The period highlight signal identifies the single most significant movement — lead with it.",
            "Consecutive negative periods (recession) vs isolated dips.",
            "Only call out volatility when swings are sustained or material to the growth narrative.",
        ],
        context_hooks=[
            "Fiscal stimulus or austerity programs, government spending plans, and budget announcements.",
            "Monetary policy stance (central bank rate decisions, currency pegs, liquidity management).",
            "OPEC+ production decisions affecting oil-GDP volume for producer economies.",
            "Global demand shocks, trade disruptions, or pandemic recovery trajectories.",
            "When available, decompose growth using expenditure drivers (private consumption, fixed investment, exports, imports).",
        ],
        forbidden_claims=[
            "Do not describe quarter-on-quarter seasonally adjusted growth — data is year-on-year.",
            "Do not attribute growth to sectors unless sector data is in the payload.",
            "Do not call a smooth trend 'volatile' without clear oscillation in the observed period.",
            "Do not mix nominal price movements with real output decomposition; separate price context from real GDP volume movements.",
        ],
        units_note="Year-on-year %.",
        narrative_guidance=[
            "Use a top-down arc: headline growth trend -> decomposition into main drivers -> implications for the macro trajectory.",
            "Explicitly link growth to available drivers in the payload (KPI 2, KPI 11, and KPI 10 components when present).",
            "For oil-dependent economies, distinguish oil-volume-driven growth from broad-based non-oil expansion.",
            "Use supporting sub-points only when they directly substantiate a main growth claim.",
            "Apply volatility language only when movement is materially uneven; if trend is smooth, emphasize persistence instead.",
        ],
    ),
    "4": InsightLens(
        headline="FDI Inflow & Outflow",
        notability_cues=[
            "Net FDI position (inward minus outward) — pre-computed in net_flow data.",
            "Abrupt reversals or large swings in inward FDI between periods.",
            "FDI flows are inherently lumpy — distinguish trend from single-transaction noise.",
        ],
        context_hooks=[
            "Investment law reforms, foreign ownership liberalization, and special economic zone launches.",
            "Bilateral investment treaties, free trade agreements, and WTO/accession developments.",
            "Sovereign wealth fund deployment strategies (e.g. PIF, ADIA, QIA outward investment).",
            "Geopolitical risk events or sanctions affecting capital flow direction.",
        ],
        forbidden_claims=[
            "Do not conflate FDI with portfolio flows or remittances.",
            "Do not claim FDI causes GDP growth — causality is ambiguous.",
            "Do not confuse FDI stock with FDI flow.",
        ],
        narrative_guidance=[
            "Start with the descriptive trajectory of inflows and outflows across the period before interpreting.",
            "Connect FDI swings to specific policy reforms, zone launches, or geopolitical events.",
            "For SWF-active economies, note outward FDI as deliberate strategy, not capital flight.",
        ],
    ),
    "5": InsightLens(
        headline="Unemployment Rate",
        notability_cues=[
            "Cumulative change >2pp over the window — strong structural shift.",
            "Persistently high (>8%) or low (<3%) levels are notable even if the rate is stable.",
            "GCC-specific context: visa-based labor systems can mask true labor-market tightness.",
        ],
        context_hooks=[
            "Labor nationalization programs (e.g. Saudization/Nitaqat, Emiratisation, Omanisation).",
            "Labor law reforms, minimum wage changes, and gig/platform economy regulation.",
            "Expatriate levy or fee changes that affect workforce composition.",
            "Public sector hiring drives vs private sector employment targets.",
        ],
        forbidden_claims=[
            "Do not infer youth unemployment, underemployment, or participation from the aggregate rate.",
        ],
        units_note="Percentage (%).",
        narrative_guidance=[
            "Lead with the rate and its direction over the window — is the improvement structural or cyclical?",
            "Connect to consumption (KPI 6) through the income channel: falling unemployment → wage income → purchasing power.",
            "In visa-based labour markets, distinguish citizen unemployment from total workforce dynamics.",
        ],
    ),
    "6": InsightLens(
        headline="Private Consumption (Real PPP)",
        notability_cues=[
            "Consumption growth >5% signals consumer-driven expansion; sub-1% signals stagnation.",
            "Consumption growing faster than GDP implies rebalancing toward domestic demand.",
        ],
        context_hooks=[
            "Consumer subsidy reforms, fuel/electricity price adjustments, and VAT changes.",
            "Wage growth policies, citizen allowance programs, and cost-of-living support measures.",
            "Credit expansion or tightening by domestic banking sectors.",
            "Tourism and entertainment sector openings that boost domestic spending.",
        ],
        forbidden_claims=[
            "Do not infer per-capita consumption without population data from KPI 9 in the payload.",
            "This is annual frequency data — do not infer quarterly consumption patterns.",
        ],
        units_note="Real PPP-adjusted. Annual frequency.",
        narrative_guidance=[
            "Position consumption relative to GDP growth: is domestic demand leading or lagging?",
            "Name the transmission channel: credit, wages, subsidies, VAT.",
            "Test for consumption resilience through adverse GDP periods — this is a key structural signal.",
        ],
    ),
    "7": InsightLens(
        headline="CPI Inflation (YoY)",
        notability_cues=[
            "Trend direction: acceleration (>1pp rise period-over-period) vs disinflation vs deflation (only if negative).",
            "Inflation stability — low volatility in a high-growth environment is analytically notable.",
            "Breaching central-bank comfort zones (2% advanced, 3-5% emerging) and policy bias it implies.",
        ],
        context_hooks=[
            "Central bank rate decisions (including Fed-linked pegged-currency rate pass-through).",
            "Administered price reforms: subsidy removal, fuel/electricity price deregulation.",
            "VAT introduction, rate changes, or excise tax expansions.",
            "Global commodity price pass-through (food, energy) and supply chain disruptions.",
        ],
        forbidden_claims=[
            "Do not label 'deflation' unless YoY CPI is actually negative.",
            "Do not prescribe interest-rate actions — frame as directional bias only.",
            "Do not infer core, food, or housing inflation from the headline CPI series — only headline data is available.",
        ],
        units_note="Year-on-year %.",
        narrative_guidance=[
            "Lead with the inflation arc as a single thread — do not list CPI alongside other KPIs.",
            "Distinguish cost-push from demand-pull. Always mention the monetary regime (peg vs float).",
            "For pegged economies, explain the interest-rate pass-through from the anchor central bank.",
        ],
    ),
    "8": InsightLens(
        headline="External Debt (% GDP)",
        notability_cues=[
            "Interpret the level relative to the country's exchange rate regime, reserve position, and whether it is a financial center.",
            "Rapid increases (>5pp/year) — distinguish borrowing-driven from GDP-contraction-driven.",
        ],
        context_hooks=[
            "Sovereign bond issuances (Eurobonds, sukuk) and their stated purpose.",
            "IMF program agreements, World Bank development financing, and credit rating actions.",
            "Fiscal consolidation plans, medium-term fiscal frameworks, and debt management strategies.",
            "Currency peg defense costs and reserve adequacy considerations.",
            "For financial center economies (UAE, Qatar), gross external debt reflects international financial intermediation, not sovereign stress.",
        ],
        forbidden_claims=[
            "Do not make definitive sustainability claims — depends on rates, currency, maturity, reserves.",
            "Do not conflate total external debt with government debt.",
        ],
        units_note="Percentage of GDP (%).",
        narrative_guidance=[
            "Decompose whether debt-ratio changes are borrowing-driven or GDP-denominator-driven.",
            "Connect to specific issuances (sukuk, Eurobonds) or fiscal programmes.",
            "Hedge sustainability claims: 'warrants monitoring,' 'consistent with' — no definitive verdicts.",
        ],
    ),
    "9": InsightLens(
        headline="Population",
        notability_cues=[
            "Growth rate >2% is high globally (immigration or high fertility); negative growth is always notable.",
            "Population growth rate relative to the country's own recent history signals structural demographic change.",
        ],
        context_hooks=[
            "Immigration policy changes: visa reforms, long-term residency programs (e.g. Golden Visa, Premium Residency).",
            "Expatriate levy or quota changes affecting migrant worker inflows/outflows.",
            "Mega-project construction booms driving temporary labor importation.",
            "Demographic policy and social reform programs (housing, family support).",
            "For aging economies: pension sustainability, healthcare costs, labor supply constraints.",
        ],
        forbidden_claims=[
            "Do not infer GDP per capita unless GDP data is in the payload.",
            "Do not infer age structure or urbanization from total population alone.",
        ],
        units_note="Express in millions to 2 dp or whole numbers. Annual.",
        narrative_guidance=[
            "Frame population as a structural indicator — it is a leading signal for domestic demand.",
            "Distinguish migration-driven growth from natural increase. Connect to labour supply and consumer base.",
            "For GCC economies, link population changes to specific visa/residency reforms and project labour demand.",
        ],
    ),
    "10": InsightLens(
        headline="IMF NEA",
        notability_cues=[
            "No data available — IMF NEA is not sourced via Oxford EAP.",
        ],
        context_hooks=[],
        forbidden_claims=[
            "Do not fabricate GDP expenditure components.",
            "Do not construct expenditure-side GDP narratives from fiscal news when NEA data is unavailable.",
        ],
        narrative_guidance=[
            "If expenditure-side data is unavailable, do not attempt to reconstruct it from other KPIs.",
        ],
    ),
    "11": InsightLens(
        headline="Real GDP by Sector",
        notability_cues=[
            "Sector-share shifts >3pp between periods signal structural change — use pre-computed composition data.",
            "Manufacturing growing faster than overall industry signals higher-value-added industrialization.",
        ],
        context_hooks=[
            "National economic diversification programs (e.g. Saudi Vision 2030, UAE Economic Vision 2030, Qatar National Vision 2030).",
            "Sector-specific industrial policy, privatization drives, or mega-project spending.",
            "Global commodity cycles and their pass-through to real sector output.",
        ],
        forbidden_claims=[
            "Do not compare absolute LCU values across countries with different currencies.",
            "Do not confuse this real (volume) series with the nominal sector split (KPI 1) — do not infer price effects.",
        ],
        units_note="Real LCU (constant prices). Synthesize sectors — do not bullet each one separately.",
        narrative_guidance=[
            "Lead with which sectors are gaining share and connect to named policy programmes.",
            "This is the REAL sector split — focus on output mix. Differentiate from KPI 1 (nominal).",
            "Synthesize sectors into a composition story. Do not bullet each sector separately.",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Country → currency mapping (ISO 4217)
# ---------------------------------------------------------------------------

ISO3_TO_CURRENCY: dict[str, str] = {
    "SAU": "SAR", "ARE": "AED", "QAT": "QAR", "KWT": "KWD",
    "BHR": "BHD", "OMN": "OMR", "USA": "USD", "GBR": "GBP",
    "DEU": "EUR", "FRA": "EUR", "JPN": "JPY", "CHN": "CNY",
    "IND": "INR", "BRA": "BRL", "EGY": "EGP", "ZAF": "ZAR",
    "NGA": "NGN", "TUR": "TRY", "IDN": "IDR", "MEX": "MXN",
}

CURRENCY_NAMES: dict[str, str] = {
    "SAR": "Saudi Riyal", "AED": "UAE Dirham", "QAR": "Qatari Riyal",
    "KWD": "Kuwaiti Dinar", "BHD": "Bahraini Dinar", "OMR": "Omani Rial",
    "USD": "US Dollar", "GBP": "British Pound", "EUR": "Euro",
    "JPY": "Japanese Yen", "CNY": "Chinese Yuan", "INR": "Indian Rupee",
    "BRL": "Brazilian Real", "EGP": "Egyptian Pound", "ZAR": "South African Rand",
    "NGN": "Nigerian Naira", "TRY": "Turkish Lira", "IDR": "Indonesian Rupiah",
    "MXN": "Mexican Peso",
}


def resolve_unit_label(raw_unit: str, country_iso3: str = "") -> str:
    """Turn Oxford's raw unit string into a concise, country-resolved label.

    Examples:
        'Riyal, Millions: 2023 prices' → 'SAR millions (2023 prices)'
        'US$, Millions'                → 'USD millions'
        '% year'                       → '% year'
        'Person, Thousands'            → 'thousands'
    """
    if not raw_unit:
        return ""

    text = raw_unit.strip()
    ccy = ISO3_TO_CURRENCY.get(country_iso3, "")

    # Currency-denominated units: 'Riyal, Millions: 2023 prices'
    _CURRENCY_WORDS = {
        "riyal": ccy or "LCU",
        "dirham": ccy or "LCU",
        "dinar": ccy or "LCU",
        "rial": ccy or "LCU",
        "pound": ccy or "LCU",
        "rupee": ccy or "LCU",
        "real": ccy or "LCU",
        "yuan": ccy or "LCU",
        "yen": ccy or "LCU",
        "naira": ccy or "LCU",
        "lira": ccy or "LCU",
        "rupiah": ccy or "LCU",
        "peso": ccy or "LCU",
        "rand": ccy or "LCU",
        "euro": ccy or "LCU",
    }

    lower = text.lower()

    # US$ → USD directly
    if lower.startswith("us$"):
        rest = text[3:].strip().lstrip(",").strip()
        parts = rest.split(":")
        scale_part = parts[0].strip().lower() if parts else ""
        qualifier = parts[1].strip() if len(parts) > 1 else ""
        label = f"USD {scale_part}" if scale_part else "USD"
        if qualifier:
            label += f" ({qualifier})"
        return label

    # Named currency (Riyal, Dirham, etc.)
    for word, code in _CURRENCY_WORDS.items():
        if word in lower:
            rest = text.split(",", 1)[1].strip() if "," in text else ""
            parts = rest.split(":")
            scale_part = parts[0].strip().lower() if parts else ""
            qualifier = parts[1].strip() if len(parts) > 1 else ""
            label = f"{code} {scale_part}" if scale_part else code
            if qualifier:
                label += f" ({qualifier})"
            return label

    # Percentages
    if lower.startswith("%"):
        return text

    # Person / headcount
    if "person" in lower:
        rest = text.split(",", 1)[1].strip().lower() if "," in text else ""
        return rest if rest else "persons"

    return text


# ---------------------------------------------------------------------------
# Country lookups
# ---------------------------------------------------------------------------

ISO3_TO_ISO2: dict[str, str] = {
    "SAU": "SA", "ARE": "AE", "QAT": "QA", "KWT": "KW",
    "BHR": "BH", "OMN": "OM", "USA": "US", "GBR": "GB",
    "DEU": "DE", "FRA": "FR", "JPN": "JP", "CHN": "CN",
    "IND": "IN", "BRA": "BR", "EGY": "EG", "ZAF": "ZA",
    "NGA": "NG", "TUR": "TR", "IDN": "ID", "MEX": "MX",
}

ISO3_TO_NAME: dict[str, str] = {
    "SAU": "Saudi Arabia", "ARE": "United Arab Emirates", "QAT": "Qatar",
    "KWT": "Kuwait", "BHR": "Bahrain", "OMN": "Oman",
    "USA": "United States", "GBR": "United Kingdom", "DEU": "Germany",
    "FRA": "France", "JPN": "Japan", "CHN": "China",
    "IND": "India", "BRA": "Brazil", "EGY": "Egypt",
    "ZAF": "South Africa", "NGA": "Nigeria", "TUR": "Turkey",
    "IDN": "Indonesia", "MEX": "Mexico",
}

DEMONYMS: dict[str, list[str]] = {
    "SAU": ["saudi", "ksa"],
    "ARE": ["emirati", "uae", "dubai", "abu dhabi"],
    "QAT": ["qatari", "doha"],
    "KWT": ["kuwaiti"],
    "BHR": ["bahraini"],
    "OMN": ["omani"],
    "USA": ["american", "us", "u.s."],
    "GBR": ["british", "uk", "u.k."],
    "DEU": ["german"],
    "FRA": ["french"],
    "JPN": ["japanese"],
    "CHN": ["chinese"],
    "IND": ["indian"],
    "BRA": ["brazilian"],
    "EGY": ["egyptian"],
    "ZAF": ["south african"],
    "NGA": ["nigerian"],
    "TUR": ["turkish"],
    "IDN": ["indonesian"],
    "MEX": ["mexican"],
}


# ---------------------------------------------------------------------------
# Newscatcher query templates per KPI
# ---------------------------------------------------------------------------

@dataclass
class KpiNewsQuery:
    query_template: str
    themes: str
    signal_terms: list[str] = field(default_factory=list)


KPI_NEWS_QUERIES: dict[str, KpiNewsQuery] = {
    "1": KpiNewsQuery(
        query_template=(
            '(GDP OR "gross domestic product" OR econom* OR "economic output" '
            'OR industr* OR manufactur* OR services OR agriculture '
            'OR "private sector" OR "public sector" OR "sectoral composition" '
            'OR "value added" OR "economic activity" OR output OR production) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["GDP", "gross domestic product", "sector", "industry",
                       "manufacturing", "services", "agriculture", "output",
                       "value added", "economic activity", "production"],
    ),
    "2": KpiNewsQuery(
        query_template=(
            '(GDP OR "non-oil" OR "oil sector" OR "oil GDP" '
            'OR "economic diversification" OR diversif* OR OPEC '
            'OR "oil revenue" OR "oil production" OR petrochemical '
            'OR hydrocarbon OR "oil dependence" OR "energy sector" '
            'OR "non-oil growth" OR "private sector" OR "oil price" '
            'OR "crude oil" OR "Vision 2030") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["oil", "non-oil", "diversification", "OPEC",
                       "hydrocarbon", "petrochemical", "oil revenue",
                       "oil production", "crude", "energy sector"],
    ),
    "3": KpiNewsQuery(
        query_template=(
            '(GDP OR growth OR recession OR expansion OR contraction '
            'OR slowdown OR "economic growth" OR "GDP growth" '
            'OR "economic performance" OR "quarterly growth" '
            'OR "annual growth" OR recovery OR downturn '
            'OR "growth rate" OR "economic outlook" OR stagnation OR boom) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["GDP", "growth", "recession", "expansion",
                       "contraction", "recovery", "downturn", "stagnation",
                       "economic performance", "economic outlook"],
    ),
    "4": KpiNewsQuery(
        query_template=(
            '(FDI OR "foreign direct investment" OR "foreign investment" '
            'OR "capital flows" OR "capital inflows" OR "investment climate" '
            'OR "foreign ownership" OR "cross-border" OR invest* '
            'OR greenfield OR "mergers and acquisitions" OR "joint venture" '
            'OR "free zone" OR "special economic zone" OR privatiz* '
            'OR "sovereign wealth") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["FDI", "foreign direct investment", "capital flows",
                       "investment", "greenfield", "free zone",
                       "sovereign wealth", "privatization", "cross-border"],
    ),
    "5": KpiNewsQuery(
        query_template=(
            '(unemploy* OR "labor market" OR "labour market" '
            'OR "job creation" OR "job losses" OR workforce OR employment '
            'OR jobless OR hiring OR layoff* OR "labor reform" '
            'OR "labour reform" OR "labor force" OR "youth unemployment" '
            'OR wage OR nationalization OR Saudization OR Emiratization '
            'OR "labor participation") '
            'AND ({country})'
        ),
        themes="Economics,Politics,Business",
        signal_terms=["unemployment", "employment", "labor market",
                       "job creation", "workforce", "hiring", "layoff",
                       "wage", "labor reform", "Saudization", "Emiratization"],
    ),
    "6": KpiNewsQuery(
        query_template=(
            '(consumption OR "consumer spending" OR "household expenditure" '
            'OR "household spending" OR "retail sales" OR retail '
            'OR "purchasing power" OR "consumer confidence" '
            'OR "domestic demand" OR "consumer demand" '
            'OR "disposable income" OR "cost of living" OR spending '
            'OR "consumer sentiment" OR "private consumption" '
            'OR "household income") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business",
        signal_terms=["consumption", "consumer spending", "retail",
                       "household expenditure", "purchasing power",
                       "consumer confidence", "domestic demand",
                       "disposable income", "cost of living"],
    ),
    "7": KpiNewsQuery(
        query_template=(
            '(inflation OR CPI OR "consumer price" OR "price index" '
            'OR "central bank" OR "monetary policy" OR "interest rate" '
            'OR deflation OR disinflation OR "cost of living" '
            'OR "food prices" OR "energy prices" OR "price stability" '
            'OR "base rate" OR "repo rate" OR "price growth" '
            'OR inflationary OR stagflation) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["inflation", "CPI", "consumer price", "interest rate",
                       "monetary policy", "central bank", "deflation",
                       "cost of living", "price index", "stagflation"],
    ),
    "8": KpiNewsQuery(
        query_template=(
            '(debt OR "external debt" OR "sovereign debt" '
            'OR "government borrowing" OR "bond issuance" '
            'OR "credit rating" OR "fiscal deficit" OR "debt-to-GDP" '
            'OR "sovereign bond" OR "public debt" OR "national debt" '
            'OR borrowing OR "credit default" OR "debt sustainability" '
            'OR "fiscal consolidation" OR "debt restructuring" '
            'OR sukuk OR eurobond OR "budget deficit" OR "fiscal balance") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["debt", "sovereign debt", "bond", "credit rating",
                       "fiscal deficit", "debt-to-GDP", "borrowing",
                       "sukuk", "eurobond", "debt sustainability"],
    ),
    "9": KpiNewsQuery(
        query_template=(
            '(population OR demograph* OR census OR immigra* OR emigra* '
            'OR migra* OR "birth rate" OR "fertility rate" '
            'OR "workforce growth" OR "labor force growth" OR expatriat* '
            'OR "visa reform" OR residency OR "population growth" '
            'OR "population change" OR "population decline" OR aging '
            'OR urbanization OR "housing demand" OR nationalization '
            'OR citizen*) '
            'AND ({country})'
        ),
        themes="Economics,Politics,Business",
        signal_terms=["population", "demographic", "immigration", "census",
                       "migration", "birth rate", "fertility", "expatriate",
                       "visa reform", "urbanization", "workforce growth"],
    ),
    "10": KpiNewsQuery(
        query_template=(
            '("government expenditure" OR "government spending" '
            'OR "fiscal policy" OR "national accounts" OR "public spending" '
            'OR budget OR "fiscal balance" OR "public investment" '
            'OR "capital expenditure" OR "current expenditure" '
            'OR revenue OR "tax revenue" OR "fiscal stimulus" '
            'OR austerity OR subsid* OR "public finance" '
            'OR "budget deficit" OR "budget surplus") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["government expenditure", "fiscal policy", "budget",
                       "public spending", "tax revenue", "austerity",
                       "subsidy", "fiscal stimulus", "public finance"],
    ),
    "11": KpiNewsQuery(
        query_template=(
            '(GDP OR "gross domestic product" OR econom* OR "economic output" '
            'OR industr* OR manufactur* OR services OR agriculture '
            'OR "private sector" OR "public sector" OR "sectoral composition" '
            'OR "value added" OR "economic activity" OR output OR production) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["GDP", "gross domestic product", "sector", "industry",
                       "manufacturing", "services", "agriculture", "output",
                       "value added", "economic activity", "production"],
    ),
}
