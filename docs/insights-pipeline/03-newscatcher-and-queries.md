# 03 — Newscatcher API defaults, date range, and KPI queries

**Primary source:** [`backend/services/news_client.py`](../../backend/services/news_client.py)  
**Query registry:** [`backend/models/kpi_registry.py`](../../backend/models/kpi_registry.py) — `KPI_NEWS_QUERIES`  
**Config:** [`backend/config.py`](../../backend/config.py) — `NEWSCATCHER_API_KEY`, `NEWSCATCHER_URL`, `NEWSCATCHER_TIMEOUT`

**ADR:** [ADR-001: Newscatcher integration and news-data fusion](../adr/001-newscatcher-news-data-fusion.md) (NLP fields, design tradeoffs).

**Layman overview:** [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)

---

## What this layer does (plain language)

Upstream you already computed **derived facts**, so we know the **earliest** and **latest** dates in the user’s chart. This layer asks an external **news search API** (Newscatcher) for English articles whose **text matches** a KPI-specific query and falls in a **date window** aligned to that chart (plus a forward buffer — see below). It does **not** rank articles here; ranking happens in [`synthesize_news_context`](../../backend/services/news_client.py) ([doc 04](04-article-scoring-and-filtering.md)).

---

## Inputs and outputs (this file’s responsibilities)

| Step | Input | Output |
|------|--------|--------|
| `fetch_news_for_kpi` | `kpi_id`, ISO3 `countries[]`, `derived_facts` | Raw `articles[]` from API (or cached) |
| `fetch_news_bulk` | `kpi_ids[]`, `countries`, `derived_facts` | One merged raw list for all KPIs |
| `_call_newscatcher` | Resolved query string, themes, `from_`, `to_` | HTTP POST JSON response parsed to articles |

**Deterministic:** query text, dates, and caching are code rules. **Non-deterministic:** whatever articles exist in Newscatcher’s index for that day (external data).

---

## Glossary

| Term | Meaning |
|------|--------|
| **`q`** | The search query string sent to Newscatcher — built from `query_template` with `{country}` filled in. |
| **`theme`** | Optional comma-separated filter passed through to the API (e.g. Economics, Finance). |
| **`signal_terms`** | Keywords used **later** for semantic scoring — not the same as the full boolean query in `q`, but related vocabulary. |
| **Clustering** | Newscatcher can group similar articles. We **disable** clustering when the date range **crosses calendar years** (`clustering_enabled = not crosses_year`) to avoid odd grouping across year boundaries. |
| **+183 days** | After taking the max date from the KPI data, we extend the **end** of the news window by half a year so recent journalism can still match indicators that lag. |
| **Clamp** | Force `from_` ≥ 2019-01-01 and `to_` ≤ today so we never ask for impossible dates. |

---

## How we move from data to HTTP (decision chain)

1. **Need dates:** `_derive_date_range(derived_facts)` scans every `series_facts[].earliest/latest` date → `range_start`, `range_end`. If nothing found, default to “last 365 days ending today.”
2. **Extend end:** Add **183 days** to `range_end` (news can appear slightly after the last data point).
3. **Clamp:** `_clamp_date_range` enforces 2019 floor and “not in the future.”
4. **Pick query:** Single-KPI → full `KPI_NEWS_QUERIES[kpi_id].query_template`. Bulk → `_build_mega_query` ORs all `signal_terms` across KPIs into one broad query.
5. **Resolve countries:** Replace `{country}` with `"Saudi Arabia" OR "Qatar"` style clauses from `ISO3_TO_NAME`.
6. **POST** with defaults + `q`, `from_`, `to_`, optional `theme`, `clustering_enabled` flag.

---

## Default payload (`NEWSCATCHER_DEFAULTS`)

**Lines 128–137** — merged into every POST body:

| Key | Value |
|-----|--------|
| `lang` | `"en"` |
| `search_in` | `"title_content"` |
| `include_translation_fields` | `False` |
| `by_parse_date` | `False` |
| `sort_by` | `"relevancy"` |
| `ranked_only` | `True` |
| `from_rank` / `to_rank` | `1` / `999999` |
| `page` / `page_size` | `1` / `100` |
| `include_nlp_data` | `True` |
| `has_nlp` | `True` |
| `is_paid_content` | `False` |
| `clustering_variable` | `"content"` |
| `clustering_threshold` | `0.6` |

Per-request overrides/additions:

- `q` — resolved query string
- `from_`, `to_` — date bounds (strings `YYYY-MM-DD`)
- `clustering_enabled` — `not crosses_year` (if `from_`/`to_` parse to different calendar years, clustering is **disabled**)
- `theme` — optional; from KPI `themes` string (comma-separated), or merged themes for bulk

