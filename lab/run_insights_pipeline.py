"""Run the 7-step insights investigation pipeline end-to-end from the CLI.

Usage:
    python lab/run_insights_pipeline.py --country SAU --kpi 3
    python lab/run_insights_pipeline.py --country SAU --kpi 3 --start 2018 --end 2026
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.models.insights import InsightLabRequest
from backend.pipelines.insights_lab import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run insights pipeline from CLI")
    parser.add_argument("--country", required=True, help="ISO3 country code (e.g. SAU)")
    parser.add_argument("--kpi", required=True, help="KPI ID (e.g. 3)")
    parser.add_argument("--start", type=int, default=2015, help="Start year")
    parser.add_argument("--end", type=int, default=2026, help="End year")
    args = parser.parse_args()

    req = InsightLabRequest(
        country=args.country,
        kpi_id=args.kpi,
        start_year=args.start,
        end_year=args.end,
    )

    print(f"--- Insights Pipeline: {args.country} / KPI {args.kpi} ({args.start}-{args.end}) ---\n")

    for line in run_pipeline(req):
        event = json.loads(line)
        etype = event.get("type", "")

        if etype == "status":
            print(f"  [{etype}] {event['content']}")
        elif etype == "error":
            print(f"  [ERROR] {event['content']}", file=sys.stderr)
        elif etype == "narrative_delta":
            print(event["content"], end="", flush=True)
        elif etype == "done":
            print("\n\n--- Pipeline complete ---")
        else:
            content = event.get("content")
            if isinstance(content, list):
                print(f"  [{etype}] {len(content)} items")
            elif isinstance(content, dict):
                print(f"  [{etype}] {json.dumps(content, default=str)[:120]}...")
            else:
                print(f"  [{etype}] {str(content)[:120]}")


if __name__ == "__main__":
    main()
