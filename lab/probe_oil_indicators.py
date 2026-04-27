"""Probe Oxford (Knoema) for oil price and exchange rate indicators.

Run from project root:
    python -m lab.probe_oil_indicators
"""
from __future__ import annotations
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import knoema
import pandas as pd

from backend.config import EAP_HOST, EAP_APP_ID, EAP_APP_SECRET, DATASET


def configure():
    cfg = knoema.ApiConfig()
    cfg.host = EAP_HOST
    cfg.app_id = EAP_APP_ID
    cfg.app_secret = EAP_APP_SECRET


OIL_CANDIDATES = [
    "Oil prices, Brent crude",
    "Oil price, Brent, USD per barrel",
    "Oil price, Brent crude, US dollars",
    "Oil price, Brent",
    "Oil price",
    "Oil prices",
    "Brent crude oil price",
    "Brent oil price",
    "Oil price, Brent crude",
    "Oil prices, Brent",
    "Commodity price, oil",
    "World oil price",
    "Crude oil price",
    "Oil price, crude, Brent, USD/barrel",
    "Oil price, $ per barrel",
]

FX_CANDIDATES = [
    "Exchange rate, LCU per USD, period average",
    "Exchange rate, USD, period average",
    "Exchange rate, LCU vs USD",
    "Exchange rate, period average",
    "Exchange rate",
    "Exchange rate, LCU per USD",
    "Exchange rate, annual average",
]

LOCATIONS_OIL = ["WLD", "WORLD", "W00", "USA", "GBR", "SAU"]
LOCATIONS_FX = ["SAU"]


def try_fetch(location, indicator, freq="A"):
    try:
        result = knoema.get(
            DATASET, True,
            Location=location,
            Indicator=indicator,
            Frequency=freq,
            timerange="2020-2025",
        )
        if isinstance(result, tuple) and len(result) == 2:
            df, meta = result
        else:
            df, meta = result, None

        if df is not None and not df.empty:
            nrows = len(df)
            sample = df.iloc[-1].iloc[0] if nrows > 0 else None
            return True, nrows, sample
        return False, 0, None
    except Exception as exc:
        return False, 0, str(exc)[:80]


def main():
    configure()

    print("=" * 100)
    print("OIL PRICE INDICATORS")
    print("=" * 100)
    for loc in LOCATIONS_OIL:
        for ind in OIL_CANDIDATES:
            ok, n, sample = try_fetch(loc, ind)
            status = "OK" if ok else "--"
            print(f"  [{status}] {loc:>6} | {ind:<55} | rows={n}  sample={sample}")
        print()

    print("=" * 100)
    print("EXCHANGE RATE INDICATORS")
    print("=" * 100)
    for ind in FX_CANDIDATES:
        ok, n, sample = try_fetch("SAU", ind)
        status = "OK" if ok else "--"
        print(f"  [{status}]    SAU | {ind:<55} | rows={n}  sample={sample}")


if __name__ == "__main__":
    main()
