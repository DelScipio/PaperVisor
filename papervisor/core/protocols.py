from __future__ import annotations

"""Service-layer protocols (structural typing contracts).

These ``Protocol`` classes describe the public API of each major domain
service.  They are *not* enforced at runtime — they exist for:

1.  **Documentation**: a single place to see the full contract.
2.  **Static type-checking**: ``mypy`` / Pyright will flag deviations.
3.  **Testability**: test doubles only need to satisfy the Protocol.

Concrete implementations remain as module-level functions in
``papervisor.services.*`` for now.  A future refactor may wrap them
into classes that inherit from these Protocols.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from papervisor.services.isbn import IsbnMetadata


# ---------------------------------------------------------------------------
# ISBN providers (pre-existing)
# ---------------------------------------------------------------------------

class IsbnDiscoveryProvider(Protocol):
    def __call__(self, *, title: str, author: str | None) -> str | None: ...


class IsbnMetadataProvider(Protocol):
    def __call__(self, isbn: str) -> IsbnMetadata: ...


# ---------------------------------------------------------------------------
# Paper service
# ---------------------------------------------------------------------------

class PaperReader(Protocol):
    """Read-side operations for papers."""

    def get_paper(self, *, paper_id: str) -> object | None: ...

    def list_papers(
        self,
        *,
        user_id: int | None = None,
        library_id: str | None = None,
        limit: int | None = 50,
    ) -> list: ...

    def list_recent_papers(
        self,
        *,
        user_id: int | None = None,
        library_id: str | None = None,
        limit: int | None = 50,
    ) -> list: ...

    def search_papers(
        self,
        *,
        query: str,
        mode: str = 'all',
        user_id: int | None = None,
        library_id: str | None = None,
        limit: int = 500,
    ) -> list: ...

    def list_papers_filtered(
        self,
        *,
        user_id: int | None = None,
        library_id: str | None = None,
        library_ids: list[str] | None = None,
        query: str | None = None,
        mode: str = 'all',
        filters: object | None = None,
        sort: str = 'default',
        limit: int | None = 500,
    ) -> list: ...

    def get_dashboard_counts(
        self,
        *,
        user_id: int | None = None,
        library_id: str | None = None,
    ) -> dict[str, int]: ...

    def is_favorite(self, *, user_id: int, paper_id: str) -> bool: ...
    def is_to_read(self, *, user_id: int, paper_id: str) -> bool: ...


class PaperWriter(Protocol):
    """Write-side operations for papers."""

    def create_paper_record(self, *, library_id: str | None, file_type: str, file_path: str, title: str, **kwargs) -> object: ...
    def update_paper_metadata(self, *, paper_id: str, title: str, **kwargs) -> object: ...
    def move_paper_to_library(self, *, paper_id: str, library_id: str | None, **kwargs) -> object: ...
    def delete_paper(self, *, paper_id: str, permanent: bool = False) -> None: ...
    def restore_paper(self, *, paper_id: str) -> None: ...
    def purge_paper(self, *, paper_id: str) -> None: ...
    def record_opened(self, *, paper_id: str) -> None: ...
    def reset_open_counts(self, *, paper_id: str) -> None: ...
    def set_reading_state(self, *, paper_id: str, progress: float | None = None, location: str | None = None) -> object | None: ...
    def toggle_completed(self, *, paper_id: str) -> bool: ...
    def toggle_favorite(self, *, paper_id: str, user_id: int | None = None) -> bool: ...
    def toggle_to_read(self, *, paper_id: str, user_id: int | None = None) -> bool: ...


class PaperImporter(Protocol):
    """File import operations."""

    def save_upload_to_temp(self, *, filename: str, content: bytes) -> Path: ...
    def commit_staged_import(self, *, library_id: str, file_type: str, staged_path: str, original_filename: str) -> object: ...
    def attach_staged_file_to_paper(self, *, paper_id: str, staged_path: str, original_filename: str, **kwargs) -> object: ...
    def import_file(self, *, library_id: str, file_type: str, filename: str, content: bytes) -> object: ...


# ---------------------------------------------------------------------------
# Library service
# ---------------------------------------------------------------------------

class LibraryService(Protocol):
    """CRUD operations for libraries."""

    def list_libraries(self, *, owner_user_id: int | None = None) -> list: ...
    def list_libraries_for_user(self, *, user_id: int) -> list: ...
    def create_library(self, *, owner_user_id: int, name: str, description: str = '', icon: str = 'menu_book') -> object: ...
    def update_library(self, *, user_id: int, library_id: str, name: str, description: str, icon: str) -> object: ...
    def delete_library(self, *, user_id: int, library_id: str) -> None: ...


# ---------------------------------------------------------------------------
# User service
# ---------------------------------------------------------------------------

class UserService(Protocol):
    """User management operations."""

    def count_users(self) -> int: ...
    def list_users(self) -> list: ...
    def get_user_by_username(self, *, username: str) -> object | None: ...
    def authenticate(self, *, username: str, password: str) -> object | None: ...
    def create_user(self, *, username: str, password: str, is_admin: bool = False) -> object: ...
    def set_password(self, *, user_id: int, new_password: str) -> None: ...
    def set_username(self, *, user_id: int, new_username: str) -> None: ...
    def delete_user(self, *, user_id: int) -> None: ...
    def generate_opds_api_key(self, user_id: int) -> str: ...
    def revoke_opds_api_key(self, user_id: int) -> None: ...


# ---------------------------------------------------------------------------
# Media service
# ---------------------------------------------------------------------------

class MediaService(Protocol):
    """Cover / thumbnail / preview operations."""

    def thumbnail_path_for(self, *, paper_id: str) -> Path: ...
    def cover_path_for(self, *, paper_id: str) -> Path: ...
    def preview_image_url_for(self, *, paper_id: str) -> str | None: ...
    def fetch_and_save_cover(self, *, isbn: str, paper_id: str, timeout_s: float = 8.0) -> Path: ...
