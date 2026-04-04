# OPDS Spec (PaperVisor)

This document summarizes OPDS implementation details, known issues encountered, and the fixes required to ensure compatibility with Boox devices and other strict OPDS readers.

## Goals
- Provide full OPDS 1.2 catalog for books and papers.
- Support devices that cannot use HTTP Basic Auth (Boox).
- Ensure all links carry authentication state (API key).
- Ensure feeds and acquisition links are valid and robust behind reverse proxies.

---

## Facet Contract (Current)

### Reorder facets (`opds:facetGroup="Reorder"`)

Canonical `sort` query values:
- `newest`
- `oldest`
- `az`
- `za`
- `popular`
- `author`

Notes:
- Legacy `sort=title` is removed.
- Reorder facet links are generated from one centralized definition to keep labels/order consistent across feeds.

### Collection facets (`opds:facetGroup="Collection"`)

Top-level acquisition feeds expose filter facets for:
- `All Files` (`/opds/all`)
- `Academic Papers` (`/opds/papers`)
- `Books` (`/opds/books`)

Notes:
- Active collection facet is emitted with `opds:activeFacet="true"`.
- Collection facet links preserve active `sort` values.

---

## Authentication

### Problem
- Boox devices do not support HTTP Basic Auth for OPDS feeds.
- Authentication was failing after the first page because links did not preserve the auth state.

### Fix
- Added per-user OPDS API keys stored in the user profile.
- Added API key query parameter support: `?key=USER_KEY`.
- Propagate the key in **all** navigation, pagination, and acquisition links.

### Notes
- Authentication order: API key first, then HTTP Basic.
- If key is missing or invalid, return 401 with a clear message.

---

## Reverse Proxy / HTTPS

### Problem
- OPDS feeds generated HTTP links behind HTTPS reverse proxies.

### Fix
- Base URL now respects `X-Forwarded-Proto` and `X-Forwarded-Host`.

---

## Namespaces / XML Validity

### Problem
- XML error: `Attribute xmlns:dcterms redefined`.

### Fix
- Removed duplicate namespace declarations in acquisition feeds.
- Namespace registration handled once via `ET.register_namespace`.

---

## Direct File Downloads (Boox Compatibility)

### Problem
- Boox strips query parameters from download URLs.
- Download endpoint used auth and failed without the key.

### Fix
- Serve files from a static mount at `/library_files/` with no auth.
- OPDS acquisition links point to direct static files.

---

## Cover and Thumbnail Images

### Problem
- Covers returned 404 or failed to load on readers.

### Fix
- Mount `/library_files/` so cover paths are publicly accessible.
- Check both JPG and PNG for covers and thumbnails.

---

## Markers / Smart Markers

### Problem
- Markers that are auto-generated (smart rules) showed empty in OPDS.
- OPDS queried only the `paper_markers` table.

### Fix
- OPDS marker lookup now uses the same logic as the UI:
  - `list_shelf_papers_filtered()` handles both manual and smart markers.

---

## Browse By / Filters

### Feature
Added a dedicated “Browse By” section with the following submenus:
- Books Only
- Papers Only
- All Authors
- Book Authors
- Paper Authors
- Series
- Genres
- Journals
- Publication Years

### Fix
- Added `up` link support in navigation feeds.
- Ensured all filter feeds preserve API key.

---

## Download Link Issues (4KB File)

### Problem
- Some downloads were 4KB because the file path resolved to an HTML error page.
- Old absolute paths did not map to the new `/library_files` mount.

### Fix
- Acquisition URL builder now:
  1) Tries to resolve relative to `library_files_dir`.
  2) If already relative, uses it as-is.
  3) If absolute with legacy roots, re-maps by folder name and verifies file exists.

---

## OPDS Feed Link Rules (Compatibility Notes)

- **Every link** must include the API key when using `?key=`.
- Acquisition links must be **direct file URLs** without auth parameters.
- Avoid alternate reader links for devices that prefer direct downloads.
- Use valid OPDS/Atom link types and `rel` values.

---

## Recommended OPDS URL

Use the per-user key from the Profile page:

```
https://your-domain/opds/?key=YOUR_KEY
```

---

## Troubleshooting Checklist

1. **500 error on feed**
   - Check server logs.
   - Ensure `up_href` is supported in navigation feeds.

2. **401 on subpages**
   - Ensure API key is propagated through all links.

3. **Covers not loading**
   - Confirm `/library_files/` mount is active.
   - Verify cover files exist in `_media/covers/`.

4. **Downloads stuck at 4KB**
   - Check file path mapping in OPDS acquisition links.
   - Ensure files are inside the mounted library directory.

---

## Implementation Files

- OPDS HTTP API: `papervisor/api/opds_api.py`
- OPDS Service Layer: `papervisor/services/opds.py`
- Static mounts: `papervisor/static_mount.py`
- User API key management: `papervisor/services/users.py`

---

## Boox Compatibility Summary

To ensure Boox works correctly:
- Always use API key authentication (`?key=`)
- All feeds and pagination links must include the key
- Downloads must be direct static files without auth
- Avoid alternate reader links
- Serve covers/thumbnails as public static files
