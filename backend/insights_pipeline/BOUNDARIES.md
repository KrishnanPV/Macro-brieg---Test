# Insights Pipeline Boundaries

This package is the reusable stage library for generating macro insights.

## Allowed dependencies
- `backend.country_brief -> backend.insights_pipeline`
- `backend.dashboard -> backend.insights_pipeline`
- `backend.tools -> backend.insights_pipeline`

## Forbidden dependencies
- `backend.insights_pipeline -> backend.country_brief`
- `backend.insights_pipeline -> backend.dashboard`
- `backend.insights_pipeline -> backend.tools`

## Scope
- Keep reusable building blocks here: stage modules, runtime helpers, prompt loading.
- Keep product-specific orchestration and output contracts outside this package.