**Authentication:** Header `x-api-token: <NEWSCATCHER_API_KEY>`. Empty articles if key missing or placeholder `your_newscatcher_api_key_here`.

---

## Country placeholder resolution (`_resolve_country_placeholder`)

**Lines 172–180:** `{country}` in templates becomes `OR`-joined quoted English names from `ISO3_TO_NAME` for the requested ISO3 list. If no names resolve, country clause fragments are stripped from the template.

---

## Date range derivation and clamp

| Step | Function / constant | Behavior |
|------|---------------------|----------|
| Data window | `_derive_date_range(derived_facts)` | Min/max of `earliest`/`latest` dates across series; if none, last 365 days to today |
| Forward extension | `fetch_news_for_kpi` / `fetch_news_bulk` | `range_end += 183 days` after derivation |
| Earliest allowed | `_NEWSCATCHER_EARLIEST` | `2019-01-01` |
| Clamp | `_clamp_date_range` | Start ≥ 2019-01-01, end ≤ today; if invalid, fall back to ~365 days ending today |

---

## Single-KPI fetch (`fetch_news_for_kpi`)

**Lines 303–326:** Looks up `KPI_NEWS_QUERIES[kpi_id]`, derives dates, clamps, optionally returns cache hit, else `_call_newscatcher(nq.query_template, countries, nq.themes, from_date, to_date)`.

---

## Bulk fetch (`fetch_news_bulk`)

**Lines 351–425:** For all `kpi_ids` present in `KPI_NEWS_QUERIES`, builds a **mega query** via `_build_mega_query`, same date logic as single KPI, sets `page_size` to `min(page_size, 1000)`, separate cache key `__bulk__`.

### `_build_mega_query` (lines 329–348)

- Collects every `signal_terms` entry across KPIs; multi-word terms are quoted.
- `query_template = "(" + " OR ".join(sorted(all_terms)) + ") AND ({country})"`
- `themes` = sorted union of comma-split theme tokens from all KPIs.

---

## `KPI_NEWS_QUERIES` (verbatim)

**Source:** [`backend/models/kpi_registry.py`](../../backend/models/kpi_registry.py) lines 312–472.

