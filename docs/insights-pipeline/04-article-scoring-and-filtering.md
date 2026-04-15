# 04 — Article scoring, filtering, and synthesis

**Source:** [`backend/services/news_client.py`](../../backend/services/news_client.py) lines 102–727 (commit `ce49207fc3ac58a63b3d44a528fd0f57057a2eb7`)

**Consumers:** [`backend/services/agent.py`](../../backend/services/agent.py) (`synthesize_news_context` with `DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY`), [`backend/routers/country_brief.py`](../../backend/routers/country_brief.py) (`COUNTRY_BRIEF_ARTICLES_PER_COUNTRY`), [`backend/routers/insights.py`](../../backend/routers/insights.py) (`/api/news/lab`).

**ADR:** NLP fields and scoring philosophy — [ADR-001](../adr/001-newscatcher-news-data-fusion.md).

**Layman overview:** [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)

---

## What this layer does (plain language)

Raw Newscatcher results can be **hundreds** of long articles. Before any LLM sees them, this layer:

1. **Throws away** articles that are too short to be useful (word-count gate).
2. **Grades** each remaining article with a **weighted mix** of “is it about the right country?”, “does it mention our economic keywords?”, “is the outlet ranked well?”, “is it recent relative to today?”, “does it look information-dense (NLP summary, entities, numbers)?”
3. **Sorts** by total grade, **removes** near-duplicate titles.
4. **Packages** a small JSON list per country (and sometimes `_general`) for the prompt, trimming snippets so the model fits in context.

This is still **deterministic code** — the same articles and anchor date produce the same scores.

---

## Inputs and outputs

| | |
|---|---|
| **Input** | Raw `articles` from `_call_newscatcher` / bulk fetch; `countries` (ISO3 list); primary `kpi_id` for picking `signal_terms`; optional `kpi_ids` to merge extra keywords; optional `derived_facts` for period / inflection enrichment; `anchor_date` (usually “today” for recency). |
| **Output** | `news_context`: dict keyed by ISO3 (and optionally `"_general"`) with condensed rows (`id`, `title`, `snippet`, `score`, `sentiment`, …). Also used to build the **flattened** `news_prompt_bundle` for `[src:N]` indexing in the LLM. |

---

## Glossary

| Term | Meaning |
|------|--------|
| **Composite score** | Single number 0–1-ish per article: weighted sum of five subscores — **not** comparable to KPI notability scores in [02](02-kpi-notability-scoring.md). |
| **Anchor date** | Reference day for recency (typically today’s date string). Articles far from this date get a lower recency subscore. |
| **`signal_terms`** | Keyword list from `KPI_NEWS_QUERIES`; used to score title/body hits. Multi-KPI mode **merges** terms from all selected KPIs. |
| **NER** | Named-entity recognition from Newscatcher’s NLP payload — we look at `label == "LOC"` to help country matching. |
| **`rank`** | Newscatcher’s source popularity rank — higher rank number → lower subscore in `_score_source_quality`. |
| **Dedup threshold 0.7** | If two titles are ≥70% similar string match, keep only the higher-scoring article. |
| **`near_inflection`** | Flag added when publish date is within **90 days** of a “notable” inflection date inferred from `change_pct` (see `_find_notable_inflection` in source). |

---

## Processing order (pipeline inside `synthesize_news_context`)

1. Merge optional **extra** `signal_terms` when `kpi_ids` is set (multi-KPI dashboard path).
2. **`_score_and_rank_articles`:** word-count filter → score each article → sort desc → dedupe titles.
3. If `derived_facts` provided: **`_align_articles_to_periods`** mutates enriched copies with `_period` and `_near_inflection` (side effect on objects in the scored list).
4. **Bucket** articles by matched country; overflow goes to `_general`.
5. **Truncate** each bucket to `max_per_country` (25 dashboard, 100 country brief, 10 default).

---

## What “quality” means in code

There is no separate quality model. Articles are:

1. Dropped if the HTTP call fails or returns no articles (logged).
2. Filtered by **minimum word count** on `content` or `description`.
3. Assigned a **weighted composite score**, sorted descending, **title-deduplicated**.
4. Optionally **aligned** to calendar periods and “near inflection” (90 days) for enrichment; then **capped per country** (and `_general` bucket).

---

## Caps (`news_client`)

| Constant | Value | Typical use |
|----------|-------|-------------|
| `_ARTICLES_PER_COUNTRY` | 10 | Default `synthesize_news_context` cap |
| `DASHBOARD_INSIGHT_ARTICLES_PER_COUNTRY` | 25 | Dashboard insight streams in `agent.py` |
| `COUNTRY_BRIEF_ARTICLES_PER_COUNTRY` | 100 | Country brief generation |
| `_MIN_WORD_COUNT` | 80 | Minimum words to enter scoring |
| `_DEDUP_SIMILARITY_THRESHOLD` | 0.7 | `difflib.SequenceMatcher` on titles |
| `_RECENCY_LAMBDA` | 0.005 | Exponential decay for recency subscore |

---

## Composite score

**`SCORING_WEIGHTS`:** country 0.30, semantic 0.25, source 0.15, recency 0.15, info_value 0.15.

**Intuition:** Roughly a third of the grade is “is this actually about our country?”, a quarter is “does the vocabulary match the economic topic?”, and the rest rewards reputable outlets, freshness, and text richness (numbers, entities, summary).

Subscores (see verbatim code below):

- **Country:** Title / NER LOC / body / ISO2 fallback.
- **Semantic:** Hits on `signal_terms` from `KPI_NEWS_QUERIES` (+ optional `extra_signal_terms` from multi-KPI merge).
- **Source:** Newscatcher `rank` buckets.
- **Recency:** `exp(-lambda * |anchor_date - published_date|)` in days — **lambda** = `_RECENCY_LAMBDA` 0.005 (gentle decay).
- **Info value:** NLP summary, NER count, sentiment, regex stats in text (`_STAT_PATTERN`).

---

## News Lab API messages

**Source:** [`backend/routers/insights.py`](../../backend/routers/insights.py) lines 88–127.

- No API key: returns `articles: []` and a message to set `NEWSCATCHER_API_KEY`.
- Raw articles returned but synthesized list empty: *"Articles were retrieved but none passed ranking filters (try another KPI or country)."*
- No raw articles: *"No articles returned for this query. Try a different KPI or widen your country selection."*

**Why you might see empty output with raw hits:** Every article failed the **80-word** minimum after fetch, or deduplication removed duplicates and nothing remained — most commonly **word count**.

---

## Verbatim: scoring constants through `synthesize_news_context`

```python
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
```

```python
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
```

**Note:** `_find_notable_inflection` (lines 183–216) picks the date associated with the largest `|change_pct|` vs prior; trailing-year guard skips alignment when the inflection is too recent. See source file for full logic.

---

## Related

- [03 — Newscatcher & queries](03-newscatcher-and-queries.md)
- [05 — Prompts & KPI lenses](05-dashboard-prompts-and-lenses.md)
- [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)
