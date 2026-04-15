"""
FastAPI backend for the Macro Brief KPI prototype.

All credentials (EAP, OpenAI) are read from .env — nothing is sent from the frontend.
"""
from __future__ import annotations

import difflib
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import requests as http_requests

import knoema
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="Macro Brief KPI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATASET = "thrmeac"
DEFAULT_HOST = (os.getenv("EAP_HOST") or "").strip()
DEFAULT_APP_ID = (os.getenv("EAP_APP_ID") or "").strip()
DEFAULT_APP_SECRET = (os.getenv("EAP_APP_SECRET") or "").strip()

NEWSCATCHER_API_KEY = (os.getenv("NEWSCATCHER_API_KEY") or "").strip()
NEWSCATCHER_URL = "https://v3-api.newscatcherapi.com/api/search"
NEWSCATCHER_TIMEOUT = 10

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


def _openai_client() -> OpenAI:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(500, "OPENAI_API_KEY is not configured on the server.")
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _openai_model() -> str:
    return (os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL


def _openai_temperature_kw(model: str) -> dict[str, float]:
    """GPT-5 chat models reject non-default temperature (only 1 is allowed); omit the param."""
    m = model.lower()
    if m.startswith("gpt-5"):
        return {}
    return {"temperature": 0.3}

# ---------------------------------------------------------------------------
# KPI catalogue (mirrors _default_specs from macro_kpi_extract.py)
# ---------------------------------------------------------------------------

@dataclass
class KpiSpec:
    id: str
    name: str
    source: str
    frequency: str
    indicators: list[str]
    timerange_env: str
    notes: str = ""


def _kpi_specs() -> list[KpiSpec]:
    return [
        KpiSpec("1", "GDP - Nominal (Split by industry)", "oxford", "Q",
                ["GDP, agriculture", "GDP, industry", "GDP, manufacturing", "GDP, services"],
                "EAP_TIMERANGE_Q",
                "Sector GDP in LCU (current prices)."),
        KpiSpec("2", "GDP - Real (Split by industry)", "oxford", "Q",
                ["GDP, oil, real, LCU", "GDP, non-oil, real, LCU", "GDP, manufacturing", "GDP, services"],
                "EAP_TIMERANGE_Q",
                "Real-side lens: oil vs non-oil plus manufacturing & services."),
        KpiSpec("3", "GDP growth by economic activity", "oxford", "Q",
                ["GDP real, annual growth"],
                "EAP_TIMERANGE_Q",
                "Aggregate real GDP growth (y/y)."),
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
SPECS_BY_ID = {s.id: s for s in SPECS}
_KPI_CATALOG_ORDER: dict[str, int] = {s.id: i for i, s in enumerate(SPECS)}


def _sorted_kpi_ids(ids: list[str]) -> list[str]:
    """Catalog order (1…10 as in SPECS), not selection or lexicographic order."""
    return sorted(
        ids,
        key=lambda k: (_KPI_CATALOG_ORDER.get(k, len(SPECS)), k),
    )


def _parse_timerange(tr: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Parse a 'YYYY-YYYY' range string into (start, end) timestamps."""
    parts = tr.split("-")
    start_year = int(parts[0])
    end_year = int(parts[1])
    return pd.Timestamp(f"{start_year}-01-01"), pd.Timestamp(f"{end_year}-12-31")


def _clip_points(
    points: list["SeriesPoint"], start: pd.Timestamp, end: pd.Timestamp,
) -> list["SeriesPoint"]:
    """Filter points to only those within [start, end]."""
    clipped = []
    for p in points:
        ts = pd.Timestamp(p.date)
        if start <= ts <= end:
            clipped.append(p)
    return clipped



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

INSIGHT_LENSES: dict[str, InsightLens] = {
    "1": InsightLens(
        headline="Nominal GDP by Sector",
        notability_cues=[
            "Sector-share shifts >5pp between periods signal structural change (diversification or concentration).",
            "Cross-country outliers where the dominant sector differs from regional norms.",
        ],
        context_hooks=[
            "National economic diversification programs (e.g. Saudi Vision 2030, UAE Economic Vision 2030, Qatar National Vision 2030).",
            "Sector-specific industrial policy, privatization drives, or mega-project spending (e.g. NEOM, tourism gigaprojects).",
            "Commodity price cycles and their pass-through to nominal GDP composition.",
        ],
        forbidden_claims=[
            "Do not infer real growth from nominal series — nominal changes can reflect price, not output.",
            "Do not compare absolute LCU values across countries with different currencies.",
        ],
        units_note="Local currency units at current prices (nominal). Synthesize sectors — do not bullet each one separately.",
    ),
    "2": InsightLens(
        headline="Real GDP by Industry (Oil vs Non-Oil)",
        notability_cues=[
            "Oil-vs-non-oil growth divergence — non-oil growing faster is a diversification signal.",
            "Sharp drops in oil GDP (volume) suggesting production cuts or demand shocks.",
        ],
        context_hooks=[
            "OPEC+ production agreements, voluntary production cuts, and quota compliance.",
            "Economic diversification milestones and non-oil sector reform programs.",
            "Global energy transition pressures and their impact on hydrocarbon-dependent economies.",
        ],
        forbidden_claims=[
            "Do not attribute oil GDP changes to price — this is a real (volume) series.",
            "Do not claim diversification from a single quarter of non-oil growth.",
        ],
        units_note="Real LCU (constant prices). Report the oil/non-oil split, not each sub-sector individually.",
    ),
    "3": InsightLens(
        headline="Real GDP Growth (YoY)",
        notability_cues=[
            "Growth inflection points — sign changes or swings >2pp between periods.",
            "Cross-country growth-rate spread: wide dispersion implies divergent cyclical positions.",
            "Consecutive negative quarters (technical recession) vs isolated dips.",
        ],
        context_hooks=[
            "Fiscal stimulus or austerity programs, government spending plans, and budget announcements.",
            "Monetary policy stance (central bank rate decisions, currency pegs, liquidity management).",
            "OPEC+ production decisions affecting oil-GDP volume for producer economies.",
            "Global demand shocks, trade disruptions, or pandemic recovery trajectories.",
        ],
        forbidden_claims=[
            "Do not describe quarter-on-quarter seasonally adjusted growth — data is year-on-year.",
            "Do not attribute growth to sectors unless sector data is in the payload.",
        ],
        units_note="Year-on-year %.",
    ),
    "4": InsightLens(
        headline="FDI Inflow & Outflow",
        notability_cues=[
            "Net FDI position (inward minus outward) and what it signals about capital-flow direction.",
            "Abrupt reversals or large swings in inward FDI between quarters.",
            "Order-of-magnitude differences in FDI scale across countries.",
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
        ],
    ),
    "5": InsightLens(
        headline="Unemployment Rate",
        notability_cues=[
            "Cumulative change >2pp over the window — strong structural shift.",
            "Rates near frictional floor (2-3%) vs elevated slack (>8%) and what each means.",
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
        ],
        units_note="Real PPP-adjusted. Annual frequency.",
    ),
    "7": InsightLens(
        headline="CPI Inflation (YoY)",
        notability_cues=[
            "Trend direction: acceleration (>1pp rise q/q) vs disinflation vs deflation (only if negative).",
            "Cross-country spread — large divergence implies different monetary/supply regimes.",
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
        ],
        units_note="Year-on-year %.",
    ),
    "8": InsightLens(
        headline="External Debt (% GDP)",
        notability_cues=[
            "Level thresholds: <30% manageable, 30-60% warrants monitoring, >60% sustainability concern.",
            "Rapid increases (>5pp/year) — distinguish borrowing-driven from GDP-contraction-driven.",
        ],
        context_hooks=[
            "Sovereign bond issuances (Eurobonds, sukuk) and their stated purpose.",
            "IMF program agreements, World Bank development financing, and credit rating actions.",
            "Fiscal consolidation plans, medium-term fiscal frameworks, and debt management strategies.",
            "Currency peg defense costs and reserve adequacy considerations.",
        ],
        forbidden_claims=[
            "Do not make definitive sustainability claims — depends on rates, currency, maturity, reserves.",
            "Do not conflate total external debt with government debt.",
        ],
        units_note="Percentage of GDP (%).",
    ),
    "9": InsightLens(
        headline="Population",
        notability_cues=[
            "Growth rate >2% is high globally (immigration or high fertility); <1% is demographic maturity.",
            "Large scale differences across countries and implications for market size and labor supply.",
        ],
        context_hooks=[
            "Immigration policy changes: visa reforms, long-term residency programs (e.g. Golden Visa, Premium Residency).",
            "Expatriate levy or quota changes affecting migrant worker inflows/outflows.",
            "Mega-project construction booms driving temporary labor importation.",
            "Demographic policy and social reform programs (housing, family support).",
        ],
        forbidden_claims=[
            "Do not infer GDP per capita unless GDP data is in the payload.",
            "Do not infer age structure or urbanization from total population alone.",
        ],
        units_note="Express in millions to 2 dp or whole numbers. Annual.",
    ),
    "10": InsightLens(
        headline="IMF NEA",
        notability_cues=[
            "No data available — IMF NEA is not sourced via Oxford EAP.",
        ],
        context_hooks=[],
        forbidden_claims=[
            "Do not fabricate GDP expenditure components.",
        ],
    ),
}


# ---------------------------------------------------------------------------
# Derived facts helper
# ---------------------------------------------------------------------------

def _compute_derived_facts(results: list[dict]) -> list[dict]:
    """Pre-compute summary statistics per series so the LLM can ground on them.

    Includes full-period analytics: CAGR, all period-over-period changes,
    inflection points (sign reversals & large movements), and trend segments
    so that insights cover the entire data window rather than just the tail.
    """
    facts: list[dict] = []
    for kpi_result in results:
        kpi_facts: dict[str, Any] = {
            "kpi_id": kpi_result["kpi_id"],
            "kpi_name": kpi_result["kpi_name"],
            "series_facts": [],
        }
        for s in kpi_result.get("series", []):
            vals = [(p["date"], p["value"]) for p in s["points"] if p["value"] is not None]
            if not vals:
                kpi_facts["series_facts"].append({
                    "country": s["country"],
                    "indicator": s["indicator"],
                    "note": "No non-null values.",
                })
                continue

            vals.sort(key=lambda x: x[0])
            latest_date, latest_val = vals[-1]
            earliest_date, earliest_val = vals[0]
            prior_date, prior_val = vals[-2] if len(vals) >= 2 else (None, None)
            all_vals = [v for _, v in vals]

            sf: dict[str, Any] = {
                "country": s["country"],
                "indicator": s["indicator"],
                "n_points": len(vals),
                "earliest": {"date": earliest_date, "value": earliest_val},
                "latest": {"date": latest_date, "value": latest_val},
                "min": {"value": min(all_vals), "date": vals[all_vals.index(min(all_vals))][0]},
                "max": {"value": max(all_vals), "date": vals[all_vals.index(max(all_vals))][0]},
            }
            if prior_val is not None:
                sf["prior"] = {"date": prior_date, "value": prior_val}
                if prior_val != 0:
                    sf["change_pct"] = round((latest_val - prior_val) / abs(prior_val) * 100, 2)

            # --- Full-period CAGR ---
            if len(vals) >= 2 and earliest_val and earliest_val > 0 and latest_val > 0:
                try:
                    t_start = pd.Timestamp(earliest_date)
                    t_end = pd.Timestamp(latest_date)
                    years = max((t_end - t_start).days / 365.25, 0.25)
                    cagr = ((latest_val / earliest_val) ** (1.0 / years) - 1) * 100
                    sf["cagr"] = {
                        "from": earliest_date,
                        "to": latest_date,
                        "years": round(years, 1),
                        "cagr_pct": round(cagr, 2),
                    }
                except Exception:
                    pass

            # --- Period-over-period changes (all consecutive pairs) ---
            if len(vals) >= 2:
                pop_changes: list[dict] = []
                for i in range(1, len(vals)):
                    d_prev, v_prev = vals[i - 1]
                    d_curr, v_curr = vals[i]
                    chg: dict[str, Any] = {
                        "from_date": d_prev,
                        "to_date": d_curr,
                        "from_value": v_prev,
                        "to_value": v_curr,
                        "absolute_change": round(v_curr - v_prev, 4),
                    }
                    if v_prev != 0:
                        chg["pct_change"] = round((v_curr - v_prev) / abs(v_prev) * 100, 2)
                    pop_changes.append(chg)
                sf["period_over_period"] = pop_changes

                # --- Inflection points (sign reversals & outsized moves) ---
                inflections: list[dict] = []
                pct_changes = [c.get("pct_change") for c in pop_changes if c.get("pct_change") is not None]
                if pct_changes:
                    mean_abs = sum(abs(p) for p in pct_changes) / len(pct_changes)
                    threshold = max(mean_abs * 1.5, 3.0)

                    for i, chg in enumerate(pop_changes):
                        pct = chg.get("pct_change")
                        if pct is None:
                            continue
                        reason = None
                        # Sign reversal
                        if i > 0:
                            prev_pct = pop_changes[i - 1].get("pct_change")
                            if prev_pct is not None and prev_pct * pct < 0 and abs(pct) > 2.0:
                                reason = "sign_reversal"
                        # Outsized move
                        if abs(pct) > threshold:
                            reason = reason or "outsized_move"
                        if reason:
                            inflections.append({
                                "date": chg["to_date"],
                                "value": chg["to_value"],
                                "pct_change": pct,
                                "reason": reason,
                            })
                if inflections:
                    sf["inflection_points"] = inflections

                # --- Trend segments (consecutive runs of same-sign change) ---
                segments: list[dict] = []
                seg_start_idx = 0
                for i in range(1, len(pop_changes)):
                    prev_pct = pop_changes[i - 1].get("pct_change")
                    curr_pct = pop_changes[i].get("pct_change")
                    if prev_pct is not None and curr_pct is not None and prev_pct * curr_pct < 0:
                        seg = pop_changes[seg_start_idx:i]
                        if len(seg) >= 2:
                            segments.append(_summarize_segment(seg, vals))
                        seg_start_idx = i
                final_seg = pop_changes[seg_start_idx:]
                if len(final_seg) >= 2:
                    segments.append(_summarize_segment(final_seg, vals))
                if segments:
                    sf["trend_segments"] = segments

            kpi_facts["series_facts"].append(sf)
        facts.append(kpi_facts)
    return facts


def _summarize_segment(
    seg: list[dict], vals: list[tuple[str, float]],
) -> dict[str, Any]:
    """Summarize a consecutive trend segment for derived_facts."""
    direction = "rising" if seg[0].get("pct_change", 0) > 0 else "falling"
    start_date = seg[0]["from_date"]
    end_date = seg[-1]["to_date"]
    start_val = seg[0]["from_value"]
    end_val = seg[-1]["to_value"]
    total_change = round(end_val - start_val, 4)
    total_pct = round((end_val - start_val) / abs(start_val) * 100, 2) if start_val != 0 else None
    return {
        "direction": direction,
        "from_date": start_date,
        "to_date": end_date,
        "from_value": start_val,
        "to_value": end_val,
        "periods": len(seg),
        "total_change": total_change,
        "total_pct_change": total_pct,
    }


# ---------------------------------------------------------------------------
# Newscatcher news integration — country/KPI mappings, cache, fetch, synthesis
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

@dataclass
class _KpiNewsQuery:
    """Holds the Newscatcher query template and theme filter for a KPI.

    The ``query_template`` contains a ``{country}`` placeholder that is
    resolved at call-time by joining the selected country names with OR.
    ``signal_terms`` are the most discriminating keywords for the KPI,
    used by the scoring pipeline to gauge semantic relevance.
    """
    query_template: str
    themes: str
    signal_terms: list[str] = field(default_factory=list)


KPI_NEWS_QUERIES: dict[str, _KpiNewsQuery] = {
    "1": _KpiNewsQuery(
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
    "2": _KpiNewsQuery(
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
    "3": _KpiNewsQuery(
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
    "4": _KpiNewsQuery(
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
    "5": _KpiNewsQuery(
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
    "6": _KpiNewsQuery(
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
    "7": _KpiNewsQuery(
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
    "8": _KpiNewsQuery(
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
    "9": _KpiNewsQuery(
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
    "10": _KpiNewsQuery(
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
}


class _NewsCache:
    """In-memory TTL cache for Newscatcher results (1 hour default)."""

    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._store: dict[tuple, tuple[float, list[dict]]] = {}

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, (ts, _) in self._store.items() if now - ts > self._ttl]
        for k in expired:
            del self._store[k]

    def get(self, key: tuple) -> list[dict] | None:
        self._evict()
        entry = self._store.get(key)
        if entry is None:
            return None
        return entry[1]

    def put(self, key: tuple, articles: list[dict]) -> None:
        self._evict()
        self._store[key] = (time.time(), articles)


_news_cache = _NewsCache()


def _find_notable_inflection(
    derived_facts: list[dict],
) -> tuple[str | None, str | None, str | None]:
    """Find the most significant data inflection across all series.

    Returns (inflection_date, from_date, to_date) where from/to define
    the 18-month asymmetric window (12mo back, 6mo forward).
    Returns (None, None, None) if no meaningful inflection is found.
    """
    best_date: str | None = None
    best_abs_change: float = 0.0

    for kpi_facts in derived_facts:
        for sf in kpi_facts.get("series_facts", []):
            change = sf.get("change_pct")
            if change is not None and abs(change) > best_abs_change:
                best_abs_change = abs(change)
                prior = sf.get("prior", {})
                best_date = prior.get("date") or sf.get("latest", {}).get("date")

    if not best_date:
        return None, None, None

    try:
        inflection_dt = pd.Timestamp(best_date).to_pydatetime()
    except Exception:
        return None, None, None

    window_start = inflection_dt - timedelta(days=365)
    window_end = inflection_dt + timedelta(days=183)

    trailing_boundary = datetime.utcnow() - timedelta(days=365)
    if inflection_dt >= trailing_boundary:
        return None, None, None

    return (
        best_date,
        window_start.strftime("%Y-%m-%d"),
        window_end.strftime("%Y-%m-%d"),
    )


def _resolve_country_placeholder(query_template: str, countries: list[str]) -> str:
    """Replace ``{country}`` in a query template with OR-joined country names."""
    country_names = []
    for c in countries:
        name = ISO3_TO_NAME.get(c)
        if name:
            country_names.append(f'"{name}"')
    if not country_names:
        return query_template.replace("AND ({country})", "").replace("({country})", "")
    country_clause = " OR ".join(country_names)
    return query_template.replace("{country}", country_clause)


NEWSCATCHER_DEFAULTS: dict[str, Any] = {
    "lang": "en",
    "search_in": "title_content",
    "include_translation_fields": False,
    "by_parse_date": False,
    "sort_by": "relevancy",
    "ranked_only": True,
    "from_rank": 1,
    "to_rank": 999999,
    "page": 1,
    "page_size": 100,
    "include_nlp_data": True,
    "has_nlp": True,
    "is_paid_content": False,
    "clustering_variable": "content",
    "clustering_threshold": 0.6,
}


def _call_newscatcher(
    query_template: str,
    countries: list[str],
    themes: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """Make a single POST to Newscatcher /api/search. Returns raw articles list."""
    if not NEWSCATCHER_API_KEY or NEWSCATCHER_API_KEY == "your_newscatcher_api_key_here":
        return []

    resolved_query = _resolve_country_placeholder(query_template, countries)

    try:
        _from = datetime.strptime(from_date, "%Y-%m-%d")
        _to = datetime.strptime(to_date, "%Y-%m-%d")
        crosses_year = _from.year != _to.year
    except ValueError:
        crosses_year = True

    payload: dict[str, Any] = {
        **NEWSCATCHER_DEFAULTS,
        "q": resolved_query,
        "from_": from_date,
        "to_": to_date,
    }

    if not crosses_year:
        payload["clustering_enabled"] = True
    else:
        payload["clustering_enabled"] = False

    if themes:
        payload["theme"] = themes

    headers = {
        "x-api-token": NEWSCATCHER_API_KEY,
        "Content-Type": "application/json",
    }

    log.info(
        "[NC-DEBUG] _call_newscatcher — q=%s, from=%s, to=%s, clustering=%s",
        resolved_query[:80], from_date, to_date,
        payload.get("clustering_enabled", False),
    )
    try:
        resp = http_requests.post(
            NEWSCATCHER_URL,
            headers=headers,
            json=payload,
            timeout=NEWSCATCHER_TIMEOUT,
        )
        if not resp.ok:
            log.warning(
                "[NC-DEBUG] Newscatcher API %s — response: %s",
                resp.status_code, resp.text[:500],
            )
            return []
        data = resp.json()

        total_hits = data.get("total_hits", 0)

        if "clusters" in data:
            articles = []
            for cluster in data.get("clusters", []):
                articles.extend(cluster.get("articles", []))
            log.info(
                "[NC-DEBUG] Response: %d total_hits, %d clusters, %d articles extracted",
                total_hits, len(data.get("clusters", [])), len(articles),
            )
            return articles

        articles = data.get("articles", [])
        log.info(
            "[NC-DEBUG] Response: %d total_hits, %d articles returned",
            total_hits, len(articles),
        )
        return articles
    except Exception as exc:
        log.warning("[NC-DEBUG] Newscatcher API call failed: %s", exc)
        return []


def _fetch_news_for_kpi(
    kpi_id: str,
    countries: list[str],
    derived_facts: list[dict],
) -> list[dict]:
    """Fetch news articles for a KPI using the two-window strategy with caching."""
    nq = KPI_NEWS_QUERIES.get(kpi_id)
    if not nq:
        log.info("[NC-DEBUG] _fetch_news_for_kpi: no query mapping for KPI '%s'", kpi_id)
        return []

    log.info(
        "[NC-DEBUG] _fetch_news_for_kpi: KPI=%s, countries=%s, query=%s",
        kpi_id, countries, nq.query_template[:60],
    )

    sorted_countries = tuple(sorted(countries))
    all_articles: list[dict] = []
    seen_ids: set[str] = set()

    def _add_unique(articles: list[dict]) -> None:
        for a in articles:
            aid = a.get("id", "")
            if aid and aid in seen_ids:
                continue
            if aid:
                seen_ids.add(aid)
            all_articles.append(a)

    today = datetime.now()
    trailing_from = (today - timedelta(days=365)).strftime("%Y-%m-%d")
    trailing_to = today.strftime("%Y-%m-%d")

    cache_key_trailing = (kpi_id, sorted_countries, "trailing")
    cached = _news_cache.get(cache_key_trailing)
    if cached is not None:
        log.info("[NC-DEBUG] Trailing window: cache HIT (%d articles)", len(cached))
        _add_unique(cached)
    else:
        log.info("[NC-DEBUG] Trailing window: cache MISS — calling API (from=%s to=%s)", trailing_from, trailing_to)
        trailing = _call_newscatcher(
            query_template=nq.query_template,
            countries=countries,
            themes=nq.themes,
            from_date=trailing_from,
            to_date=trailing_to,
        )
        _news_cache.put(cache_key_trailing, trailing)
        _add_unique(trailing)

    inflection_date, hist_from, hist_to = _find_notable_inflection(derived_facts)
    log.info("[NC-DEBUG] Inflection detection: date=%s, hist_from=%s, hist_to=%s", inflection_date, hist_from, hist_to)
    if hist_from and hist_to:
        window_label = f"historical_{inflection_date}"
        cache_key_hist = (kpi_id, sorted_countries, window_label)
        cached_hist = _news_cache.get(cache_key_hist)
        if cached_hist is not None:
            log.info("[NC-DEBUG] Historical window: cache HIT (%d articles)", len(cached_hist))
            _add_unique(cached_hist)
        else:
            log.info("[NC-DEBUG] Historical window: cache MISS — calling API")
            historical = _call_newscatcher(
                query_template=nq.query_template,
                countries=countries,
                themes=nq.themes,
                from_date=hist_from,
                to_date=hist_to,
            )
            _news_cache.put(cache_key_hist, historical)
            _add_unique(historical)

    log.info("[NC-DEBUG] _fetch_news_for_kpi: total unique articles = %d", len(all_articles))
    return all_articles


# ---------------------------------------------------------------------------
# Article scoring pipeline  [WIP — see ADR-001 OQ-2 for open weight questions]
# ---------------------------------------------------------------------------

_DEMONYMS: dict[str, list[str]] = {
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

_STAT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*%"
    r"|\$\s*\d"
    r"|\d+(?:\.\d+)?\s*(?:billion|million|trillion|bn|mn|tn)"
    r"|\d+(?:\.\d+)?\s*(?:bps|basis points|percentage points|pp)",
    re.IGNORECASE,
)

SCORING_WEIGHTS: dict[str, float] = {
    "country": 0.30,
    "semantic": 0.25,
    "source": 0.15,
    "recency": 0.15,
    "info_value": 0.15,
}

_ARTICLES_PER_COUNTRY = 10
_MIN_WORD_COUNT = 80
_DEDUP_SIMILARITY_THRESHOLD = 0.7
_RECENCY_LAMBDA = 0.005


def _score_country_relevance(
    article: dict,
    countries: list[str],
) -> tuple[float, str | None]:
    """Score how strongly the article relates to one of the target countries.

    Returns (score, matched_iso3).
    """
    title = (article.get("title") or "").lower()
    content = (article.get("content") or article.get("description") or "").lower()
    nlp = article.get("nlp") or {}
    loc_entities: list[str] = []
    if isinstance(nlp, dict):
        ner = nlp.get("ner", [])
        if isinstance(ner, list):
            loc_entities = [
                (e.get("entity_name") or "").lower()
                for e in ner
                if isinstance(e, dict) and e.get("label") == "LOC"
            ]

    best_score = 0.0
    best_country: str | None = None

    for iso3 in countries:
        name_lower = ISO3_TO_NAME.get(iso3, "").lower()
        if not name_lower:
            continue
        aliases = [name_lower] + _DEMONYMS.get(iso3, [])

        in_title = any(a in title for a in aliases)
        in_ner = any(
            any(a in loc for a in aliases)
            for loc in loc_entities
        )
        in_content = any(a in content for a in aliases)

        if in_title:
            score = 1.0
        elif in_ner:
            score = 0.7
        elif in_content:
            score = 0.5
        else:
            iso2 = ISO3_TO_ISO2.get(iso3, "")
            article_country = (article.get("country") or "").upper()
            score = 0.3 if article_country == iso2 else 0.0

        if score > best_score:
            best_score = score
            best_country = iso3

    return best_score, best_country


def _score_semantic_relevance(
    article: dict,
    signal_terms: list[str],
) -> float:
    """TF-IDF-like heuristic: fraction of signal terms found in the article.

    Title matches are weighted 2x.
    """
    if not signal_terms:
        return 0.5

    title = (article.get("title") or "").lower()
    content = (article.get("content") or article.get("description") or "").lower()

    hits = 0.0
    max_possible = len(signal_terms) * 2  # all found in title = 2x weight each

    for term in signal_terms:
        t = term.lower()
        if t in title:
            hits += 2.0
        elif t in content:
            hits += 1.0

    return min(hits / max_possible, 1.0) if max_possible > 0 else 0.0


def _score_source_quality(article: dict) -> float:
    """Log-scale mapping from Newscatcher source rank."""
    rank = article.get("rank")
    if rank is None or rank <= 0:
        return 0.3

    if rank <= 1_000:
        return 1.0
    elif rank <= 10_000:
        return 0.8
    elif rank <= 50_000:
        return 0.5
    else:
        return 0.3


def _score_recency(article: dict, anchor_date: str) -> float:
    """Exponential decay from the query window's end date."""
    pub_date = article.get("published_date") or ""
    if not pub_date or not anchor_date:
        return 0.2

    try:
        pub_dt = pd.Timestamp(pub_date)
        anchor_dt = pd.Timestamp(anchor_date)
        days_diff = abs((anchor_dt - pub_dt).days)
    except Exception:
        return 0.2

    return math.exp(-_RECENCY_LAMBDA * days_diff)


def _score_info_value(article: dict) -> float:
    """Composite information-value score based on multiple content signals."""
    score = 0.0
    nlp = article.get("nlp") or {}

    if isinstance(nlp, dict) and nlp.get("summary"):
        score += 0.2

    if isinstance(nlp, dict):
        ner = nlp.get("ner", [])
        if isinstance(ner, list) and len(ner) >= 3:
            score += 0.3

    if isinstance(nlp, dict):
        sent_obj = nlp.get("sentiment") or {}
        if isinstance(sent_obj, dict):
            content_sent = sent_obj.get("content")
            if content_sent is not None and content_sent != 0.0:
                score += 0.1

    text = (article.get("content") or article.get("description") or "")
    if _STAT_PATTERN.search(text):
        score += 0.2

    return min(score, 1.0)


def _compute_article_score(
    article: dict,
    countries: list[str],
    signal_terms: list[str],
    anchor_date: str,
) -> tuple[float, str | None]:
    """Compute the composite score for an article.

    Returns (composite_score, matched_country_iso3).
    """
    country_score, matched_country = _score_country_relevance(article, countries)
    semantic_score = _score_semantic_relevance(article, signal_terms)
    source_score = _score_source_quality(article)
    recency_score = _score_recency(article, anchor_date)
    info_score = _score_info_value(article)

    w = SCORING_WEIGHTS
    composite = (
        w["country"] * country_score
        + w["semantic"] * semantic_score
        + w["source"] * source_score
        + w["recency"] * recency_score
        + w["info_value"] * info_score
    )

    return composite, matched_country


def _deduplicate_by_title(
    scored: list[tuple[float, str | None, dict]],
) -> list[tuple[float, str | None, dict]]:
    """Remove near-duplicate articles based on title similarity."""
    if not scored:
        return scored

    result: list[tuple[float, str | None, dict]] = []
    seen_titles: list[str] = []

    for score, country, article in scored:
        title = (article.get("title") or "").strip()
        if not title:
            result.append((score, country, article))
            continue

        is_dup = False
        for existing in seen_titles:
            ratio = difflib.SequenceMatcher(None, title.lower(), existing.lower()).ratio()
            if ratio >= _DEDUP_SIMILARITY_THRESHOLD:
                is_dup = True
                break

        if not is_dup:
            seen_titles.append(title)
            result.append((score, country, article))

    return result


def _score_and_rank_articles(
    articles: list[dict],
    countries: list[str],
    kpi_id: str,
    anchor_date: str,
) -> list[tuple[float, str | None, dict]]:
    """Score, filter, deduplicate, and rank articles.

    Returns a sorted list of (score, matched_country, article).
    """
    nq = KPI_NEWS_QUERIES.get(kpi_id)
    signal_terms = nq.signal_terms if nq else []

    word_filtered = [
        a for a in articles
        if len((a.get("content") or a.get("description") or "").split()) >= _MIN_WORD_COUNT
    ]
    log.info(
        "[SCORE] Word-count filter: %d -> %d articles (min %d words)",
        len(articles), len(word_filtered), _MIN_WORD_COUNT,
    )

    scored: list[tuple[float, str | None, dict]] = []
    for a in word_filtered:
        composite, matched = _compute_article_score(a, countries, signal_terms, anchor_date)
        scored.append((composite, matched, a))

    scored.sort(key=lambda x: x[0], reverse=True)

    deduped = _deduplicate_by_title(scored)
    log.info(
        "[SCORE] Dedup: %d -> %d articles",
        len(scored), len(deduped),
    )

    return deduped


# ---------------------------------------------------------------------------
# Time-alignment layer
# ---------------------------------------------------------------------------

def _align_articles_to_periods(
    scored_articles: list[tuple[float, str | None, dict]],
    derived_facts: list[dict],
    frequency: str,
) -> dict[str, list[dict]]:
    """Group articles by the data period (quarter or year) they correspond to.

    Also flags articles near detected inflection points.
    """
    inflection_date_str, _, _ = _find_notable_inflection(derived_facts)
    inflection_dt: datetime | None = None
    if inflection_date_str:
        try:
            inflection_dt = pd.Timestamp(inflection_date_str).to_pydatetime()
        except Exception:
            pass

    period_map: dict[str, list[dict]] = {}

    for _score, _country, article in scored_articles:
        pub_date = article.get("published_date") or ""
        if not pub_date:
            period_map.setdefault("unknown", []).append(article)
            continue

        try:
            pub_dt = pd.Timestamp(pub_date).to_pydatetime()
        except Exception:
            period_map.setdefault("unknown", []).append(article)
            continue

        if frequency == "Q":
            quarter = (pub_dt.month - 1) // 3 + 1
            period_key = f"Q{quarter} {pub_dt.year}"
        else:
            period_key = str(pub_dt.year)

        near_inflection = False
        if inflection_dt:
            days_from_inflection = abs((pub_dt - inflection_dt).days)
            near_inflection = days_from_inflection <= 90

        enriched = {**article, "_period": period_key, "_near_inflection": near_inflection}
        period_map.setdefault(period_key, []).append(enriched)

    return period_map


# ---------------------------------------------------------------------------
# Synthesize news context (upgraded — uses scoring + time-alignment)
# ---------------------------------------------------------------------------

def _synthesize_news_context(
    articles: list[dict],
    countries: list[str],
    kpi_id: str = "",
    anchor_date: str = "",
    derived_facts: list[dict] | None = None,
) -> dict[str, Any]:
    """Score, rank, align and condense articles into prompt-ready format.

    Pipeline:
    1. Score and rank all articles via the scoring pipeline
    2. Time-align to data periods
    3. Select top N per country
    4. Format for LLM prompt injection
    """
    if not anchor_date:
        anchor_date = datetime.now().strftime("%Y-%m-%d")

    scored = _score_and_rank_articles(articles, countries, kpi_id, anchor_date)

    nq = KPI_NEWS_QUERIES.get(kpi_id)
    frequency = "Q"
    for spec in SPECS:
        if spec.id == kpi_id:
            frequency = spec.frequency
            break

    if derived_facts:
        _align_articles_to_periods(scored, derived_facts, frequency)

    by_country: dict[str, list[dict]] = {c: [] for c in countries}
    unmatched: list[dict] = []

    for score, matched_country, article in scored:
        nlp = article.get("nlp") or {}
        sentiment = None
        if isinstance(nlp, dict):
            sent_obj = nlp.get("sentiment") or {}
            if isinstance(sent_obj, dict):
                sentiment = sent_obj.get("content")

        snippet = article.get("description") or article.get("content") or ""
        if len(snippet) > 300:
            snippet = snippet[:297] + "..."

        pub_date = article.get("published_date") or ""
        period = article.get("_period", "")
        near_inflection = article.get("_near_inflection", False)

        condensed: dict[str, Any] = {
            "title": article.get("title", ""),
            "date": pub_date,
            "snippet": snippet,
            "source": article.get("name_source", ""),
            "sentiment": sentiment,
            "score": round(score, 3),
        }
        if period:
            condensed["period"] = period
        if near_inflection:
            condensed["near_inflection"] = True

        if matched_country and matched_country in by_country:
            by_country[matched_country].append(condensed)
        else:
            unmatched.append(condensed)

    for country_code in by_country:
        by_country[country_code] = by_country[country_code][:_ARTICLES_PER_COUNTRY]

    if unmatched:
        for country_code in by_country:
            remaining = _ARTICLES_PER_COUNTRY - len(by_country[country_code])
            if remaining > 0 and unmatched:
                by_country[country_code].extend(unmatched[:remaining])
                unmatched = unmatched[remaining:]

    result: dict[str, Any] = {}
    for country_code, arts in by_country.items():
        if arts:
            result[country_code] = arts

    if unmatched:
        result["_general"] = unmatched[:_ARTICLES_PER_COUNTRY]

    log.info(
        "[NC-DEBUG] _synthesize_news_context: %d input -> scored %d -> by_country %s, %d unmatched",
        len(articles), len(scored),
        {k: len(v) for k, v in result.items()},
        len(unmatched),
    )
    for k, v in result.items():
        for art in v[:2]:
            log.info(
                "[NC-DEBUG]   %s -> %s (score=%.3f, %s)",
                k, art.get("title", "")[:60], art.get("score", 0), art.get("date", ""),
            )

    return result


# ---------------------------------------------------------------------------
# V2 extension point stubs (see ADR-001 — designed now, implemented later)
# ---------------------------------------------------------------------------

class ScorerPlugin:
    """Interface for V2 scoring modules that can be plugged into the pipeline.

    V2 modules (e.g. embedding-based semantic scorer, source allowlist scorer)
    should subclass this and implement ``score()``.  The pipeline would iterate
    over registered plugins and merge their scores into the composite.

    Not wired into the pipeline yet — placeholder for V2 architecture.
    """

    name: str = "base"
    weight: float = 0.0

    def score(self, article: dict, context: dict[str, Any]) -> float:
        """Return a 0-1 score for the article given the analysis context.

        ``context`` includes keys: countries, kpi_id, signal_terms,
        anchor_date, derived_facts.
        """
        raise NotImplementedError


class EmbeddingScorerStub(ScorerPlugin):
    """V2: Semantic relevance via sentence-transformer embeddings.

    Would compute cosine similarity between article text and a reference
    KPI description embedding using a lightweight model like
    ``sentence-transformers/all-MiniLM-L6-v2``.

    Prerequisites: sentence-transformers pip package, model download,
    pre-computed KPI description embeddings.
    """

    name = "embedding_semantic"
    weight = 0.25

    def score(self, article: dict, context: dict[str, Any]) -> float:
        raise NotImplementedError("V2: requires sentence-transformers")


class StatisticalCorrelationStub:
    """V2: Compute rolling correlation between sentiment trends and KPI values.

    Would take a time-series of aggregated daily/weekly sentiment scores
    and correlate with KPI data points using pandas rolling windows and
    scipy.stats.pearsonr.

    Prerequisites: batch article storage (SQLite), 3+ months of archived
    sentiment data, scipy dependency.
    """

    @staticmethod
    def compute_correlation(
        sentiment_series: "pd.Series",  # type: ignore[name-defined]
        kpi_series: "pd.Series",  # type: ignore[name-defined]
        window: int = 30,
    ) -> float:
        raise NotImplementedError("V2: requires batch article storage + scipy")


class AnomalyDetectorStub:
    """V2: Detect unusual news volume spikes for a KPI/country.

    Would compare current article count against a rolling baseline to
    flag abnormally high or low coverage.  Useful for alerting: 'news
    volume for SAU inflation surged 3x this week'.

    Prerequisites: batch article storage with historical counts,
    scipy.stats for z-score computation.
    """

    @staticmethod
    def detect_volume_anomaly(
        current_count: int,
        baseline_mean: float,
        baseline_std: float,
        threshold_z: float = 2.0,
    ) -> bool:
        raise NotImplementedError("V2: requires historical article counts")


class TopicModelStub:
    """V2: Cluster articles into sub-themes beyond Newscatcher's coarse themes.

    Would use BERTopic or TF-IDF + k-means to discover latent topics
    within the article pool for a KPI, enabling the LLM to see thematic
    diversity (e.g. for inflation: 'food prices', 'monetary policy',
    'energy costs' as distinct sub-themes).

    Prerequisites: BERTopic or scikit-learn, sentence-transformers
    for embeddings, enough articles per query (50+).
    """

    @staticmethod
    def extract_topics(
        articles: list[dict],
        n_topics: int = 5,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("V2: requires BERTopic or scikit-learn")


class BatchPreprocessorStub:
    """V2: Daily job to pre-fetch, score, and store articles.

    Would run on a scheduler (cron/Celery/APScheduler) to:
    1. Iterate all KPI x country combinations
    2. Fetch articles from Newscatcher
    3. Score and store in SQLite/PostgreSQL with metadata
    4. Pre-compute sentiment aggregates and article counts

    Insight requests would then read from storage instead of making
    live API calls, reducing latency to near-zero for the news component.

    Prerequisites: SQLite or PostgreSQL, scheduler infrastructure,
    staleness management (max age before refresh).
    """

    @staticmethod
    def run_daily_fetch(
        kpi_ids: list[str],
        countries: list[str],
    ) -> None:
        raise NotImplementedError("V2: requires storage + scheduler infrastructure")


class GrangerCausalityStub:
    """V2: Test whether news sentiment leads or lags KPI movements.

    Would use statsmodels.tsa.stattools.grangercausalitytests to
    determine if changes in aggregated news sentiment Granger-cause
    changes in KPI values, or vice versa.

    Prerequisites: 6+ months of time-aligned sentiment + KPI data,
    statsmodels dependency, stationarity testing.
    """

    @staticmethod
    def test_causality(
        sentiment_series: "pd.Series",  # type: ignore[name-defined]
        kpi_series: "pd.Series",  # type: ignore[name-defined]
        max_lag: int = 4,
    ) -> dict[str, Any]:
        raise NotImplementedError("V2: requires statsmodels + archived data")


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior macro-economic analyst producing data-grounded insights for an executive briefing tool. You combine rigorous data interpretation with your broad knowledge of macroeconomic policy, geopolitics, and institutional developments to produce insights that explain not just what is happening, but why — and what may come next.

HARD CONSTRAINTS — data integrity (applies to Summary and Key Findings):
- In "Summary" and "Key Findings", interpret ONLY the JSON in DATA_CONTEXT. Do NOT invent statistics or data points not present.
- If data are missing (empty series, partial errors), say so explicitly; never fill gaps.
- Use ISO-3 country codes exactly as given (e.g. SAU, QAT).
- Every numeric statement in "Key Findings" must correspond to a value in DATA_CONTEXT.results or derived_facts.
- You may only reference KPIs listed in selection.kpi_ids and countries in selection.countries.
- If the data are insufficient for a claim, state that the view does not contain enough points.

EXTERNAL CONTEXT — Implications section only:
- In the "Implications" section, you MUST draw on your macroeconomic knowledge to provide SPECIFIC causal explanations and forward outlook. This includes:
  * Government policies and reform programs (e.g. Saudi Vision 2030, UAE diversification, Omanisation)
  * Central bank actions and monetary policy decisions (including Fed-linked peg pass-through)
  * OPEC/OPEC+ production decisions and energy market dynamics
  * Trade agreements, sanctions, geopolitical developments
  * IMF/World Bank commentary, credit rating actions, institutional forecasts
  * Fiscal policy announcements (budgets, stimulus, austerity, subsidy reforms, VAT changes)
  * Major real-world events visible in the data window (pandemics, commodity shocks, regional conflicts)
- Follow this pattern for each implication bullet: [data trend observed] + [SPECIFIC likely cause from known context] + [consequence or risk] + [forward outlook].
  Example: "SAU's non-oil GDP growth of 4.21% in 2024, likely supported by Vision 2030 giga-project spending and tourism sector expansion, suggests the diversification trajectory is gaining traction — if sustained, non-oil revenue could reduce fiscal breakeven oil prices over the medium term."
- SPECIFICITY IS MANDATORY. You must name the actual policy, event, decision, or mechanism you believe explains a trend. Examples of what is required vs. what is forbidden:
  * GOOD: "The Q3 2022 FDI drop coincided with aggressive Fed rate hikes (300bp between March and September 2022) which strengthened the dollar and raised the cost of capital for cross-border investments, while the Russia-Ukraine conflict disrupted global supply chains and redirected European capital toward nearshoring."
  * BAD: "The drop was driven by global economic uncertainties and regional geopolitical tensions." — This says NOTHING. What uncertainties? What tensions? An analyst already knows there were uncertainties; they need to know WHICH ones and HOW they transmitted to FDI.
  * GOOD: "The 2020 FDI collapse is consistent with the COVID-19 pandemic lockdowns that froze cross-border M&A activity, compounded by the April 2020 oil price war between Saudi Arabia and Russia that cratered Brent crude to below $20/barrel."
  * BAD: "The decline was likely driven by pandemic-era disruptions and commodity price volatility." — Too vague; name the specific disruptions.
- When explaining a causal mechanism, describe the TRANSMISSION CHANNEL: how does the event actually affect the KPI? For example, Fed rate hikes affect GCC FDI because GCC currencies are pegged to USD, so higher US rates mechanically raise local borrowing costs and reduce the relative attractiveness of GCC assets to dollar-denominated investors.
- Name specific policies, programs, or events when you are confident they are real and relevant. Use calibrated confidence language: "consistent with", "likely driven by", "aligned with the stated objectives of".
- NEVER fabricate policies, events, or institutional statements. If you are not confident about a causal explanation, state the data trend and say you lack sufficient context to explain it — this is FAR better than vague hand-waving.
- Clearly distinguish between established facts about the world and your own speculative inference.

NEWS CONTEXT — grounding Implications in real events:
- You may receive a NEWS_CONTEXT JSON block containing recent news articles relevant to the selected KPIs and countries, sourced from the Newscatcher News API.
- In the "Implications" section, you MUST prefer citing specific events, policies, or statements from NEWS_CONTEXT over relying on your parametric knowledge when they plausibly explain a data trend.
- Follow this enhanced pattern for news-grounded implications: [data trend from Key Findings] + [specific event/policy/statement from a news article] + [causal mechanism linking the event to the trend] + [forward outlook or risk].
- When citing news, reference the event or policy by name and approximate date (e.g. "following the June 2024 OPEC+ agreement to extend voluntary cuts"). Do NOT cite article titles, URLs, or source names in the output.
- If NEWS_CONTEXT is empty or no articles are relevant to a particular finding, fall back to your general macroeconomic knowledge as instructed above.
- NEVER fabricate news events. If unsure whether a news article is relevant, state the data trend without forcing an explanation.

NUMBER FORMATTING — strict:
- Percentages (growth rates, ratios, shares, inflation): report to exactly 2 decimal places (e.g. 3.42%, not 3.4% or 3.421%).
- Absolute numbers that are naturally whole (population, counts): use no decimals. Express large numbers readably (e.g. "36.95 million" or "1.24 billion"), with at most 2 decimals.
- Currency / GDP absolute values: round to 2 decimal places in the unit used (e.g. 245.67 billion LCU).
- Never show more than 2 decimal places for any number.

DATE AND TIME REFERENCES — strict:
- Cite years only (e.g. "2024"), not full dates (e.g. not "2024-01-01T00:00:00"), unless the quarter is analytically relevant.
- When quarterly granularity matters (e.g. inflation turning points, GDP growth inflections), cite the quarter as "Q1 2024", "Q3 2023", etc.
- Do not reference future years or projected dates. Only cite up to the present year (2026) or the latest year with actual data, whichever is earlier.
- Never cite ISO timestamps or machine-formatted dates.

WRITING STYLE — analytical, specific, never vague:
- Do not simply list numbers. Every bullet must explain what the number means economically.
- After stating a fact, immediately provide the analytical "so what" — the economic consequence or significance.
- Use comparative framing: "X grew twice as fast as Y", "the spread between A and B widened by Z pp".
- Distinguish between levels and changes. A high level does not imply growth; a large change does not imply a high level.
- Use plain language suitable for C-suite executives. Avoid jargon without brief clarification on first use.
- BANNED PHRASES — never use these vague fillers as causal explanations. They add zero analytical value:
  * "global economic uncertainties" / "economic uncertainty"
  * "regional geopolitical tensions" / "geopolitical tensions"
  * "market dynamics" / "global market dynamics"
  * "external shocks" (without naming the specific shock)
  * "challenging macroeconomic environment"
  * "shifting investor sentiment" (without saying what caused it to shift)
  * "domestic economic conditions" (without specifying which conditions)
  If you find yourself writing any of these, STOP and replace them with the specific event, policy, or mechanism you actually mean. If you don't know the specific cause, say so explicitly rather than hiding behind vague language.

TEMPORAL COVERAGE — cover the ENTIRE data window, not just the latest period:
- Your analysis MUST span the full time range present in the data (e.g. 2020–2025), not just the most recent quarter or year.
- Use the derived_facts fields to identify patterns across the full period:
  * "cagr" — the compound annual growth rate across the entire data window. Report this to frame the long-term trajectory.
  * "period_over_period" — all consecutive changes. Scan these for turning points, acceleration, deceleration.
  * "inflection_points" — pre-identified moments where the trend reversed direction or exhibited outsized moves. These are HIGH-PRIORITY for Key Findings.
  * "trend_segments" — consecutive runs of growth or decline. Use these to describe structural phases (e.g. "a sustained decline from 2021 to 2023 followed by a sharp recovery").
  * "earliest" and "latest" — the bookends of the series. Use these alongside "cagr" for full-period framing.
- DO NOT default to only discussing the last 1-2 data points. If the data spans 5+ years, your insights should reflect that depth.
- Prioritize: (1) the most significant inflection point in the full window, (2) the overall trajectory/CAGR, (3) structural phase shifts, (4) the latest data point in context of the longer trend.
- When discussing the latest period, always frame it relative to the longer-term trend: "after declining at a -2.30% CAGR from 2020 to 2023, FDI reversed course in 2024" is far more valuable than "FDI rose in Q4 2025".

NOTABILITY FILTER — only surface what matters:
- Only report findings that are NOTABLE: large movements (>5pp for shares, >2pp for rates), trend reversals, cross-country divergences, structural outliers, or sustained multi-year trends (positive or negative CAGR).
- Suppress trivial observations like "X grew slightly" or "Y remained broadly stable" UNLESS stability itself is the noteworthy finding (e.g. inflation flat near 0% for 3 consecutive years).
- Do NOT produce a bullet for every sub-indicator of a KPI. Synthesize: e.g. "Services dominated at X%, with manufacturing and agriculture together accounting for Y%", rather than one bullet per sector.
- If nothing notable happened for a KPI in the data window, say so in one sentence instead of forcing generic commentary.
- A multi-year decline or a negative CAGR is ALWAYS notable and must be reported.

OUTPUT STRUCTURE — mandatory:
You must structure your response in EXACTLY these three sections using markdown ## headings:

## Summary
2-3 sentences capturing the single most important takeaway from the data. This is the executive headline — lead with the most striking or consequential finding. Frame the summary across the FULL data window, not just the latest period.

## Key Findings
4-6 bullet points. Each bullet must be grounded directly in the data: a specific number, the country, the year/quarter, and an analytical interpretation. These are FACTUAL observations — they state what the data shows and what it means, but do not speculate beyond the data. No external context here.
COVERAGE REQUIREMENT: Your bullets must span the full data window. Specifically:
- At least one bullet must address the long-term trajectory (CAGR or total change across the full period).
- At least one bullet must address the most significant inflection point or trend reversal within the data window (if any exist in inflection_points or trend_segments).
- Remaining bullets should cover other notable movements, cross-country divergences, or structural shifts across ANY part of the time range — not just the latest period.
- You may include one bullet on the latest period, but it must be contextualized against the longer trend.

## Implications
3-4 bullet points. This is where you combine data findings with your macroeconomic knowledge. Each bullet should:
(a) Reference the data trend from Key Findings,
(b) Provide a SPECIFIC causal explanation — name the actual policy, event, decision, or mechanism. Never use vague phrases like "global uncertainties" or "geopolitical tensions" without specifying which ones and how they transmitted to the KPI,
(c) Describe the TRANSMISSION CHANNEL — how does the cause actually affect the indicator? (e.g. "Fed rate hikes raise GCC borrowing costs through the currency peg, making local assets less attractive to foreign investors"),
(d) State the consequence or risk, and
(e) Offer a forward outlook.
Implications should cover structural/long-term causes (not just recent events) when the data spans multiple years. For example, a multi-year decline in FDI warrants discussion of underlying structural factors, not just a quarterly blip.
Use calibrated confidence language throughout: "likely driven by", "consistent with", "this suggests", "if sustained, this may".
If you cannot identify a specific cause for a trend, say so explicitly — "the cause of this movement is not clear from available context" is infinitely more useful than vague hand-waving.
"""

_CROSS_KPI_ADDENDUM = (
    "Where multiple KPIs appear in the data, you may note consistency or tension "
    "between them WITHOUT importing variables not in the payload."
)


def _build_insight_prompt(
    selection: dict,
    results: list[dict],
    derived_facts: list[dict],
    news_context: dict[str, Any] | None = None,
) -> list[dict]:
    """Assemble the ChatCompletion messages list."""
    lens_blocks: list[str] = []
    for kpi_id in _sorted_kpi_ids(list(selection["kpi_ids"])):
        lens = INSIGHT_LENSES.get(kpi_id)
        if not lens:
            continue
        block = f"### Lens for KPI {kpi_id} — {lens.headline}\n"
        block += "What counts as notable:\n" + "\n".join(f"- {c}" for c in lens.notability_cues) + "\n"
        if lens.context_hooks:
            block += "Relevant external context for Implications (draw on your knowledge of):\n"
            block += "\n".join(f"- {h}" for h in lens.context_hooks) + "\n"
        if lens.forbidden_claims:
            block += "Forbidden claims:\n" + "\n".join(f"- {f}" for f in lens.forbidden_claims) + "\n"
        if lens.units_note:
            block += f"Units note: {lens.units_note}\n"
        lens_blocks.append(block)

    data_context = {
        "selection": selection,
        "results": results,
        "derived_facts": derived_facts,
    }

    news_block = ""
    if news_context:
        news_json = json.dumps(news_context, default=str)
        news_block = (
            "\n\nNEWS_CONTEXT (JSON) — recent news articles relevant to the selected KPIs and countries. "
            "Use these to ground the Implications section in specific real-world events:\n"
            f"```json\n{news_json}\n```\n"
        )
        log.info("[NC-DEBUG] _build_insight_prompt: NEWS_CONTEXT block injected (%d chars)", len(news_json))
    else:
        log.info("[NC-DEBUG] _build_insight_prompt: NO news_context — news block empty")

    user_content = (
        "DATA_CONTEXT (JSON):\n"
        f"```json\n{json.dumps(data_context, default=str)}\n```\n"
        + news_block
        + "\n"
        "Per-KPI notability lenses (use these to decide what is worth reporting):\n\n"
        + "\n".join(lens_blocks)
        + "\n"
        + _CROSS_KPI_ADDENDUM
        + "\n\n"
        "Task — follow the OUTPUT STRUCTURE from the system prompt exactly:\n\n"
        "IMPORTANT: The derived_facts now include full-period analytics. Use them:\n"
        "- 'cagr': compound annual growth rate across the entire data window — use this to frame the long-term trajectory.\n"
        "- 'inflection_points': pre-identified trend reversals and outsized moves — these are HIGH PRIORITY for Key Findings.\n"
        "- 'trend_segments': consecutive runs of growth or decline — use to describe structural phases.\n"
        "- 'period_over_period': all consecutive changes — scan for patterns across the FULL time range.\n"
        "- 'earliest'/'latest': bookend values for full-period framing.\n\n"
        "1. **## Summary** — 2-3 sentences. Lead with the most striking finding, but frame it "
        "across the FULL data window. Example: 'Over 2020-2025, SAU inward FDI declined at a "
        "-3.50% CAGR, with a sharp 40% drop in 2022 partially offset by recovery in 2024-25.' "
        "Do not repeat every KPI; distill the macro story.\n\n"
        "2. **## Key Findings** — 4-6 bullets. Each must cite a specific number "
        "(formatted per the rules), the country, the year/quarter, and an analytical "
        "interpretation. Only include NOTABLE findings — skip unremarkable data points. "
        "Synthesize sub-indicators rather than listing each one. Do not write bullets "
        "that merely restate a number without explaining its economic significance. "
        "No external context in this section — data only.\n"
        "   COVERAGE REQUIREMENT:\n"
        "   - At least ONE bullet on the long-term trajectory (CAGR or total change across the full period).\n"
        "   - At least ONE bullet on the most significant inflection point or trend reversal (if any exist).\n"
        "   - Remaining bullets on other notable movements across ANY part of the time range.\n"
        "   - You may include one bullet on the latest period, but contextualize it against the longer trend.\n"
        "   - Do NOT cluster all bullets on the last 1-2 data points.\n\n"
        "3. **## Implications** — 3-4 bullets. This is where you bring in external "
        "macro context. Each bullet must follow this pattern:\n"
        "   - [data trend from Key Findings] + [SPECIFIC cause — name the actual policy, event, "
        "or mechanism] + [TRANSMISSION CHANNEL — how does it affect the KPI?] + [consequence or risk] "
        "+ [forward outlook].\n"
        "   - NEVER use vague phrases like 'global uncertainties', 'geopolitical tensions', "
        "'market dynamics', or 'external shocks' as explanations. Always name the SPECIFIC event "
        "or policy and explain HOW it transmitted to the indicator.\n"
        "   - When the data spans multiple years, include at least one implication about "
        "STRUCTURAL or LONG-TERM causes (not just recent events). For example, a negative "
        "CAGR over several years warrants discussion of underlying structural factors.\n"
        "   - Prefer citing specific events from NEWS_CONTEXT when relevant. Reference the "
        "event by name and approximate date, not by article title or URL.\n"
        "   - GOOD Example: 'The -3.50% CAGR in SAU inward FDI from 2020 to 2023 coincided with "
        "COVID-19 lockdowns that froze cross-border M&A (2020), the April 2020 Saudi-Russia oil "
        "price war that cratered Brent to $20/barrel, and the Fed's 525bp tightening cycle "
        "(2022-23) which raised GCC borrowing costs through the dollar peg — the 2024 recovery, "
        "consistent with the new Investment Law enacted in late 2023 and NEOM-related capital "
        "commitments, suggests these structural headwinds are easing.'\n"
        "   - BAD Example (DO NOT write like this): 'The decline was likely driven by pandemic-era "
        "disruptions and shifting investor sentiment amid oil price volatility.' — This tells an "
        "analyst nothing they don't already know.\n"
        "   - If you cannot identify a specific cause, SAY SO: 'the driver of this movement is "
        "unclear from available context' is far better than vague hand-waving.\n"
        "   - Use calibrated language: 'likely driven by', 'consistent with', 'aligned with'. "
        "Never fabricate events.\n\n"
        "Formatting reminders: cite years only (e.g. '2024'), not ISO dates. "
        "Use quarter notation 'Q1 2024' only when quarter-level precision matters. "
        "All percentages to 2 decimal places. Absolute numbers with no more than 2 decimals.\n"
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class KpiInfo(BaseModel):
    id: str
    name: str
    source: str
    frequency: str
    indicators: list[str]
    notes: str
    available: bool


class FetchRequest(BaseModel):
    countries: list[str]
    kpi_ids: list[str]
    frequency_overrides: dict[str, str] | None = None
    timerange_q: str = "2015-2029"
    timerange_a: str = "2015-2026"


class SeriesPoint(BaseModel):
    date: str
    value: float | None


class IndicatorSeries(BaseModel):
    country: str
    indicator: str
    points: list[SeriesPoint]


class KpiResult(BaseModel):
    kpi_id: str
    kpi_name: str
    frequency: str
    native_frequency: str = ""
    series: list[IndicatorSeries]
    errors: list[str] = []


class FetchResponse(BaseModel):
    results: list[KpiResult]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/kpis", response_model=list[KpiInfo])
def list_kpis():
    return [
        KpiInfo(
            id=s.id, name=s.name, source=s.source, frequency=s.frequency,
            indicators=s.indicators, notes=s.notes,
            available=(s.source == "oxford"),
        )
        for s in SPECS
    ]


@app.post("/api/fetch", response_model=FetchResponse)
def fetch_data(req: FetchRequest):
    if not DEFAULT_HOST:
        raise HTTPException(500, "EAP_HOST is not configured in .env.")
    if not DEFAULT_APP_ID or not DEFAULT_APP_SECRET:
        raise HTTPException(500, "EAP_APP_ID / EAP_APP_SECRET not configured in .env.")
    if not req.countries:
        raise HTTPException(400, "Select at least one country.")
    if not req.kpi_ids:
        raise HTTPException(400, "Select at least one KPI.")

    apicfg = knoema.ApiConfig()
    apicfg.host = DEFAULT_HOST
    apicfg.app_id = DEFAULT_APP_ID
    apicfg.app_secret = DEFAULT_APP_SECRET

    timeranges = {"Q": req.timerange_q, "A": req.timerange_a}
    freq_overrides = req.frequency_overrides or {}
    results: list[KpiResult] = []

    for kpi_id in _sorted_kpi_ids(req.kpi_ids):
        spec = SPECS_BY_ID.get(kpi_id)
        if not spec:
            results.append(KpiResult(kpi_id=kpi_id, kpi_name="Unknown", frequency="",
                                     native_frequency="", series=[],
                                     errors=[f"KPI {kpi_id} not found."]))
            continue
        if spec.source != "oxford":
            results.append(KpiResult(kpi_id=kpi_id, kpi_name=spec.name,
                                     frequency=spec.frequency, native_frequency=spec.frequency,
                                     series=[], errors=["Not available via Oxford EAP (IMF source)."]))
            continue

        effective_freq = freq_overrides.get(kpi_id, spec.frequency)
        if spec.frequency == "A" and effective_freq == "Q":
            effective_freq = "A"
        tr = timeranges.get(effective_freq, timeranges["A"])
        clip_start, clip_end = _parse_timerange(tr)
        all_series: list[IndicatorSeries] = []
        errors: list[str] = []

        for country in req.countries:
            for indicator in spec.indicators:
                try:
                    df = knoema.get(
                        DATASET,
                        Location=country.strip(),
                        Indicator=indicator,
                        Frequency=effective_freq,
                        timerange=tr,
                    )
                    if df is None or df.empty:
                        errors.append(f"{country}/{indicator}: no data returned.")
                        continue

                    points: list[SeriesPoint] = []
                    for idx, row in df.iterrows():
                        ts = idx if not isinstance(idx, tuple) else idx[0]
                        val = row.iloc[0]
                        points.append(SeriesPoint(
                            date=pd.Timestamp(ts).isoformat(),
                            value=None if pd.isna(val) else float(val),
                        ))
                    points = _clip_points(points, clip_start, clip_end)
                    if not points:
                        errors.append(f"{country}/{indicator}: no data in selected range.")
                        continue
                    all_series.append(IndicatorSeries(
                        country=country, indicator=indicator, points=points,
                    ))
                except Exception as exc:
                    errors.append(f"{country}/{indicator}: {exc}")

        results.append(KpiResult(
            kpi_id=kpi_id, kpi_name=spec.name, frequency=effective_freq,
            native_frequency=spec.frequency,
            series=all_series, errors=errors,
        ))

    return FetchResponse(results=results)


# ---------------------------------------------------------------------------
# Insights endpoint
# ---------------------------------------------------------------------------

class RefetchKpiRequest(BaseModel):
    countries: list[str]
    kpi_id: str
    frequency: str
    timerange_q: str = "2015-2029"
    timerange_a: str = "2015-2026"


@app.post("/api/fetch-kpi")
def fetch_single_kpi(req: RefetchKpiRequest):
    """Re-fetch a single KPI with a specific frequency (A or Q)."""
    if not DEFAULT_HOST or not DEFAULT_APP_ID or not DEFAULT_APP_SECRET:
        raise HTTPException(500, "EAP credentials not configured in .env.")

    spec = SPECS_BY_ID.get(req.kpi_id)
    if not spec:
        raise HTTPException(404, f"KPI {req.kpi_id} not found.")
    if spec.source != "oxford":
        raise HTTPException(400, "Not available via Oxford EAP.")

    effective_freq = req.frequency
    if spec.frequency == "A" and effective_freq == "Q":
        effective_freq = "A"

    apicfg = knoema.ApiConfig()
    apicfg.host = DEFAULT_HOST
    apicfg.app_id = DEFAULT_APP_ID
    apicfg.app_secret = DEFAULT_APP_SECRET

    timeranges = {"Q": req.timerange_q, "A": req.timerange_a}
    tr = timeranges.get(effective_freq, timeranges["A"])
    clip_start, clip_end = _parse_timerange(tr)
    all_series: list[IndicatorSeries] = []
    errors: list[str] = []

    for country in req.countries:
        for indicator in spec.indicators:
            try:
                df = knoema.get(
                    DATASET,
                    Location=country.strip(),
                    Indicator=indicator,
                    Frequency=effective_freq,
                    timerange=tr,
                )
                if df is None or df.empty:
                    errors.append(f"{country}/{indicator}: no data returned.")
                    continue
                points: list[SeriesPoint] = []
                for idx, row in df.iterrows():
                    ts = idx if not isinstance(idx, tuple) else idx[0]
                    val = row.iloc[0]
                    points.append(SeriesPoint(
                        date=pd.Timestamp(ts).isoformat(),
                        value=None if pd.isna(val) else float(val),
                    ))
                points = _clip_points(points, clip_start, clip_end)
                if not points:
                    errors.append(f"{country}/{indicator}: no data in selected range.")
                    continue
                all_series.append(IndicatorSeries(
                    country=country, indicator=indicator, points=points,
                ))
            except Exception as exc:
                errors.append(f"{country}/{indicator}: {exc}")

    return KpiResult(
        kpi_id=req.kpi_id, kpi_name=spec.name, frequency=effective_freq,
        native_frequency=spec.frequency,
        series=all_series, errors=errors,
    )


class InsightsRequest(BaseModel):
    countries: list[str]
    kpi_ids: list[str]
    results: list[dict[str, Any]]


@app.post("/api/insights")
def generate_insights(req: InsightsRequest):
    valid_results = [r for r in req.results if r.get("series")]
    if not valid_results:
        raise HTTPException(400, "No data series to generate insights from.")

    valid_results.sort(
        key=lambda r: (
            _KPI_CATALOG_ORDER.get(str(r.get("kpi_id", "")), len(SPECS)),
            str(r.get("kpi_id", "")),
        )
    )

    selection = {"countries": req.countries, "kpi_ids": req.kpi_ids}
    derived_facts = _compute_derived_facts(valid_results)

    today_str = datetime.now().strftime("%Y-%m-%d")
    merged_news: dict[str, Any] = {}
    for r in valid_results:
        kid = str(r.get("kpi_id", ""))
        try:
            raw_articles = _fetch_news_for_kpi(kid, req.countries, derived_facts)
            kpi_news = _synthesize_news_context(
                raw_articles, req.countries,
                kpi_id=kid, anchor_date=today_str, derived_facts=derived_facts,
            )
            for country_key, arts in kpi_news.items():
                merged_news.setdefault(country_key, []).extend(arts)
        except Exception as exc:
            log.warning("News fetch failed for KPI %s: %s", kid, exc)

    for key in merged_news:
        merged_news[key] = merged_news[key][:_ARTICLES_PER_COUNTRY]

    log.info(
        "[NC-DEBUG] /api/insights: merged_news has %d country keys, %d total articles — injecting=%s",
        len(merged_news),
        sum(len(v) for v in merged_news.values()),
        bool(merged_news),
    )

    messages = _build_insight_prompt(
        selection, valid_results, derived_facts,
        news_context=merged_news if merged_news else None,
    )

    client = _openai_client()
    model = _openai_model()

    def _stream():
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=2048,
            stream=True,
            **_openai_temperature_kw(model),
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    return StreamingResponse(_stream(), media_type="text/plain")


class SingleKpiInsightRequest(BaseModel):
    countries: list[str]
    kpi_result: dict[str, Any]


@app.post("/api/insights/kpi")
def generate_single_kpi_insight(req: SingleKpiInsightRequest):
    """Generate insights for a single KPI, enriched with Newscatcher news context."""
    r = req.kpi_result
    if not r.get("series"):
        raise HTTPException(400, "No data series to generate insights from.")

    kpi_id = str(r.get("kpi_id", ""))
    selection = {"countries": req.countries, "kpi_ids": [kpi_id]}
    derived_facts = _compute_derived_facts([r])

    today_str = datetime.now().strftime("%Y-%m-%d")
    news_context: dict[str, Any] | None = None
    try:
        raw_articles = _fetch_news_for_kpi(kpi_id, req.countries, derived_facts)
        log.info("[NC-DEBUG] /api/insights/kpi KPI=%s: raw_articles=%d", kpi_id, len(raw_articles))
        if raw_articles:
            news_context = _synthesize_news_context(
                raw_articles, req.countries,
                kpi_id=kpi_id, anchor_date=today_str, derived_facts=derived_facts,
            )
            if not news_context:
                news_context = None
    except Exception as exc:
        log.warning("News fetch failed for KPI %s: %s", kpi_id, exc)

    log.info(
        "[NC-DEBUG] /api/insights/kpi KPI=%s: news_context injecting=%s, keys=%s",
        kpi_id, news_context is not None,
        list(news_context.keys()) if news_context else [],
    )

    messages = _build_insight_prompt(selection, [r], derived_facts, news_context=news_context)

    client = _openai_client()
    model = _openai_model()

    def _stream():
        stream = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=2048,
            stream=True,
            **_openai_temperature_kw(model),
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    return StreamingResponse(_stream(), media_type="text/plain")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main_api:app", host="127.0.0.1", port=8000, reload=True)