```python
@dataclass
class KpiNewsQuery:
    query_template: str
    themes: str
    signal_terms: list[str] = field(default_factory=list)


KPI_NEWS_QUERIES: dict[str, KpiNewsQuery] = {
    "1": KpiNewsQuery(
        query_template=(
            '(GDP OR "gross domestic product" OR econom* OR "economic output" '
            'OR industr* OR manufactur* OR services OR agriculture '
            'OR "private sector" OR "public sector" OR "sectoral composition" '
            'OR "value added" OR "economic activity" OR output OR production) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["GDP", "gross domestic product", "sector", "industry",
                       "manufacturing", "services", "agriculture", "output",
                       "value added", "economic activity", "production"],
    ),
    "2": KpiNewsQuery(
        query_template=(
            '(GDP OR "non-oil" OR "oil sector" OR "oil GDP" '
            'OR "economic diversification" OR diversif* OR OPEC '
            'OR "oil revenue" OR "oil production" OR petrochemical '
            'OR hydrocarbon OR "oil dependence" OR "energy sector" '
            'OR "non-oil growth" OR "private sector" OR "oil price" '
            'OR "crude oil" OR "Vision 2030") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["oil", "non-oil", "diversification", "OPEC",
                       "hydrocarbon", "petrochemical", "oil revenue",
                       "oil production", "crude", "energy sector"],
    ),
    "3": KpiNewsQuery(
        query_template=(
            '(GDP OR growth OR recession OR expansion OR contraction '
            'OR slowdown OR "economic growth" OR "GDP growth" '
            'OR "economic performance" OR "quarterly growth" '
            'OR "annual growth" OR recovery OR downturn '
            'OR "growth rate" OR "economic outlook" OR stagnation OR boom) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["GDP", "growth", "recession", "expansion",
                       "contraction", "recovery", "downturn", "stagnation",
                       "economic performance", "economic outlook"],
    ),
    "4": KpiNewsQuery(
        query_template=(
            '(FDI OR "foreign direct investment" OR "foreign investment" '
            'OR "capital flows" OR "capital inflows" OR "investment climate" '
            'OR "foreign ownership" OR "cross-border" OR invest* '
            'OR greenfield OR "mergers and acquisitions" OR "joint venture" '
            'OR "free zone" OR "special economic zone" OR privatiz* '
            'OR "sovereign wealth") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business,Politics",
        signal_terms=["FDI", "foreign direct investment", "capital flows",
                       "investment", "greenfield", "free zone",
                       "sovereign wealth", "privatization", "cross-border"],
    ),
    "5": KpiNewsQuery(
        query_template=(
            '(unemploy* OR "labor market" OR "labour market" '
            'OR "job creation" OR "job losses" OR workforce OR employment '
            'OR jobless OR hiring OR layoff* OR "labor reform" '
            'OR "labour reform" OR "labor force" OR "youth unemployment" '
            'OR wage OR nationalization OR Saudization OR Emiratization '
            'OR "labor participation") '
            'AND ({country})'
        ),
        themes="Economics,Politics,Business",
        signal_terms=["unemployment", "employment", "labor market",
                       "job creation", "workforce", "hiring", "layoff",
                       "wage", "labor reform", "Saudization", "Emiratization"],
    ),
    "6": KpiNewsQuery(
        query_template=(
            '(consumption OR "consumer spending" OR "household expenditure" '
            'OR "household spending" OR "retail sales" OR retail '
            'OR "purchasing power" OR "consumer confidence" '
            'OR "domestic demand" OR "consumer demand" '
            'OR "disposable income" OR "cost of living" OR spending '
            'OR "consumer sentiment" OR "private consumption" '
            'OR "household income") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Business",
        signal_terms=["consumption", "consumer spending", "retail",
                       "household expenditure", "purchasing power",
                       "consumer confidence", "domestic demand",
                       "disposable income", "cost of living"],
    ),
    "7": KpiNewsQuery(
        query_template=(
            '(inflation OR CPI OR "consumer price" OR "price index" '
            'OR "central bank" OR "monetary policy" OR "interest rate" '
            'OR deflation OR disinflation OR "cost of living" '
            'OR "food prices" OR "energy prices" OR "price stability" '
            'OR "base rate" OR "repo rate" OR "price growth" '
            'OR inflationary OR stagflation) '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["inflation", "CPI", "consumer price", "interest rate",
                       "monetary policy", "central bank", "deflation",
                       "cost of living", "price index", "stagflation"],
    ),
    "8": KpiNewsQuery(
        query_template=(
            '(debt OR "external debt" OR "sovereign debt" '
            'OR "government borrowing" OR "bond issuance" '
            'OR "credit rating" OR "fiscal deficit" OR "debt-to-GDP" '
            'OR "sovereign bond" OR "public debt" OR "national debt" '
            'OR borrowing OR "credit default" OR "debt sustainability" '
            'OR "fiscal consolidation" OR "debt restructuring" '
            'OR sukuk OR eurobond OR "budget deficit" OR "fiscal balance") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["debt", "sovereign debt", "bond", "credit rating",
                       "fiscal deficit", "debt-to-GDP", "borrowing",
                       "sukuk", "eurobond", "debt sustainability"],
    ),
    "9": KpiNewsQuery(
        query_template=(
            '(population OR demograph* OR census OR immigra* OR emigra* '
            'OR migra* OR "birth rate" OR "fertility rate" '
            'OR "workforce growth" OR "labor force growth" OR expatriat* '
            'OR "visa reform" OR residency OR "population growth" '
            'OR "population change" OR "population decline" OR aging '
            'OR urbanization OR "housing demand" OR nationalization '
            'OR citizen*) '
            'AND ({country})'
        ),
        themes="Economics,Politics,Business",
        signal_terms=["population", "demographic", "immigration", "census",
                       "migration", "birth rate", "fertility", "expatriate",
                       "visa reform", "urbanization", "workforce growth"],
    ),
    "10": KpiNewsQuery(
        query_template=(
            '("government expenditure" OR "government spending" '
            'OR "fiscal policy" OR "national accounts" OR "public spending" '
            'OR budget OR "fiscal balance" OR "public investment" '
            'OR "capital expenditure" OR "current expenditure" '
            'OR revenue OR "tax revenue" OR "fiscal stimulus" '
            'OR austerity OR subsid* OR "public finance" '
            'OR "budget deficit" OR "budget surplus") '
            'AND ({country})'
        ),
        themes="Economics,Finance,Politics",
        signal_terms=["government expenditure", "fiscal policy", "budget",
                       "public spending", "tax revenue", "austerity",
                       "subsidy", "fiscal stimulus", "public finance"],
    ),
}
```

---

## Response shape

`_call_newscatcher` and bulk handler accept either top-level `articles` or `clusters[].articles` (lines 257–263, 413–418).

## Related

- Article **scoring** after fetch: [04 — Article scoring & filtering](04-article-scoring-and-filtering.md)
- Full pipeline: [06 — End-to-end pipeline (layman)](06-end-to-end-pipeline-layman.md)
