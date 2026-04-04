from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PaperItem:
    id: str
    title: str
    subtitle: str
    reading_progress: float = 0.0
    is_completed: bool = False
    is_favorite: bool = False
    is_to_read: bool = False

    open_count_total: int = 0
    open_count_since_reset: int = 0
    file_suffix: str = ''
    file_type: str = 'paper'


@dataclass(frozen=True)
class LibraryItem:
    id: str
    name: str
    slug: str
    description: str = ''
    icon: str = 'menu_book'
    paper_count: int = 0

    # Sharing metadata (optional; used by UI)
    owner_user_id: int | None = None
    owner_username: str | None = None
    scope: str = 'private'  # private | shared | global
    shared_role: str | None = None  # reader | editor
    is_shared_with_me: bool = False
    is_owned_by_me: bool = False


@dataclass(frozen=True)
class MarkerItem:
    id: str
    name: str
    icon: str = 'category'
    is_smart: bool = False
    scope: str = 'all'
    paper_count: int = 0
    
    # Ownership and visibility
    owner_user_id: int | None = None
    visibility: str = 'private'
    is_owned_by_me: bool = False
