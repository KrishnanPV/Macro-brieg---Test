# Engineering Decisions Log

Append-only log of notable design decisions. Add a new dated entry per decision; do not edit past entries.

## 2026-06-04 — Data-driven oil gating for 1A title and 3A overlay

**Decision**
- Replace the hardcoded GCC list (`_GCC_CODES`) as the *display* gate for two
  oil-specific exhibits with a single data-availability signal: whether Oxford
  returns an oil/non-oil real-GDP split for the country.

**Signal**
- `_has_oil_split(results_raw)` in `backend/country_brief/pipeline.py` returns
  True when KPI 2 / KPI 12 carry renderable `oil, real` / `non-oil, real`
  series points. This is computed once after the KPI fetch.

**Affected exhibits**
- **1A (KPI 12 — Real GDP Growth)**: when there is no oil/non-oil split, the
  chart title drops the `(Total / Oil / Non-Oil)` qualifier and renders as
  `Real GDP Growth` (only the total line plots anyway).
- **3A (KPI 13 — Trade, Exports & Imports)**: the Brent oil-price overlay is
  only fetched/attached when the country has an oil/non-oil split. The overlay
  series itself is available per-country in LCU for nearly everyone, so its own
  availability is *not* a valid discriminator — the GDP split is.

**Rationale**
- Generalizes beyond GCC to any oil exporter Oxford models with a split
  (e.g. Nigeria, Iraq, Algeria, Kazakhstan, Norway), and avoids a stale
  hardcoded country list.
- `_GCC_CODES` is retained only where it gates *fetch scope* (force-including
  KPI 2 for GCC in automatic mode), not display.
