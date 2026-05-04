## 2026-04-23 - [Fix Exception Leakage in ui.notify]
**Vulnerability:** Leaking internal backend Python exceptions to the frontend via `ui.notify(str(ex))`.
**Learning:** In `papervisor/ui/pages/admin/maintenance_panel.py`, errors were being directly passed to the UI. This is a vulnerability because internal backend structure and states can be leaked to malicious users.
**Prevention:** Wrap potential failures in strict try/except blocks, log the raw error securely using `logger.error`, and display a generic error message to the user.
