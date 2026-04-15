"""Quick verification that unit metadata flows through the pipeline.

Run from project root:
    python -m lab.verify_units
"""
from __future__ import annotations

import sys, os, json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

from backend.services.knoema_client import fetch_kpi_data
from backend.services.derived_facts import compute_derived_facts
from backend.services.signals import extract_signals


def main():
    country = sys.argv[1] if len(sys.argv) > 1 else "SAU"
    kpi_ids = ["1", "3", "4", "7"]

    print(f"=== Fetching KPI data for {country} (KPIs: {kpi_ids}) ===\n")

    resp = fetch_kpi_data(
        countries=[country],
        kpi_ids=kpi_ids,
        timerange_q="2020-2025",
        timerange_a="2020-2025",
    )

    print("--- KpiResult units ---")
    for r in resp.results:
        print(f"  KPI {r.kpi_id:>2} ({r.kpi_name}): unit={r.unit!r}")
        for s in r.series[:1]:
            print(f"    series: unit={s.unit!r}, scale={s.scale!r}")

    results_raw = [r.model_dump() for r in resp.results]

    print("\n--- Derived facts units ---")
    facts = compute_derived_facts(results_raw)
    for f in facts:
        print(f"  KPI {f['kpi_id']:>2}: unit={f.get('unit', '')!r}")
        for sf in f.get("series_facts", [])[:1]:
            print(f"    series: unit={sf.get('unit', '')!r}")

    print("\n--- Signal descriptions (first 5) ---")
    valid = [r for r in results_raw if r.get("series")]
    signals = extract_signals(valid)
    for s in signals[:5]:
        desc = s.description.replace("\u2192", "->")
        print(f"  [{s.kpi_id}] {desc}")

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
