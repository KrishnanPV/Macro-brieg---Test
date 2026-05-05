"""Reusable insights stage library.

Boundary rules:
- This package can be imported by `backend.country_brief`, `backend.dashboard`, and `backend.tools`.
- This package must not import `backend.country_brief`, `backend.dashboard`, or `backend.tools`.
- Product-specific orchestration belongs to product packages (for example:
  country brief aggregation/composition).
- Preferred stage imports are under `backend.insights_pipeline.stages`.
"""

