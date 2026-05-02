## 2025-05-02 - Sentinel: Fail Securely on Path Traversal
**Vulnerability:** Path Traversal bypass via error conditions in `download_paper_file` (`papervisor/ui/dialogs/metadata/actions.py`).
**Learning:** `p.resolve()` inside a try-catch block failed open (caught exception and `pass`ed). This allowed bypassing the strict `library_root` containment check if an attacker could supply a path that raised an exception during resolution (e.g. strict OS-level exceptions for invalid components), resulting in arbitrary file download.
**Prevention:** Always fail securely by denying access and returning early whenever an exception is caught during critical security validations like path traversal prevention.
