"""Fuzzy-search the Oxford EAP indicator catalog from the command line.

Usage:
    python -m backend.tools.oxford_catalog.search "exports"
    python -m backend.tools.oxford_catalog.search "government revenue" --limit 50
"""
from __future__ import annotations

import argparse
import sys

from backend.services.oxford_catalog import search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the Oxford EAP indicator catalog.")
    parser.add_argument("term", help="Substring to search for (case-insensitive).")
    parser.add_argument("--limit", type=int, default=25, help="Maximum matches to print.")
    args = parser.parse_args(argv)

    matches = search(args.term, limit=args.limit)
    if not matches:
        print(f"No indicators match {args.term!r}.")
        return 1

    name_w = max(len(m["name"]) for m in matches)
    parent_w = max((len(m.get("parent_name") or "") for m in matches), default=0)
    for m in matches:
        flag = "*" if m.get("has_data") else " "
        print(f"{flag} {m['name']:<{name_w}}  [{m.get('parent_name', ''):<{parent_w}}]  id={m.get('id', '')}")
    print(f"\n{len(matches)} match(es). Leading '*' = catalog flags hasdata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
