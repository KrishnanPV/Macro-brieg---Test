"""Run the country brief pipeline with deep_analysis enabled from the CLI.

Usage:
    python lab/run_country_brief_deep.py --country SAU
    python lab/run_country_brief_deep.py --country SAU --start 2018 --end 2026
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.models.schemas import CountryBriefGenerateRequest
from backend.pipelines.country_brief import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Run country brief with deep analysis")
    parser.add_argument("--country", required=True, help="ISO3 country code (e.g. SAU)")
    parser.add_argument("--start", type=int, default=2015, help="Start year")
    parser.add_argument("--end", type=int, default=2026, help="End year")
    parser.add_argument("--no-deep", action="store_true", help="Disable deep analysis (standard mode)")
    args = parser.parse_args()

    req = CountryBriefGenerateRequest(
        country=args.country,
        start_year=args.start,
        end_year=args.end,
        deep_analysis=not args.no_deep,
    )

    mode = "standard" if args.no_deep else "deep analysis"
    print(f"--- Country Brief ({mode}): {args.country} ({args.start}-{args.end}) ---\n")

    for line in run_pipeline(req, deep_analysis=req.deep_analysis):
        event = json.loads(line)
        etype = event.get("type", "")

        if etype == "status":
            print(f"  [{etype}] {event['content']}")
        elif etype == "text_delta":
            print(event["content"], end="", flush=True)
        elif etype == "done":
            print("\n\n--- Brief generation complete ---")
        elif etype == "deep_analysis_start":
            content = event.get("content", {})
            ids = content.get("kpi_ids", [])
            print(f"  [deep_analysis] Starting parallel pipelines for {len(ids)} KPIs: {ids}")
        elif etype == "deep_analysis_kpi_done":
            c = event.get("content", {})
            print(
                f"  [deep_analysis] KPI {c.get('kpi_id')} ({c.get('kpi_name')}): "
                f"{c.get('signals', 0)} signals, {c.get('events', 0)} events, "
                f"{c.get('insights', 0)} insights"
            )
        elif etype == "deep_analysis_synthesis":
            c = event.get("content", {})
            print(
                f"  [synthesis] {len(c.get('cross_connections', []))} connections, "
                f"{len(c.get('themes', []))} themes, "
                f"{len(c.get('common_events', []))} common events"
            )
        elif etype in ("kpi_data", "triage", "news_catalog", "blocks"):
            content = event.get("content")
            if isinstance(content, list):
                print(f"  [{etype}] {len(content)} items")
            else:
                print(f"  [{etype}] received")
        else:
            print(f"  [{etype}] {str(event.get('content', ''))[:120]}")


if __name__ == "__main__":
    main()
