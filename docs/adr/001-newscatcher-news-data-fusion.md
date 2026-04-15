# ADR-001: Newscatcher Integration and News-Data Fusion Architecture

**Status:** Accepted (V1 scope) / Partially Deferred (V2 items)

**Date:** 2026-04-06

**Authors:** Johann Sylvester, AI Assistant

---

## Context

The Macrobrief tool displays macroeconomic KPI data from Oxford Economics (via Knoema) and generates LLM-powered insights. To ground the "Implications" section of insights in real-world events, the system integrates Newscatcher News API to fetch recent articles relevant to each KPI and country selection.

The existing V1 integration was minimal: small page sizes, narrow queries, naive article selection (first-N), and no structured pipeline between article retrieval and LLM synthesis. This ADR documents the decisions made to redesign the Newscatcher integration, query construction, and news-data fusion architecture.

---

## Decision Records

### DR-1: Newscatcher NLP Data

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Keep Newscatcher NLP on as first pass + add deeper analysis in the scoring pipeline |
| (b) | Disable Newscatcher NLP entirely and build our own NLP pipeline (spaCy, transformers) |
| (c) | Use Newscatcher NLP only, no additional analysis |

**Chosen:** **(a)** — Use Newscatcher NLP (NER, sentiment, themes) as the first pass; add deeper analysis (embeddings, custom scoring) in V2.

**Rationale:** Newscatcher NLP is included with the API response at no additional cost. It provides NER for country-article matching, sentiment scores for context, and theme classification for filtering. Building our own NLP pipeline would add latency, dependencies, and maintenance burden for V1 with marginal benefit over what Newscatcher already provides. However, Newscatcher's NLP is a black box — we cannot tune entity recognition or sentiment models. V2 should layer on custom analysis for scoring refinement.

**Consequences:**
- `include_nlp_data: true` and `has_nlp: true` in all API queries
- Code depends on Newscatcher's NER entity format (`nlp.ner[].label`, `nlp.ner[].entity_name`)
- Sentiment values come from `nlp.sentiment.content` (range -1.0 to 1.0)
- If Newscatcher changes their NLP output format, our parsing code breaks

---

### DR-2: Article Clustering

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Disable clustering entirely |
| (b) | Always enable clustering |
| (c) | Conditional — enable only within same-year date windows |

**Chosen:** **(c)** — Keep current conditional approach.

**Rationale:** Clustering deduplicates similar articles at the API level, reducing noise and surfacing unique stories. However, it fails across year boundaries (Newscatcher API limitation / known quirk). The conditional approach is pragmatic: enable clustering when the date window stays within one calendar year, omit it when the window crosses years.

**Consequences:**
- Cross-year queries may return more near-duplicate articles
- The scoring pipeline's diversity deduplication step compensates for this gap
- Clustering parameters: `clustering_variable: "content"`, `clustering_threshold: 0.6`

---

### DR-3: Page Size

**Options presented:**

| Option | Description |
|--------|-------------|
| 10 | Current value — small pool, fast but limited selection |
| 100 | Proposed — large pool for scoring pipeline to select from |

**Chosen:** **100**

**Rationale:** A larger pool gives the scoring pipeline better material to select from. No additional API cost per article within a single page request. The scoring pipeline is what prevents the LLM from being overwhelmed — it selects the top N from the pool. With only 10 articles, the scoring pipeline has nothing meaningful to do.

**Consequences:**
- ~10x more data to process per request, but scoring is in-memory and sub-millisecond per article
- Cache entries are larger (100 articles vs 10 stored per cache key)
- More diverse article selection possible

---

### DR-4: Query Construction Approach

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | LLM-generated dynamic queries — use GPT to craft search queries per request |
| (b) | Deterministic standardized queries — hand-authored templates per KPI |
| (c) | Hybrid — LLM refines a base template per request |

**Chosen:** **(b)** — Deterministic standardized queries.

