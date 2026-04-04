from __future__ import annotations

"""Compatibility façade for papers services.

This module was split into smaller modules to make the codebase easier to
maintain. Keep existing imports working by re-exporting the public API.

Split modules:
- papervisor.services.papers_search
- papervisor.services.papers_crud
- papervisor.services.papers_import
- papervisor.services.papers_metadata

Internal helpers:
- papervisor.services.papers_files
"""

from papervisor.services.papers_crud import (
    create_paper_record,
    delete_paper,
    get_paper,
    move_paper_to_library,
    record_opened,
    reset_open_counts,
    set_reading_state,
    toggle_completed,
    toggle_favorite,
    toggle_to_read,
    update_paper_metadata,
    update_paper_updated_at,
)
from papervisor.services.papers_import import (
    ImportedPaper,
    RenameResult,
    attach_staged_file_to_paper,
    commit_staged_import,
    import_file,
    rename_papers_to_match_patterns,
    save_upload_to_temp,
    replace_paper_file,
)
from papervisor.services.papers_metadata import ImportMetadata, extract_import_metadata
from papervisor.services.papers_search import (
    PaperFilters,
    count_papers_filtered,
    get_dashboard_counts,
    is_favorite,
    is_to_read,
    list_books,
    list_continue_reading,
    list_favorite_papers,
    list_most_opened,
    list_paper_filter_facets,
    list_papers,
    list_papers_filtered,
    list_recent_papers,
    list_to_read_papers,
    search_papers,
)

__all__ = [
    # Types
    'ImportedPaper',
    'RenameResult',
    'PaperFilters',
    'ImportMetadata',
    # Search/listing
    'list_paper_filter_facets',
    'list_papers',
    'list_recent_papers',
    'search_papers',
    'list_papers_filtered',
    'count_papers_filtered',
    'list_books',
    'get_dashboard_counts',
    'list_favorite_papers',
    'list_to_read_papers',
    'list_continue_reading',
    'list_most_opened',
    'is_favorite',
    'is_to_read',
    # CRUD/state
    'get_paper',
    'create_paper_record',
    'update_paper_metadata',
    'update_paper_updated_at',
    'move_paper_to_library',
    'delete_paper',
    'record_opened',
    'reset_open_counts',
    'set_reading_state',
    'toggle_completed',
    'toggle_favorite',
    'toggle_to_read',
    # Import
    'rename_papers_to_match_patterns',
    'save_upload_to_temp',
    'commit_staged_import',
    'attach_staged_file_to_paper',
    'import_file',
    'replace_paper_file',
    # Metadata helpers
    'extract_import_metadata',
]

# NOTE: The original monolithic implementation that used to live in this file
# was split into smaller modules and removed to avoid duplication/confusion.
# Use git history if you need to reference the previous version.
