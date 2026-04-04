from __future__ import annotations

"""PaperVisor exception hierarchy.

Goal:
- Make failures explicit and machine-distinguishable (validation vs not found vs permission, etc.)
- Preserve a human-friendly message for UI/API responses
- Allow chaining with `raise ... from e` for debugging
"""


class PaperVisorException(Exception):
    """Base exception for application/domain errors."""


class ValidationException(PaperVisorException):
    """Invalid user input or invalid state for the requested operation."""


class NotFoundException(PaperVisorException):
    """Requested entity does not exist or is not visible to the caller."""


class PermissionDeniedException(PaperVisorException):
    """Caller is authenticated but lacks permission."""


class DatabaseException(PaperVisorException):
    """Database operation failed (connectivity, constraint errors, etc.)."""


class FileSystemException(PaperVisorException):
    """File I/O failed or filesystem state is invalid."""


class MetadataException(PaperVisorException):
    """Metadata extraction/enrichment failed."""


class ExternalServiceException(PaperVisorException):
    """External provider/API call failed (network, rate limit, invalid response)."""
