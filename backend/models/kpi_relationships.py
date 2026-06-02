"""Static KPI relationship tags used by the signal-graph layer.

Three orthogonal taggings of the KPI catalog:

- ``KPI_FAMILY`` — one family per KPI (e.g. ``growth``, ``inflation``).
- ``KPI_CHANNELS`` — zero or more macro channels per KPI (e.g. ``oil_sector``).
- ``ACCOUNTING_IDENTITIES`` — explicit parent/component groupings.

Plus display-label maps for families and channels.

KPIs absent from a dict simply do not appear in the corresponding groups, so
the catalog can be extended incrementally without breaking the graph layer.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# KPI family — exactly one per KPI id
# ---------------------------------------------------------------------------

KPI_FAMILY: dict[str, str] = {
    "2":  "growth",              # GDP - Real (Oil vs Non-Oil)
    "3":  "growth",              # Real GDP Growth (YoY)
    "4":  "investment",          # FDI inflow & outflow
    "5":  "labor_market",        # Unemployment rate
    "6":  "consumer",            # Private consumption (Real PPP)
    "7":  "inflation",           # CPI Inflation
    "8":  "external_financing",  # External debt (% GDP)
    "9":  "demographics",        # Population
    "10": "growth",              # IMF NEA (placeholder)
    "11": "growth",              # GDP by Sector (Real)
    "12": "growth",              # GDP Growth Split (Total/Oil/Non-Oil)
    "13": "external_demand",     # Trade — Exports & Imports
    "14": "fiscal",              # Government revenue & expenditure
}


# ---------------------------------------------------------------------------
# Macro channels — zero or more per KPI id
# ---------------------------------------------------------------------------

KPI_CHANNELS: dict[str, frozenset[str]] = {
    "2":  frozenset({"oil_sector", "domestic_demand"}),
    "3":  frozenset({"growth"}),
    "4":  frozenset({"external_financing", "investment"}),
    "5":  frozenset({"labor_market", "domestic_demand"}),
    "6":  frozenset({"consumer", "domestic_demand"}),
    "7":  frozenset({"inflation", "monetary_policy"}),
    "8":  frozenset({"external_financing", "fiscal"}),
    "9":  frozenset({"demographics", "consumer"}),
    "10": frozenset({"growth"}),
    "11": frozenset({"growth", "domestic_demand"}),
    "12": frozenset({"growth", "oil_sector"}),
    "13": frozenset({"external_demand", "oil_sector", "commodity"}),
    "14": frozenset({"fiscal"}),
}


# ---------------------------------------------------------------------------
# Accounting identities — explicit parent / component relationships
# ---------------------------------------------------------------------------
#
# Only the identities the current 14-KPI catalog can populate cleanly are
# active. The classic decompositions the user listed (GDP expenditure,
# headline inflation breakdown, fiscal balance, current account) cannot be
# populated yet because their components live inside a single KPI's
# ``indicators`` list rather than as distinct KPI ids. Templates are
# preserved below as comments so they surface for activation when the
# catalog grows.

ACCOUNTING_IDENTITIES: dict[str, dict[str, Any]] = {
    "real_gdp_split": {
        "label": "Real GDP split (total vs oil/non-oil)",
        "parent_kpi_id": "3",
        "component_kpi_ids": ["2", "12"],
    },
    "growth_sector_decomposition": {
        "label": "Real GDP by sector",
        "parent_kpi_id": "3",
        "component_kpi_ids": ["11"],
    },
}

# Templates for future activation once the catalog distinguishes components
# as separate KPI ids:
#
# "gdp_expenditure": {
#     "label": "GDP expenditure identity (C + I + G + X - M)",
#     "parent_kpi_id": "3",
#     "component_kpi_ids": [<consumption>, <investment>, <gov>, <exports>, <imports>],
# },
# "headline_inflation": {
#     "label": "Headline inflation decomposition",
#     "parent_kpi_id": "7",
#     "component_kpi_ids": [<food>, <energy>, <core>],
# },
# "fiscal_balance": {
#     "label": "Fiscal balance (revenue - expenditure)",
#     "parent_kpi_id": <fiscal_balance>,
#     "component_kpi_ids": [<revenue>, <expenditure>],
# },
# "current_account": {
#     "label": "Current account (trade + income + transfers)",
#     "parent_kpi_id": <current_account>,
#     "component_kpi_ids": [<trade_balance>, <income_balance>, <transfers>],
# },


# ---------------------------------------------------------------------------
# Display labels
# ---------------------------------------------------------------------------

FAMILY_LABELS: dict[str, str] = {
    "growth":             "Growth",
    "investment":         "Investment",
    "labor_market":       "Labor market",
    "consumer":           "Consumer",
    "inflation":          "Inflation",
    "external_financing": "External financing",
    "demographics":       "Demographics",
    "external_demand":    "External demand",
    "fiscal":             "Fiscal",
}

CHANNEL_LABELS: dict[str, str] = {
    "growth":             "Growth",
    "domestic_demand":    "Domestic demand",
    "external_demand":    "External demand",
    "inflation":          "Inflation",
    "labor_market":       "Labor market",
    "fiscal":             "Fiscal",
    "monetary_policy":    "Monetary policy",
    "credit":             "Credit",
    "commodity":          "Commodity",
    "oil_sector":         "Oil sector",
    "investment":         "Investment",
    "consumer":           "Consumer",
    "external_financing": "External financing",
    "demographics":       "Demographics",
}
