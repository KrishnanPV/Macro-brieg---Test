"""Newscatcher news integration — fetch, score, align, synthesize."""
from __future__ import annotations

import difflib
import hashlib
import logging
import math
import re
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests as http_requests

from backend.config import NEWSCATCHER_API_KEY, NEWSCATCHER_URL, NEWSCATCHER_TIMEOUT
from backend.models.kpi_registry import (
    SPECS, KPI_NEWS_QUERIES, ISO3_TO_NAME, ISO3_TO_ISO2, DEMONYMS,
)

log = logging.getLogger(__name__)


def _article_link(article: dict) -> str:
    for key in ("link", "url", "article_url"):
        v = article.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def stable_article_id(url: str, title: str) -> str:
    """Deterministic id for UI and citation markers (stable across requests for same url+title)."""
    h = hashlib.sha256(f"{url}|{title}".encode()).hexdigest()[:12]
    return f"nc_{h}"


def flatten_news_catalog(
    news_context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate by id, assign 1-based index, build prompt JSON and API article rows.

    Returns (articles_for_api, prompt_bundle) where prompt_bundle is ``{"articles": [...]}``
    with fields n, id, title, snippet, source, date, url, and optional country_iso3.
    """
    if not news_context:
        return [], {"articles": []}

    keys = [k for k in news_context.keys() if k != "_general"]
    keys.sort()
    if "_general" in news_context:
        keys.append("_general")

    seen: set[str] = set()
    merged: list[tuple[dict[str, Any], str | None]] = []
    for bucket in keys:
        items = news_context.get(bucket)
        if not isinstance(items, list):
            continue
        country_iso3: str | None = None if bucket == "_general" else bucket
        for item in items:
            if not isinstance(item, dict):
                continue
            aid = (item.get("id") or "").strip()
            if aid:
                if aid in seen:
                    continue
                seen.add(aid)
            merged.append((item, country_iso3))

    prompt_articles: list[dict[str, Any]] = []
    api_rows: list[dict[str, Any]] = []
    for i, (raw, country_iso3) in enumerate(merged, start=1):
        row = {
            "n": i,
            "id": raw.get("id", ""),
            "title": raw.get("title", ""),
            "snippet": raw.get("snippet", ""),
            "source": raw.get("source", ""),
            "date": raw.get("date", ""),
            "url": raw.get("url", ""),
        }
        if country_iso3:
            row["country_iso3"] = country_iso3
        prompt_articles.append(row)
        api_row = {
            "index": i,
            "id": row["id"],
            "title": row["title"],
            "snippet": row["snippet"],
            "source": row["source"],
            "date": row["date"],
            "url": row["url"],
        }
        if country_iso3:
            api_row["country_iso3"] = country_iso3
        api_rows.append(api_row)

    return api_rows, {"articles": prompt_articles}


# ---------------------------------------------------------------------------
# Scoring constants
# ---------------------------------------------------------------------------

_STAT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*%"
    r"|\$\s*\d"
    r"|\d+(?:\.\d+)?\s*(?:billion|million|trillion|bn|mn|tn)"
    r"|\d+(?:\.\d+)?\s*(?:bps|basis points|percentage points|pp)",
    re.IGNORECASE,
)

SCORING_WEIGHTS: dict[str, float] = {
    "country": 0.30, "semantic": 0.25, "source": 0.15,
    "recency": 0.15, "info_value": 0.15,
}

_ARTICLES_PER_COUNTRY = 10
# Dashboard KPI insights: richer NEWS_CONTEXT without country-brief scale.
DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY = 25
# Country brief: many articles per country for broad narrative grounding.
COUNTRY_BRIEF_ARTICLES_PER_COUNTRY = 100
_MIN_WORD_COUNT = 80
_DEDUP_SIMILARITY_THRESHOLD = 0.7
_RECENCY_LAMBDA = 0.005

NEWSCATCHER_DEFAULTS: dict[str, Any] = {
    "lang": "en", "search_in": "title_content",
    "include_translation_fields": False, "by_parse_date": False,
    "sort_by": "relevancy", "ranked_only": True,
    "from_rank": 1, "to_rank": 999999,
    "page": 1, "page_size": 100,
    "include_nlp_data": True, "has_nlp": True,
    "is_paid_content": False,
    "clustering_variable": "content", "clustering_threshold": 0.6,
}


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class _NewsCache:
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
        return entry[1] if entry else None

    def put(self, key: tuple, articles: list[dict]) -> None:
        self._evict()
        self._store[key] = (time.time(), articles)


_news_cache = _NewsCache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_country_placeholder(query_template: str, countries: list[str]) -> str:
    country_names = []
    for c in countries:
        name = ISO3_TO_NAME.get(c)
        if name:
            country_names.append(f'"{name}"')
    if not country_names:
        return query_template.replace("AND ({country})", "").replace("({country})", "")
    return query_template.replace("{country}", " OR ".join(country_names))


def _find_notable_inflection(
    derived_facts: list[dict],
) -> tuple[str | None, str | None, str | None]:
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


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _call_newscatcher(
    query_template: str, countries: list[str],
    themes: str, from_date: str, to_date: str,
) -> list[dict]:
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
        "q": resolved_query, "from_": from_date, "to_": to_date,
        "clustering_enabled": not crosses_year,
    }
    if themes:
        payload["theme"] = themes

    headers = {"x-api-token": NEWSCATCHER_API_KEY, "Content-Type": "application/json"}

    log.info("[NC] q=%s, from=%s, to=%s", resolved_query[:80], from_date, to_date)
    try:
        resp = http_requests.post(NEWSCATCHER_URL, headers=headers, json=payload, timeout=NEWSCATCHER_TIMEOUT)
        if not resp.ok:
            log.warning("[NC] %s — %s", resp.status_code, resp.text[:500])
            return []
        data = resp.json()

        if "clusters" in data:
            articles = []
            for cluster in data.get("clusters", []):
                articles.extend(cluster.get("articles", []))
            return articles

        return data.get("articles", [])
    except Exception as exc:
        log.warning("[NC] call failed: %s", exc)
        return []


_NEWSCATCHER_EARLIEST = datetime(2019, 1, 1)


def _derive_date_range(derived_facts: list[dict]) -> tuple[datetime, datetime]:
    """Extract the actual date range present in the KPI data series."""
    dates: list[datetime] = []
    for kpi_facts in derived_facts:
        for sf in kpi_facts.get("series_facts", []):
            for field in ("earliest", "latest"):
                d = sf.get(field, {}).get("date")
                if d:
                    try:
                        dates.append(pd.Timestamp(d).to_pydatetime())
                    except Exception:
                        pass
    if not dates:
        today = datetime.now()
        return today - timedelta(days=365), today
    return min(dates), max(dates)


def _clamp_date_range(
    range_start: datetime, range_end: datetime,
) -> tuple[str, str]:
    """Clamp a date range to Newscatcher's available window (2019+, up to today)."""
    today = datetime.now()
    clamped_start = max(range_start, _NEWSCATCHER_EARLIEST)
    clamped_end = min(range_end, today)
    if clamped_start >= clamped_end:
        clamped_start = clamped_end - timedelta(days=365)
        clamped_start = max(clamped_start, _NEWSCATCHER_EARLIEST)
    return clamped_start.strftime("%Y-%m-%d"), clamped_end.strftime("%Y-%m-%d")


def fetch_news_for_kpi(
    kpi_id: str, countries: list[str], derived_facts: list[dict],
) -> list[dict]:
    """Fetch news for a single KPI — one Newscatcher call for the full data range."""
    nq = KPI_NEWS_QUERIES.get(kpi_id)
    if not nq:
        return []

    sorted_countries = tuple(sorted(countries))

    range_start, range_end = _derive_date_range(derived_facts)
    range_end = range_end + timedelta(days=183)
    from_date, to_date = _clamp_date_range(range_start, range_end)

    cache_key = (kpi_id, sorted_countries, f"full_{from_date}_{to_date}")
    cached = _news_cache.get(cache_key)
    if cached is not None:
        return list(cached)

    articles = _call_newscatcher(
        nq.query_template, countries, nq.themes, from_date, to_date,
    )
    _news_cache.put(cache_key, articles)
    return articles


# ---------------------------------------------------------------------------
# Scoring pipeline
# ---------------------------------------------------------------------------

def _score_country_relevance(article: dict, countries: list[str]) -> tuple[float, str | None]:
    title = (article.get("title") or "").lower()
    content = (article.get("content") or article.get("description") or "").lower()
    nlp = article.get("nlp") or {}
    loc_entities: list[str] = []
    if isinstance(nlp, dict):
        ner = nlp.get("ner", [])
        if isinstance(ner, list):
            loc_entities = [
                (e.get("entity_name") or "").lower()
                for e in ner if isinstance(e, dict) and e.get("label") == "LOC"
            ]

    best_score, best_country = 0.0, None
    for iso3 in countries:
        name_lower = ISO3_TO_NAME.get(iso3, "").lower()
        if not name_lower:
            continue
        aliases = [name_lower] + DEMONYMS.get(iso3, [])
        in_title = any(a in title for a in aliases)
        in_ner = any(any(a in loc for a in aliases) for loc in loc_entities)
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
            best_score, best_country = score, iso3

    return best_score, best_country


def _score_semantic_relevance(article: dict, signal_terms: list[str]) -> float:
    if not signal_terms:
        return 0.5
    title = (article.get("title") or "").lower()
    content = (article.get("content") or article.get("description") or "").lower()
    hits = 0.0
    max_possible = len(signal_terms) * 2
    for term in signal_terms:
        t = term.lower()
        if t in title:
            hits += 2.0
        elif t in content:
            hits += 1.0
    return min(hits / max_possible, 1.0) if max_possible > 0 else 0.0


def _score_source_quality(article: dict) -> float:
    rank = article.get("rank")
    if rank is None or rank <= 0:
        return 0.3
    if rank <= 1_000:
        return 1.0
    elif rank <= 10_000:
        return 0.8
    elif rank <= 50_000:
        return 0.5
    return 0.3


def _score_recency(article: dict, anchor_date: str) -> float:
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
    score = 0.0
    nlp = article.get("nlp") or {}
    if isinstance(nlp, dict):
        if nlp.get("summary"):
            score += 0.2
        ner = nlp.get("ner", [])
        if isinstance(ner, list) and len(ner) >= 3:
            score += 0.3
        sent_obj = nlp.get("sentiment") or {}
        if isinstance(sent_obj, dict):
            if sent_obj.get("content") not in (None, 0.0):
                score += 0.1
    text = article.get("content") or article.get("description") or ""
    if _STAT_PATTERN.search(text):
        score += 0.2
    return min(score, 1.0)


def _compute_article_score(
    article: dict, countries: list[str], signal_terms: list[str], anchor_date: str,
) -> tuple[float, str | None]:
    country_score, matched_country = _score_country_relevance(article, countries)
    w = SCORING_WEIGHTS
    composite = (
        w["country"] * country_score
        + w["semantic"] * _score_semantic_relevance(article, signal_terms)
        + w["source"] * _score_source_quality(article)
        + w["recency"] * _score_recency(article, anchor_date)
        + w["info_value"] * _score_info_value(article)
    )
    return composite, matched_country


def _deduplicate_by_title(scored: list[tuple[float, str | None, dict]]) -> list[tuple[float, str | None, dict]]:
    if not scored:
        return scored
    result: list[tuple[float, str | None, dict]] = []
    seen_titles: list[str] = []
    for score, country, article in scored:
        title = (article.get("title") or "").strip()
        if not title:
            result.append((score, country, article))
            continue
        is_dup = any(
            difflib.SequenceMatcher(None, title.lower(), existing.lower()).ratio() >= _DEDUP_SIMILARITY_THRESHOLD
            for existing in seen_titles
        )
        if not is_dup:
            seen_titles.append(title)
            result.append((score, country, article))
    return result


def _score_and_rank_articles(
    articles: list[dict], countries: list[str], kpi_id: str, anchor_date: str,
    extra_signal_terms: list[str] | None = None,
) -> list[tuple[float, str | None, dict]]:
    nq = KPI_NEWS_QUERIES.get(kpi_id)
    signal_terms = list(nq.signal_terms) if nq else []
    if extra_signal_terms:
        seen = set(t.lower() for t in signal_terms)
        for t in extra_signal_terms:
            if t.lower() not in seen:
                signal_terms.append(t)
                seen.add(t.lower())
    word_filtered = [
        a for a in articles
        if len((a.get("content") or a.get("description") or "").split()) >= _MIN_WORD_COUNT
    ]
    scored = [(
        *_compute_article_score(a, countries, signal_terms, anchor_date), a
    ) for a in word_filtered]
    scored.sort(key=lambda x: x[0], reverse=True)
    return _deduplicate_by_title(scored)


def _align_articles_to_periods(
    scored_articles: list[tuple[float, str | None, dict]],
    derived_facts: list[dict],
    frequency: str,
) -> dict[str, list[dict]]:
    inflection_date_str, _, _ = _find_notable_inflection(derived_facts)
    inflection_dt = None
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
            near_inflection = abs((pub_dt - inflection_dt).days) <= 90

        enriched = {**article, "_period": period_key, "_near_inflection": near_inflection}
        period_map.setdefault(period_key, []).append(enriched)
    return period_map


def synthesize_news_context(
    articles: list[dict], countries: list[str],
    kpi_id: str = "", anchor_date: str = "",
    derived_facts: list[dict] | None = None,
    kpi_ids: list[str] | None = None,
    *,
    max_per_country: int | None = None,
) -> dict[str, Any]:
    """Score, rank, align and condense articles into prompt-ready format.

    max_per_country: cap after ranking per ISO3 bucket (and for _general). Defaults to
    ``_ARTICLES_PER_COUNTRY`` (10). Use :data:`COUNTRY_BRIEF_ARTICLES_PER_COUNTRY` or
    :data:`DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY` from callers as needed.
    """
    cap = max_per_country if max_per_country is not None else _ARTICLES_PER_COUNTRY
    if cap < 1:
        cap = 1
    if not anchor_date:
        anchor_date = datetime.now().strftime("%Y-%m-%d")

    extra_terms: list[str] | None = None
    if kpi_ids:
        extra_terms = []
        for kid in kpi_ids:
            nq = KPI_NEWS_QUERIES.get(kid)
            if nq:
                extra_terms.extend(nq.signal_terms)

    scored = _score_and_rank_articles(
        articles, countries, kpi_id, anchor_date,
        extra_signal_terms=extra_terms,
    )

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

        title = article.get("title", "") or ""
        url = _article_link(article)
        aid = stable_article_id(url, title)

        condensed: dict[str, Any] = {
            "id": aid,
            "title": title,
            "date": article.get("published_date", ""),
            "snippet": snippet,
            "source": article.get("name_source", ""),
            "url": url,
            "sentiment": sentiment,
            "score": round(score, 3),
        }
        period = article.get("_period", "")
        if period:
            condensed["period"] = period
        if article.get("_near_inflection", False):
            condensed["near_inflection"] = True

        if matched_country and matched_country in by_country:
            by_country[matched_country].append(condensed)
        else:
            unmatched.append(condensed)

    for country_code in by_country:
        by_country[country_code] = by_country[country_code][:cap]

    if unmatched:
        for country_code in by_country:
            remaining = cap - len(by_country[country_code])
            if remaining > 0 and unmatched:
                by_country[country_code].extend(unmatched[:remaining])
                unmatched = unmatched[remaining:]

    result: dict[str, Any] = {k: v for k, v in by_country.items() if v}
    if unmatched:
        result["_general"] = unmatched[:cap]

    return result
