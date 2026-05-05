## 2026-05-03 - Add upload file size limits
**Vulnerability:** Unrestricted file uploads leading to Denial of Service via memory exhaustion.
**Learning:** NiceGUI's ui.upload() allows unbounded file uploads by default if max_file_size is not set.
**Prevention:** Always specify max_file_size limit on ui.upload() components.

## 2026-04-23 - [Fix Exception Leakage in ui.notify]
**Vulnerability:** Leaking internal backend Python exceptions to the frontend via `ui.notify(str(ex))`.
**Learning:** In `papervisor/ui/pages/admin/maintenance_panel.py`, errors were being directly passed to the UI. This is a vulnerability because internal backend structure and states can be leaked to malicious users.
**Prevention:** Wrap potential failures in strict try/except blocks, log the raw error securely using `logger.error`, and display a generic error message to the user.

## 2025-05-02 - Sentinel: Fail Securely on Path Traversal
**Vulnerability:** Path Traversal bypass via error conditions in `download_paper_file` (`papervisor/ui/dialogs/metadata/actions.py`).
**Learning:** `p.resolve()` inside a try-catch block failed open (caught exception and `pass`ed). This allowed bypassing the strict `library_root` containment check if an attacker could supply a path that raised an exception during resolution (e.g. strict OS-level exceptions for invalid components), resulting in arbitrary file download.
**Prevention:** Always fail securely by denying access and returning early whenever an exception is caught during critical security validations like path traversal prevention. Narrow exception handlers to specific expected types (`OSError`, `ValueError`, `RuntimeError`) rather than bare `except Exception` to avoid silencing unrelated bugs. Use the already-resolved path for the download call to close potential symlink-after-check race conditions.
