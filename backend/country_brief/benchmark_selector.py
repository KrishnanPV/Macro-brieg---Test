"""Choose FDI benchmark peers (2 global + 2 regional)."""
from __future__ import annotations

import logging
import os
from typing import Any

from openai import OpenAI

from backend.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
from backend.country_brief.prompts import (
    BENCHMARK_SELECTOR_SYSTEM_PROMPT,
    build_benchmark_selector_prompt,
    parse_benchmark_selector_response,
)
from backend.models.kpi_registry import ISO3_TO_NAME
from backend.services.cost_tracker import record_usage

log = logging.getLogger(__name__)

_USE_LLM = os.getenv("BENCHMARK_USE_LLM", "").strip() == "1"

GLOBAL_CANDIDATE_ORDER = [
    "TUR", "MEX", "BRA", "IDN", "ZAF", "EGY", "GBR", "FRA", "DEU", "JPN", "IND", "CHN", "USA",
]

REGIONAL_GROUPS: dict[str, list[str]] = {
    "gcc": ["SAU", "ARE", "QAT", "KWT", "BHR", "OMN"],
    "europe": ["GBR", "DEU", "FRA", "TUR"],
    "americas": ["USA", "BRA", "MEX"],
    "asia_pacific": ["JPN", "CHN", "IND", "IDN"],
    "africa_me": ["EGY", "ZAF", "NGA"],
}

REGIONAL_FALLBACKS: dict[str, list[str]] = {
    "gcc": ["EGY", "TUR", "ZAF"],
    "europe": ["TUR", "USA", "JPN"],
    "americas": ["GBR", "DEU", "CHN"],
    "asia_pacific": ["CHN", "JPN", "USA"],
    "africa_me": ["TUR", "SAU", "ARE"],
}


def _get_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    kwargs: dict[str, Any] = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        kwargs["base_url"] = OPENAI_BASE_URL
    return OpenAI(**kwargs)


def _model_kwargs(model: str) -> dict[str, Any]:
    if model.lower().startswith("gpt-5"):
        return {}
    return {"temperature": 0.2}


def _region_for_country(country: str) -> str:
    iso3 = country.upper()
    for region, members in REGIONAL_GROUPS.items():
        if iso3 in members:
            return region
    return "global"


def _dedupe_keep_order(values: list[str], banned: set[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        code = str(raw).upper().strip()
        if not code or code in seen or code in banned:
            continue
        if code not in ISO3_TO_NAME:
            continue
        out.append(code)
        seen.add(code)
    return out


def _build_pools(country: str) -> tuple[list[str], list[str], list[str]]:
    target = country.upper()
    region = _region_for_country(target)

    regional_base = [c for c in REGIONAL_GROUPS.get(region, []) if c != target]
    regional_fallbacks = [c for c in REGIONAL_FALLBACKS.get(region, []) if c != target]
    regional_pool = _dedupe_keep_order(regional_base + regional_fallbacks, banned={target})

    global_pool = [c for c in GLOBAL_CANDIDATE_ORDER if c != target and c not in regional_pool]
    global_pool = _dedupe_keep_order(global_pool, banned={target})

    backfill_pool = _dedupe_keep_order(global_pool + regional_pool, banned={target})
    return global_pool, regional_pool, backfill_pool


def _fallback_selection(country: str) -> dict[str, Any]:
    global_pool, regional_pool, backfill_pool = _build_pools(country)
    return {
        "global": global_pool[:2],
        "regional": regional_pool[:2],
        "global_pool": global_pool,
        "regional_pool": regional_pool,
        "backfill_pool": backfill_pool,
    }


def select_benchmark_countries(
    country: str,
    *,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    """Pick 2 global + 2 regional benchmark peers."""
    target = country.upper()
    fallback = _fallback_selection(target)
    global_pool = fallback["global_pool"]
    regional_pool = fallback["regional_pool"]

    if not global_pool or not regional_pool or not _USE_LLM:
        if not _USE_LLM:
            log.info("Benchmark selector using deterministic pools for %s (LLM disabled)", target)
        return fallback

    target_region = _region_for_country(target)
    user_prompt = build_benchmark_selector_prompt(
        country=target,
        country_name=ISO3_TO_NAME.get(target, target),
        region_group=target_region,
        start_year=start_year,
        end_year=end_year,
        global_pool=global_pool,
        regional_pool=regional_pool,
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": BENCHMARK_SELECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            **_model_kwargs(OPENAI_MODEL),
        )
        record_usage(OPENAI_MODEL, response.usage, caller="benchmark_selector.select_benchmark_countries")
        parsed = parse_benchmark_selector_response(
            (response.choices[0].message.content or "").strip(),
            target_country=target,
            global_pool=global_pool,
            regional_pool=regional_pool,
        )
        chosen_global = list(parsed.get("global", []))
        chosen_regional = list(parsed.get("regional", []))

        if len(chosen_global) < 2:
            for code in global_pool:
                if code in chosen_global:
                    continue
                chosen_global.append(code)
                if len(chosen_global) == 2:
                    break
        if len(chosen_regional) < 2:
            for code in regional_pool:
                if code in chosen_regional or code in chosen_global:
                    continue
                chosen_regional.append(code)
                if len(chosen_regional) == 2:
                    break

        return {
            "global": chosen_global[:2],
            "regional": chosen_regional[:2],
            "global_pool": global_pool,
            "regional_pool": regional_pool,
            "backfill_pool": fallback["backfill_pool"],
        }
    except Exception:
        log.exception("FDI benchmark selector failed for %s", target)
        return fallback

