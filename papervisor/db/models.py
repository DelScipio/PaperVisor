from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from papervisor.db.base import Base

if TYPE_CHECKING:
    pass  # all forward refs resolved via string annotations


# ---------------------------------------------------------------------------
# FK ondelete behaviour reference
# ---------------------------------------------------------------------------
#
# | FK Column                           | ondelete    | Rationale
# |-------------------------------------|-------------|-------------------------------------------
# | Paper.library_id → libraries.id     | SET NULL    | Papers survive library deletion (orphaned)
# | Library.owner_user_id → users.id    | SET NULL    | Library survives owner deletion (unowned)
# | LibraryShare.library_id             | CASCADE     | Share removed when library deleted
# | LibraryShare.shared_with_user_id    | CASCADE     | Share removed when recipient deleted
# | LibraryShare.shared_by_user_id      | SET NULL    | Audit trail preserved if sharer deleted
# | PaperShare.paper_id                 | CASCADE     | Share removed when paper deleted
# | PaperShare.shared_with_user_id      | CASCADE     | Share removed when recipient deleted
# | PaperShare.shared_by_user_id        | SET NULL    | Audit trail preserved if sharer deleted
# | LibraryNamingPattern.library_id     | CASCADE     | Pattern removed with library
# | UserSetting.user_id                 | CASCADE     | Settings removed when user deleted
# | PaperFavorite.user_id / .paper_id   | CASCADE     | Junction row removed from either side
# | PaperToRead.user_id / .paper_id     | CASCADE     | Junction row removed from either side
# | Marker.owner_user_id → users.id     | CASCADE     | User's markers removed on deletion (*)
# | PaperMarker.paper_id / .marker_id   | CASCADE     | Junction row removed from either side
# | PaperTag.paper_id / .tag_id         | CASCADE     | Junction row removed from either side
#
# (*) Note: Marker.owner_user_id CASCADE means deleting a user also deletes
#     their *shared* markers.  If shared markers should survive, change to
#     SET NULL in a future migration.
# ---------------------------------------------------------------------------


