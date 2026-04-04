from __future__ import annotations

import base64
import logging
from pathlib import Path

import fitz  # PyMuPDF
import requests

from papervisor.core.config import get_paths


_USER_AGENT = 'PaperVisor/0.1'


def _media_root() -> Path:
    root = get_paths().library_files_dir / '_media'
    root.mkdir(parents=True, exist_ok=True)
    return root


def thumbnail_path_for(*, paper_id: str) -> Path:
    folder = _media_root() / 'thumbs'
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f'{paper_id}.png'


def generate_pdf_first_page_thumbnail(*, file_path: str, paper_id: str, width_px: int = 360) -> Path:
    p = Path(file_path)
    if not p.exists():
        raise ValueError('File not found')
    if p.suffix.lower() != '.pdf':
        raise ValueError('Thumbnail generation is only supported for PDF')

    doc = fitz.open(str(p))
    try:
        if doc.page_count < 1:
            raise ValueError('PDF has no pages')
        page = doc.load_page(0)
        rect = page.rect
        if rect.width <= 0:
            raise ValueError('Invalid PDF page size')
        zoom = max(0.1, float(width_px) / float(rect.width))
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out = thumbnail_path_for(paper_id=paper_id)
        pix.save(str(out))
        return out
    finally:
        doc.close()


def openlibrary_cover_url(isbn: str, *, size: str = 'L') -> str:
    cleaned = ''.join(c for c in (isbn or '') if c.isdigit() or c in {'X', 'x'}).upper()
    if not cleaned:
        raise ValueError('ISBN is required')
    if size not in {'S', 'M', 'L'}:
        size = 'L'
    return f'https://covers.openlibrary.org/b/isbn/{cleaned}-{size}.jpg'


def _ext_from_content_type(content_type: str) -> str:
    ct = str(content_type or '').lower()
    if 'png' in ct:
        return '.png'
    if 'webp' in ct:
        return '.webp'
    if 'jpeg' in ct or 'jpg' in ct:
        return '.jpg'
    return '.jpg'


def _looks_like_html(content_type: str, data: bytes) -> bool:
    ct = str(content_type or '').lower()
    if 'text/html' in ct:
        return True
    head = (data or b'')[:256].lstrip()
    return head.startswith(b'<!doctype html') or head.startswith(b'<html')


def _looks_like_image(data: bytes) -> bool:
    b = data or b''
    if len(b) < 12:
        return False
    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if b.startswith(b'\x89PNG\r\n\x1a\n'):
        return True
    # JPEG: FF D8 FF
    if b.startswith(b'\xff\xd8\xff'):
        return True
    # WEBP: 'RIFF'....'WEBP'
    if b.startswith(b'RIFF') and b[8:12] == b'WEBP':
        return True
    return False


def cover_path_for(*, paper_id: str) -> Path:
    folder = _media_root() / 'covers'
    folder.mkdir(parents=True, exist_ok=True)

    # Prefer an existing cover file if present (supports extracted EPUB covers).
    # If multiple variants exist, pick the newest one.
    candidates: list[Path] = []
    for ext in ['.jpg', '.png', '.webp']:
        p = folder / f'{paper_id}{ext}'
        if p.exists():
            candidates.append(p)

    if candidates:
        try:
            candidates.sort(key=lambda pp: pp.stat().st_mtime_ns, reverse=True)
        except Exception:
            logging.getLogger(__name__).debug('Failed to sort cover candidates by mtime', exc_info=True)
        return candidates[0]

    return folder / f'{paper_id}.jpg'


def preview_image_path_for(*, paper_id: str) -> Path | None:
    """Return the best preview image for a paper.

    Rule: show the most recently updated asset among cover and thumbnail.
    This lets UI behavior match user intent:
    - clicking Regen (thumbnail) makes thumbnail show
    - clicking Fetch (cover) makes cover show
    """

    cover = cover_path_for(paper_id=paper_id)
    thumb = thumbnail_path_for(paper_id=paper_id)

    cover_exists = cover.exists()
    thumb_exists = thumb.exists()

    if cover_exists and not thumb_exists:
        return cover
    if thumb_exists and not cover_exists:
        return thumb
    if not cover_exists and not thumb_exists:
        return None

    try:
        cover_m = cover.stat().st_mtime_ns
    except Exception:
        cover_m = 0
    try:
        thumb_m = thumb.stat().st_mtime_ns
    except Exception:
        thumb_m = 0

    return thumb if thumb_m > cover_m else cover


