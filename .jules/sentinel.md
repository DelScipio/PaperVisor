## 2026-05-03 - Add upload file size limits
**Vulnerability:** Unrestricted file uploads leading to Denial of Service via memory exhaustion.
**Learning:** NiceGUI's ui.upload() allows unbounded file uploads by default if max_file_size is not set.
**Prevention:** Always specify max_file_size limit on ui.upload() components.