class Paper(Base):
    __tablename__ = 'papers'

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    library_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('libraries.id', ondelete='SET NULL'), nullable=True)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default='paper')
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(512), nullable=False, default='')
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    authors: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    published_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    journal: Mapped[str | None] = mapped_column(String(512), nullable=True)
    publisher: Mapped[str | None] = mapped_column(String(512), nullable=True)
    isbn: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Book-specific (best-effort; may be null for non-books)
    description: Mapped[str | None] = mapped_column(String(8192), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    genres: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    series: Mapped[str | None] = mapped_column(String(256), nullable=True)
    series_index: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Paper-specific (best-effort; may be null for non-papers)
    abstract: Mapped[str | None] = mapped_column(String(8192), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    volume: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pages: Mapped[str | None] = mapped_column(String(64), nullable=True)
    keywords: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Reading state (server-side)
    reading_progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reading_location: Mapped[str] = mapped_column(String(2048), nullable=False, default='')
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Analytics / dashboard
    open_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_count_since_reset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    open_count_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    # Soft delete (NULL = not deleted)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)

    # --- relationships ---
    library: Mapped[Library | None] = relationship('Library', back_populates='papers', lazy='select')
    markers: Mapped[list[Marker]] = relationship('Marker', secondary='paper_markers', back_populates='papers', lazy='select', viewonly=True)
    tags: Mapped[list[Tag]] = relationship('Tag', secondary='paper_tags', back_populates='papers', lazy='select', viewonly=True)
    favorites: Mapped[list[PaperFavorite]] = relationship('PaperFavorite', back_populates='paper', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    to_read_entries: Mapped[list[PaperToRead]] = relationship('PaperToRead', back_populates='paper', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    paper_shares: Mapped[list[PaperShare]] = relationship('PaperShare', back_populates='paper', lazy='select', cascade='all, delete-orphan', passive_deletes=True)


class Library(Base):
    __tablename__ = 'libraries'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(String(1024), nullable=False, default='')
    icon: Mapped[str] = mapped_column(String(64), nullable=False, default='menu_book')

    # Sharing/ownership
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # private | shared | global
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default='private')

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    owner: Mapped[User | None] = relationship('User', back_populates='owned_libraries', lazy='select')
    papers: Mapped[list[Paper]] = relationship('Paper', back_populates='library', lazy='select')
    naming_patterns: Mapped[list[LibraryNamingPattern]] = relationship('LibraryNamingPattern', back_populates='library', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    shares: Mapped[list[LibraryShare]] = relationship('LibraryShare', back_populates='library', lazy='select', cascade='all, delete-orphan', passive_deletes=True)


class LibraryShare(Base):
    __tablename__ = 'library_shares'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    library_id: Mapped[str] = mapped_column(String(36), ForeignKey('libraries.id', ondelete='CASCADE'), nullable=False)
    shared_with_user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    shared_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # pending | accepted
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    # reader | editor
    role: Mapped[str] = mapped_column(String(16), nullable=False, default='reader')

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    library: Mapped[Library] = relationship('Library', back_populates='shares', lazy='select')
    shared_with_user: Mapped[User] = relationship('User', foreign_keys=[shared_with_user_id], lazy='select')
    shared_by_user: Mapped[User | None] = relationship('User', foreign_keys=[shared_by_user_id], lazy='select')


class PaperShare(Base):
    __tablename__ = 'paper_shares'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey('papers.id', ondelete='CASCADE'), nullable=False)
    shared_with_user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    shared_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # pending | accepted | declined
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    paper: Mapped[Paper] = relationship('Paper', back_populates='paper_shares', lazy='select')
    shared_with_user: Mapped[User] = relationship('User', foreign_keys=[shared_with_user_id], lazy='select')
    shared_by_user: Mapped[User | None] = relationship('User', foreign_keys=[shared_by_user_id], lazy='select')


class NamingPattern(Base):
    __tablename__ = 'naming_patterns'

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    pattern: Mapped[str] = mapped_column(String(1024), nullable=False, default='')
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class LibraryNamingPattern(Base):
    __tablename__ = 'library_naming_patterns'

    __table_args__ = (UniqueConstraint('library_id', 'file_type', name='uq_library_naming_patterns_library_type'),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    library_id: Mapped[str] = mapped_column(String(36), ForeignKey('libraries.id', ondelete='CASCADE'), nullable=False)
    # paper | book
    file_type: Mapped[str] = mapped_column(String(16), nullable=False, default='paper')
    pattern: Mapped[str] = mapped_column(String(1024), nullable=False, default='')
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )

    # --- relationships ---
    library: Mapped[Library] = relationship('Library', back_populates='naming_patterns', lazy='select')


class AppSetting(Base):
    __tablename__ = 'app_settings'

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048), nullable=False, default='')
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False
    )


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opds_api_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    owned_libraries: Mapped[list[Library]] = relationship('Library', back_populates='owner', lazy='select')
    settings: Mapped[list[UserSetting]] = relationship('UserSetting', back_populates='user', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    favorites: Mapped[list[PaperFavorite]] = relationship('PaperFavorite', back_populates='user', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    to_read_entries: Mapped[list[PaperToRead]] = relationship('PaperToRead', back_populates='user', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    markers: Mapped[list[Marker]] = relationship('Marker', back_populates='owner', lazy='select', cascade='all, delete-orphan', passive_deletes=True)
    audit_events: Mapped[list[AuditLogEvent]] = relationship(
        'AuditLogEvent',
        back_populates='user',
        lazy='select',
        passive_deletes=True,
    )
    hidden_global_libraries_entries: Mapped[list[HiddenGlobalLibrary]] = relationship('HiddenGlobalLibrary', back_populates='user', lazy='select', cascade='all, delete-orphan', passive_deletes=True)


class AuditLogEvent(Base):
    __tablename__ = 'audit_log_events'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Event classification
    level: Mapped[str] = mapped_column(String(16), nullable=False, default='info')
    category: Mapped[str] = mapped_column(String(32), nullable=False, default='auth')
    action: Mapped[str] = mapped_column(String(64), nullable=False, default='event')

    # Human-readable summary and optional structured payload
    message: Mapped[str] = mapped_column(String(1024), nullable=False, default='')
    details_json: Mapped[str | None] = mapped_column(String(4096), nullable=True)

    # Actor/request context
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- relationships ---
    user: Mapped[User | None] = relationship('User', back_populates='audit_events', lazy='select')


class UserSetting(Base):
    __tablename__ = 'user_settings'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048), nullable=False, default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    user: Mapped[User] = relationship('User', back_populates='settings', lazy='select')


class PaperFavorite(Base):
    __tablename__ = 'paper_favorites'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    user: Mapped[User] = relationship('User', back_populates='favorites', lazy='select')
    paper: Mapped[Paper] = relationship('Paper', back_populates='favorites', lazy='select')


class HiddenGlobalLibrary(Base):
    __tablename__ = 'hidden_global_libraries'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    library_id: Mapped[str] = mapped_column(String(36), ForeignKey('libraries.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    user: Mapped[User] = relationship('User', back_populates='hidden_global_libraries_entries', lazy='select')
    library: Mapped[Library] = relationship('Library', lazy='select')


class PaperToRead(Base):
    __tablename__ = 'paper_to_read'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    user: Mapped[User] = relationship('User', back_populates='to_read_entries', lazy='select')
    paper: Mapped[Paper] = relationship('Paper', back_populates='to_read_entries', lazy='select')


class Marker(Base):
    __tablename__ = 'markers'

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[str] = mapped_column(String(64), nullable=False, default='category')

    # Ownership and visibility
    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    # private | shared | global
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default='private')

    # Manual marker vs smart/special marker
    is_smart: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Scope: all | book | paper (Content type)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default='all')
    # JSON (string) of rules for smart markers
    rules_json: Mapped[str] = mapped_column(String(8192), nullable=False, default='')

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    owner: Mapped[User | None] = relationship('User', back_populates='markers', lazy='select')
    papers: Mapped[list[Paper]] = relationship('Paper', secondary='paper_markers', back_populates='markers', lazy='select', viewonly=True)


class PaperMarker(Base):
    __tablename__ = 'paper_markers'

    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True)
    marker_id: Mapped[str] = mapped_column(String(36), ForeignKey('markers.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    paper: Mapped[Paper] = relationship('Paper', lazy='select', viewonly=True)
    marker: Mapped[Marker] = relationship('Marker', lazy='select', viewonly=True)


class Tag(Base):
    __tablename__ = 'tags'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    papers: Mapped[list[Paper]] = relationship('Paper', secondary='paper_tags', back_populates='tags', lazy='select', viewonly=True)


class PaperTag(Base):
    __tablename__ = 'paper_tags'

    paper_id: Mapped[str] = mapped_column(String(64), ForeignKey('papers.id', ondelete='CASCADE'), primary_key=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # --- relationships ---
    paper: Mapped[Paper] = relationship('Paper', lazy='select', viewonly=True)
    tag: Mapped[Tag] = relationship('Tag', lazy='select', viewonly=True)
