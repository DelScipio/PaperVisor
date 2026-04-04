"""Typed UI page state for the main index page.

Replaces the raw ``dict[str, str | None]`` that was used to manage
navigation, filter, and paging state.  Every field has a concrete type
so IDE auto-complete and ``mypy`` work naturally.

Helper methods encapsulate the JSON serialization / parsing that was
previously scattered throughout ``index.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from typing import Sequence

from papervisor.services.papers_search import PaperFilters


# ---- default constants -----------------------------------------------

PAGE_SIZE: int = 120


# ---- dataclass -------------------------------------------------------

@dataclass
class PageState:
    """Mutable page-level state for the main index view."""

    # Navigation
    view: str = 'dashboard'
    library_id: str | None = None
    marker_id: str | None = None

    # Previous view (for returning from search overlay)
    prev_view: str = 'dashboard'
    prev_library_id: str | None = None
    prev_marker_id: str | None = None

    # UI Options
    display_mode: str = 'grid'

    # Search
    search_query: str = ''
    search_mode: str = 'all'

    # Sidebar collapse toggles
    nav_navigation_collapsed: bool = False
    nav_libraries_collapsed: bool = False
    nav_markers_collapsed: bool = False
    nav_auto_markers_collapsed: bool = False

    # Filters
    filters_library_id: str = ''
    filters_library_ids: list[str] = field(default_factory=list)
    filters_file_type: str = 'all'
    filters_sort: str = 'default'
    filters_favorites_only: bool = False
    filters_to_read_only: bool = False
    filters_has_doi: bool = False
    filters_has_isbn: bool = False
    filters_missing_id: bool = False
    filters_completed_only: bool = False
    filters_tag_names: list[str] = field(default_factory=list)
    filters_marker_ids: list[str] = field(default_factory=list)
    filters_authors: list[str] = field(default_factory=list)
    filters_journals: list[str] = field(default_factory=list)
    filters_publishers: list[str] = field(default_factory=list)
    filters_series: list[str] = field(default_factory=list)
    filters_languages: list[str] = field(default_factory=list)
    filters_genres: list[str] = field(default_factory=list)
    filters_year_min: int | None = None
    filters_year_max: int | None = None

    # Paging
    list_limit: int = PAGE_SIZE




    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def set_view(self, view: str, library_id: str | None = None, marker_id: str | None = None) -> None:
        """Switch the active view, saving the current one for search-return."""
        view = (view or '').strip().lower() or 'dashboard'

        if view != 'search':
            self.prev_view = view
            self.prev_library_id = library_id
            self.prev_marker_id = marker_id

        self.view = view
        self.library_id = library_id
        self.marker_id = marker_id
        self.reset_paging()

        # Clear filters that don't apply to the new view.
        if view in {'library', 'dashboard'}:
            self.filters_library_ids = []
        if view in {'marker', 'dashboard'}:
            self.filters_marker_ids = []

    def restore_from_search(self) -> None:
        """Return to the view that was active before search."""
        self.set_view(self.prev_view, self.prev_library_id, self.prev_marker_id)

    # ------------------------------------------------------------------
    # Paging helpers
    # ------------------------------------------------------------------

    def get_limit(self) -> int:
        return max(PAGE_SIZE, min(5000, self.list_limit))

    def reset_paging(self) -> None:
        self.list_limit = PAGE_SIZE

    def load_more(self) -> None:
        self.list_limit = self.get_limit() + PAGE_SIZE

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def effective_library_ids(self) -> list[str] | None:
        """Resolve the active library scope from navigation + filter state."""
        if self.view == 'library' and self.library_id:
            return [self.library_id]

        if self.filters_library_ids:
            return list(self.filters_library_ids)

        # Backward compat: old single-library filter.
        single = (self.filters_library_id or '').strip()
        return [single] if single else None

    def effective_filters(self) -> PaperFilters:
        """Build a ``PaperFilters`` dataclass from current filter state."""
        ft = (self.filters_file_type or 'all').strip().lower()
        return PaperFilters(
            file_type=None if ft == 'all' else ft,
            favorites_only=self.filters_favorites_only,
            to_read_only=self.filters_to_read_only,
            has_doi=self.filters_has_doi,
            has_isbn=self.filters_has_isbn,
            missing_id=self.filters_missing_id,
            completed_only=self.filters_completed_only,
            tag_names=list(self.filters_tag_names) if self.filters_tag_names else None,
            marker_ids=list(self.filters_marker_ids) if self.filters_marker_ids else None,
            authors=list(self.filters_authors) if self.filters_authors else None,
            journals=list(self.filters_journals) if self.filters_journals else None,
            publishers=list(self.filters_publishers) if self.filters_publishers else None,
            series=list(self.filters_series) if self.filters_series else None,
            languages=list(self.filters_languages) if self.filters_languages else None,
            genres=list(self.filters_genres) if self.filters_genres else None,
            year_min=self.filters_year_min,
            year_max=self.filters_year_max,
        )

    def active_sort_key(self) -> str:
        return (self.filters_sort or 'default').strip().lower() or 'default'

    # ------------------------------------------------------------------
    # Legacy dict bridge (for components that still use dict[str, str|None])
    # ------------------------------------------------------------------

    def get(self, key: str, default: str | None = None) -> str | None:
        """Dict-compatible ``get()`` — returns stringified value."""
        if not hasattr(self, key):
            return default
        val = getattr(self, key)
        if isinstance(val, bool):
            return '1' if val else '0'
        if isinstance(val, list):
            return json.dumps(val)
        if val is None:
            return default
        return str(val)

    def __getitem__(self, key: str) -> str | None:
        return self.get(key)

    def __setitem__(self, key: str, value: str | None) -> None:
        """Dict-compatible ``__setitem__`` — coerces strings into typed fields."""
        if not hasattr(self, key):
            # Allow unknown keys (e.g. filters_preset_name) as dynamic attrs.
            object.__setattr__(self, key, value)
            return
        field_map = {f.name: f for f in fields(self)}
        if key not in field_map:
            object.__setattr__(self, key, value)
            return
        ft = field_map[key].type
        try:
            if ft in ('bool',):
                object.__setattr__(self, key, str(value or '0') == '1')
            elif ft in ('int',):
                object.__setattr__(self, key, int(value) if value not in (None, '') else PAGE_SIZE)
            elif ft in ('int | None',):
                object.__setattr__(self, key, int(value) if value not in (None, '') else None)
            elif 'list[str]' in str(ft):
                object.__setattr__(self, key, _parse_json_list(value))
            elif ft in ('str | None',):
                object.__setattr__(self, key, value)
            else:
                object.__setattr__(self, key, value if value is not None else '')
        except (ValueError, TypeError):
            object.__setattr__(self, key, value)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def to_dict(self) -> dict[str, str | None]:
        """Serialize to the string-keyed dict format used by ``filters_panel`` etc."""
        d: dict[str, str | None] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if isinstance(val, bool):
                d[f.name] = '1' if val else '0'
            elif isinstance(val, list):
                d[f.name] = json.dumps(val)
            elif val is None:
                d[f.name] = None
            else:
                d[f.name] = str(val)
        return d

    def update_from_dict(self, d: dict[str, str | None]) -> None:
        """Apply mutations from the legacy dict back into typed fields."""
        for key, raw in d.items():
            self[key] = raw


# ---- private helpers ---------------------------------------------------

def _parse_json_list(raw: str | None) -> list[str]:
    """Safely parse a JSON string as a list of strings."""
    s = str(raw or '[]').strip()
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return []