def _library_files_url_for_path(path: Path) -> str | None:
    """Convert a filesystem path under the configured `library_files_dir` to a URL.

    `papervisor.static_mount.mount_static` mounts that folder at `/library_files`.
    Returning a URL (instead of base64 data URLs) keeps category pages fast:
    - no per-tile disk reads + base64 encoding
    - browser can cache images normally
    """

    try:
        library_root = get_paths().library_files_dir.resolve()
        p = Path(path).resolve()
        rel = p.relative_to(library_root)
    except Exception:
        return None

    try:
        from urllib.parse import quote

        parts = [quote(p) for p in rel.parts]
    except Exception:
        parts = list(rel.parts)

    return '/library_files/' + '/'.join(parts)


def preview_image_url_for(*, paper_id: str) -> str | None:
    """Return a URL for the best preview image (cover/thumbnail) if it exists."""

    prev = preview_image_path_for(paper_id=paper_id)
    if prev is None:
        return None
    try:
        if not prev.exists():
            return None
    except Exception:
        return None

    return _library_files_url_for_path(prev)


def cover_path_for_ext(*, paper_id: str, ext: str) -> Path:
    folder = _media_root() / 'covers'
    folder.mkdir(parents=True, exist_ok=True)
    e = (ext or '.jpg').strip().lower()
    if not e.startswith('.'):
        e = '.' + e
    if e not in {'.jpg', '.jpeg', '.png', '.webp'}:
        e = '.jpg'
    if e == '.jpeg':
        e = '.jpg'
    return folder / f'{paper_id}{e}'


def fetch_and_save_cover(*, isbn: str, paper_id: str, timeout_s: float = 8.0) -> Path:
    # Follow admin-configured provider priority (Admin → API).
    try:
        from papervisor.services.settings import get_book_metadata_fetch_providers

        providers = get_book_metadata_fetch_providers()
    except Exception:
        providers = ['openlibrary', 'google']

    last_error: Exception | None = None
    for prov in providers:
        if prov == 'openlibrary':
            try:
                url = openlibrary_cover_url(isbn)
                resp = requests.get(url, timeout=timeout_s, headers={'User-Agent': _USER_AGENT}, allow_redirects=True)
                if resp.status_code < 400 and resp.content:
                    ct = str(resp.headers.get('content-type') or '')
                    if _looks_like_html(ct, resp.content):
                        continue
                    # Some providers return tiny placeholders; be conservative.
                    if len(resp.content) < 512 or not _looks_like_image(resp.content):
                        continue
                    ext = _ext_from_content_type(ct)
                    out = cover_path_for_ext(paper_id=paper_id, ext=ext)
                    out.write_bytes(resp.content)
                    return out
            except Exception as ex:
                last_error = ex
                continue
        elif prov == 'google':
            try:
                from papervisor.services.google_books import fetch_googlebooks_cover

                data, ext = fetch_googlebooks_cover(isbn=isbn, timeout_s=timeout_s)
                if len(data) < 512 or not _looks_like_image(data):
                    continue
                out = cover_path_for_ext(paper_id=paper_id, ext=ext)
                out.write_bytes(data)
                return out
            except Exception as ex:
                last_error = ex
                continue

    raise ValueError('Cover not found') from last_error


def file_to_data_url(path: Path) -> str:
    data = path.read_bytes()
    suf = path.suffix.lower()
    if suf == '.png':
        mime = 'image/png'
    elif suf == '.webp':
        mime = 'image/webp'
    elif suf == '.jpeg' or suf == '.jpg':
        mime = 'image/jpeg'
    else:
        mime = 'image/jpeg'
    b64 = base64.b64encode(data).decode('ascii')
    return f'data:{mime};base64,{b64}'
