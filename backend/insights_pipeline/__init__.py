"""Reusable insights stage library.

Boundary rules:
- This package can be imported by `backend.country_brief` and `backend.lab`.
- This package must not import `backend.country_brief` or `backend.lab`.
- Product-specific orchestration belongs to product packages (for example:
  country brief aggregation/composition).
- Preferred stage imports are under `backend.insights_pipeline.stages`.
"""

