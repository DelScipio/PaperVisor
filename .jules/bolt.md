## 2024-05-18 - Prevent overfetching large text blobs in SQLAlchemy lists
**Learning:** Using `load_only` in SQLAlchemy queries (e.g., `select(Paper).options(load_only(...))`) significantly improves performance and reduces memory usage when listing many items, specifically by preventing the database from fetching and transmitting large string columns like abstracts and descriptions when only basic metadata is needed for UI lists.
**Action:** Always apply `.options(load_only(...))` for read-heavy list queries where only a subset of columns (like ID, title, etc.) is required to instantiate domain objects.

## 2024-05-18 - Single Query Dashboard Counting
**Learning:** `get_dashboard_counts` previously queried `total`, `completed`, `favorites`, and `to_read` sequentially using `session.execute` and `select(func.count())` which scaled poorly as UI hits refreshed frequently.
**Action:** Replaced sequential queries with a single aggregation using `func.count` and `func.sum(case(...))` directly applied on `base.with_only_columns(...)` to prevent implicit Cartesian products with `subquery()`.
