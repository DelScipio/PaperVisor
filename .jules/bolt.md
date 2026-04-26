
## 2024-05-18 - Single Query Dashboard Counting
**Learning:** `get_dashboard_counts` previously queried `total`, `completed`, `favorites`, and `to_read` sequentially using `session.execute` and `select(func.count())` which scaled poorly as UI hits refreshed frequently.
**Action:** Replaced sequential queries with a single aggregation using `func.count` and `func.sum(case(...))` directly applied on `base.with_only_columns(...)` to prevent implicit Cartesian products with `subquery()`.