**Discarded:**
- **(a)** LLM-generated queries: adds latency (~1-2s per LLM call), cost (token usage), and non-reproducibility. Debugging becomes harder when queries change between runs for identical inputs. The quality of search queries does not benefit significantly from LLM generation when the KPI topics are well-defined.
- **(c)** Hybrid: complexity not justified for V1. The base templates are already broad enough.

**Rationale:** Reproducibility, debuggability, and zero additional cost. The LLM's role is post-retrieval (insight synthesis), not pre-retrieval (query construction). Queries are inspectable and auditable.

**Consequences:**
- Queries must be manually maintained — when new KPIs are added, corresponding query templates must be authored
- Query quality is deterministic: same KPI + country always produces the same search
- No ability to adapt queries to specific data patterns (e.g., if inflation spiked, we can't dynamically add "rate hike" to the query)

---

### DR-5: Country Embedding in Query String

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Embed country name in query string with AND operator |
| (b) | Use only `countries` API filter + post-retrieval NER matching |
| (c) | Use `LOC_entity_name` API parameter for entity-level filtering |

**Chosen:** **(a)** — Embed country names directly in the query string.

**Rationale:** The `countries` API parameter only filters by **publisher location**, not article content. A US-based Bloomberg article about Saudi GDP would be filtered *out* by `countries=SA`. By embedding the country name in the query string (e.g., `... AND "Saudi Arabia"`), we ensure content relevance regardless of where the publisher is located. The `countries` API filter is kept as a secondary signal.

**Consequences:**
- Queries are longer (country names appended with OR)
- Must maintain `ISO3_TO_NAME` mapping for all supported countries
- Edge cases: "UAE" vs "United Arab Emirates", "USA" vs "United States" — demonyms and abbreviations should be considered
- The `countries` API filter is removed from the payload to avoid over-restricting results (publisher location filtering conflicts with content-based country embedding)

---

### DR-6: Query Breadth Strategy

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Multi-word phrases only (e.g., `"population growth" OR "immigration policy"`) |
| (b) | Single root keywords + wildcards (e.g., `population OR demograph*`) |
| (c) | Broad keywords with `theme` filter as guardrail |

**Chosen:** **(c)** — Broad single keywords + wildcards + theme filter as guardrail.

**Discarded:** **(a)** — Too restrictive. Multi-word phrases miss articles that discuss the concept without using the exact phrase. For example, `"population growth"` misses an article about "population trends" or one that simply discusses "population" in a growth context.

**Rationale:** In information retrieval, the standard approach is to over-retrieve and then filter/rank. The query's job is **recall** (don't miss relevant articles); the scoring pipeline's job is **precision** (separate signal from noise). The `theme` parameter (e.g., `Economics,Finance,Business`) acts as a guardrail that prevents broad single-word terms like `growth` or `debt` from returning irrelevant articles (e.g., "sleep debt", "personal growth").

**Consequences:**
- More articles returned per query (good for scoring pipeline diversity)
- Scoring pipeline must be robust enough to filter noise from broad queries
- Wildcards (e.g., `demograph*`, `unemploy*`) reduce the number of explicit terms needed

---

### DR-7: Fusion Architecture

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Structured NLP Pipeline: NER + sentiment + deterministic scoring → LLM |
| (b) | Statistical Fusion: Option A + correlation analysis, anomaly detection |
| (c) | Full Causal Framework: Granger causality, BERTopic, lead/lag detection |
| (d) | Start with A, architect for B |

**Chosen:** **(d)** — Option A for V1, architected so Option B can be plugged in for V2.

**Discarded for V1:** **(c)** Full Causal Framework — requires significant compute resources, substantial data history (years of article archives), and research effort. Inappropriate for V1 where the primary goal is to ship a working pipeline and validate with users.

**Deferred to V2:** **(b)** Statistical Fusion — correlation between sentiment trends and KPI movements, anomaly detection for news volume spikes, topic modeling via BERTopic or TF-IDF clustering.

