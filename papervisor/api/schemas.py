"""Pydantic models for REST API request/response bodies.

These models serve as the OpenAPI schema source-of-truth for ``/docs``.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared / generic
# ---------------------------------------------------------------------------

class OkResponse(BaseModel):
    """Generic success response."""
    ok: bool = Field(True, description='Always ``true`` on success.')


class OkBytesResponse(OkResponse):
    """Success response with byte count (file uploads)."""
    bytes: int = Field(..., description='Number of bytes written.', ge=0)


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str


# ---------------------------------------------------------------------------
# Reading state
# ---------------------------------------------------------------------------

class ReadingStateIn(BaseModel):
    """Reading state update request body."""
    progress: float | None = Field(None, description='Reading progress 0.0 – 1.0.', ge=0.0, le=1.0)
    location: str | None = Field(None, description='Current reading location / page identifier.')


class ReadingStateOut(BaseModel):
    """Reading state response."""
    paper_id: str = Field(..., description='Paper identifier.')
    progress: float = Field(0.0, description='Reading progress 0.0 – 1.0.')
    location: str = Field('', description='Current reading location / page identifier.')
    is_completed: bool = Field(False, description='Whether the paper is marked as completed.')
    is_favorite: bool = Field(False, description='Whether the paper is a user favorite.')


class ReadingStateUpdated(OkResponse):
    """Response after updating reading state."""
    paper_id: str = Field(..., description='Paper identifier.')
    progress: float = Field(0.0, description='Reading progress 0.0 – 1.0.')
    location: str = Field('', description='Current reading location / page identifier.')
    is_completed: bool = Field(False, description='Whether the paper is marked as completed.')
    is_favorite: bool = Field(False, description='Whether the paper is a user favorite.')


# ---------------------------------------------------------------------------
# Paper list / pagination
# ---------------------------------------------------------------------------

class PaperSummary(BaseModel):
    """Compact paper representation for list endpoints."""
    id: str
    title: str
    subtitle: str = ''
    file_type: str = 'paper'
    authors: str | None = None
    published_year: str | None = None
    journal: str | None = None
    doi: str | None = None
    isbn: str | None = None
    series: str | None = None
    language: str | None = None
    reading_progress: float = 0.0
    is_completed: bool = False
    is_favorite: bool = False
    is_to_read: bool = False
    open_count_total: int = 0
    file_suffix: str = ''


class PaginationMeta(BaseModel):
    """Pagination metadata."""
    total: int = Field(..., description='Total number of items matching the query.')
    page: int = Field(..., description='Current page number (1-based).', ge=1)
    per_page: int = Field(..., description='Items per page.', ge=1, le=200)
    pages: int = Field(..., description='Total number of pages.')


class PaperListResponse(BaseModel):
    """Paginated paper list."""
    items: list[PaperSummary]
    pagination: PaginationMeta


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    """Health-check response."""
    status: str = Field('ok', description="``ok`` or ``degraded``.")
    version: str | None = Field(None, description='Application version string.')
    database: str | None = Field(None, description="``connected`` or ``error``.")
    disk_free_mb: int | None = Field(None, description='Free disk space in MiB on the library volume.')
    papers_count: int | None = Field(None, description='Total number of papers (quick sanity check).')
