"""Probe what Unit / Scale metadata Oxford (Knoema) returns for each KPI.

Run from project root with the .venv activated:
    python -m lab.probe_knoema_metadata [COUNTRY]

Outputs a compact table of (KPI, indicator, Unit, Scale) for the given country.
"""
from __future__ import annotations

import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import knoema
import pandas as pd

from backend.config import EAP_HOST, EAP_APP_ID, EAP_APP_SECRET, DATASET
from backend.models.kpi_registry import SPECS, SPECS_BY_ID


def configure():
    cfg = knoema.ApiConfig()
    cfg.host = EAP_HOST
    cfg.app_id = EAP_APP_ID
    cfg.app_secret = EAP_APP_SECRET


def probe(country: str = "SAU"):
    configure()
    specs = [s for s in SPECS if s.source == "oxford"]

    print(f"{'KPI':>4} | {'Indicator':<45} | {'Unit':<40} | {'Scale'}")
    print("-" * 140)

    for spec in specs:
        for indicator in spec.indicators:
            try:
                result = knoema.get(
                    DATASET,
                    True,
                    Location=country,
                    Indicator=indicator,
                    Frequency=spec.frequency,
                    timerange="2024-2025",
                )
                if isinstance(result, tuple) and len(result) == 2:
                    _data_df, meta_df = result
                    # The metadata is a single-column DF; rows are attribute names
                    # Iterate over columns to find the one for our country
                    for col in meta_df.columns:
                        col_vals = meta_df[col]
                        unit_val = ""
                        scale_val = ""
                        for idx, val in col_vals.items():
                            idx_str = str(idx)
                            if "Unit" in idx_str:
                                unit_val = str(val) if pd.notna(val) else ""
                            elif "Scale" in idx_str:
                                scale_val = str(val) if pd.notna(val) else ""
                        print(f"{spec.id:>4} | {indicator:<45} | {unit_val:<40} | {scale_val}")
                else:
                    print(f"{spec.id:>4} | {indicator:<45} | (no metadata returned)")
            except Exception as exc:
                print(f"{spec.id:>4} | {indicator:<45} | ERROR: {exc}")


if __name__ == "__main__":
    country = sys.argv[1] if len(sys.argv) > 1 else "SAU"
    probe(country)