**Rationale:** Ship a working pipeline fast, validate with users, then add rigor. The V1 architecture defines clear interfaces (scorer protocol, fusion hooks) that V2 modules can implement without restructuring.

**Consequences:**
- V1 fusion is deterministic and fast (no ML inference, no statistical computation)
- V2 can add statistical modules by implementing the scorer/hook interfaces
- The scoring pipeline has configurable weights that can be tuned based on V1 feedback

---

### DR-8: Real-time vs Batch Processing

**Options presented:**

| Option | Description |
|--------|-------------|
| (a) | Real-time for V1, plan for batch in V2 |
| (b) | Build batch infrastructure now |
| (c) | Hybrid now: batch fetch + NLP, real-time LLM synthesis |

**Chosen:** **(a)** — Real-time for V1.

**Deferred:** Batch pre-processing (daily article indexing, pre-computed sentiment aggregates, SQLite/PostgreSQL storage).

**Rationale:** Keeps V1 simple with minimal infrastructure. For an executive briefing tool, the 3-5 second latency of real-time Newscatcher API calls is acceptable. Batch processing adds infrastructure complexity (scheduler, storage layer, staleness management, cache invalidation) that is not justified until user volume and latency requirements demand it.

**Consequences:**
- Each insight request makes fresh API calls (cached for 1 hour via in-memory TTL cache)
- Repeated requests for the same KPI/country combination within 1 hour are served from cache
- No persistent storage of articles between server restarts
- V2 batch hook interface is defined but not implemented

---

## Open Questions (flagged for team discussion)

### OQ-1: Trailing 365-Day Window Anchor `TODO`

**Current behavior:** Trailing 365 days from "now" (current date at request time).

**Alternative:** Trailing 365 days from the end of the selected data period (e.g., if data ends 2024-Q4, news window = 2024-01-01 to 2024-12-31).

**Impact:** If a user is viewing 2020-2023 data, should the news window cover 2022-2023 (contemporaneous with data end) or 2025-2026 (most recent news regardless of data period)? The answer depends on the primary use case:
- **Real-time monitoring:** anchor to "now" — users want the latest news context regardless of historical data
- **Historical analysis:** anchor to data-end — users want news that was contemporaneous with the data movements they're examining

**V1 decision:** Keep "now" anchor. Revisit once the team clarifies the dominant use case.

### OQ-2: Scoring Pipeline Weights `TODO`

- Should scoring weights be global (same for all KPIs) or KPI-specific (e.g., recency matters more for inflation than population)?
- Should weights be hand-tuned or learned from user feedback on insight quality?
- V1 starts with global hand-tuned weights; the config structure supports per-KPI overrides.

### OQ-3: Article Cap per Country `TODO`

- Current: 5 articles per country in the LLM prompt
- Proposed: 10 articles per country
- Token budget implication: 10 articles x ~250 chars each = ~2,500 chars per country. For 6 GCC countries = ~15,000 chars of news context added to the prompt.
- Need to validate this fits within the model's context window alongside DATA_CONTEXT and system prompt.

---

## V2 Roadmap (deferred items)

| Item | Description | Prerequisite |
|------|-------------|--------------|
| Statistical correlation | Rolling sentiment-KPI correlation using pandas/scipy | Batch article storage |
| Anomaly detection | Flag unusual news volume spikes relative to baseline | Batch article storage |
| Topic modeling | BERTopic or TF-IDF clustering for sub-theme discovery | sentence-transformers dependency |
| Batch pre-processing | Daily job to pre-fetch, score, store articles in SQLite | Infrastructure decision |
| Granger causality | Test whether news sentiment leads or lags KPI movements | 6+ months of archived data |
| Embedding-based scoring | sentence-transformers for semantic relevance scoring | Model hosting decision |
| Source allowlist | Curated list of high-authority economic sources | Manual curation effort |
| A/B weight testing | Compare insight quality across different weight configs | Logging + evaluation framework |
