from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from html import unescape
import posixpath
import xml.etree.ElementTree as ET

from papervisor.core.sanitizers import clean_text as _clean_text
from papervisor.services.doi import extract_doi_from_text
from papervisor.services.isbn import extract_isbn_from_text


_WS_RE = re.compile(r"\s+")


def _resolve_zip_path(opf_path: str | None, href: str) -> str:
    href = (href or '').replace('\\', '/').lstrip('/')
    opf_dir = opf_path.rsplit('/', 1)[0] if opf_path and '/' in opf_path else ''
    if not opf_dir:
        return posixpath.normpath(href).lstrip('/')
    return posixpath.normpath(posixpath.join(opf_dir, href)).lstrip('/')


@dataclass(frozen=True)
class EpubMetadata:
    title: str
    authors: str
    publisher: str
    year: str
    isbn: str
    doi: str


def extract_epub_cover(file_path: str) -> tuple[bytes, str] | None:
    """Extract embedded EPUB cover image bytes.

    Returns (data, ext) where ext is one of: .jpg/.png/.webp.
    """

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            container_xml = _read_zip_text(zf, 'META-INF/container.xml')
            if not container_xml:
                return None

            root = ET.fromstring(container_xml)
            rootfile = root.find('.//{*}rootfile')
            opf_path = rootfile.attrib.get('full-path') if rootfile is not None else None
            if not opf_path:
                return None

            opf_xml = _read_zip_text(zf, opf_path)
            if not opf_xml:
                return None

            opf_root = ET.fromstring(opf_xml)

            cover_id: str | None = None
            for meta in opf_root.findall('.//{*}meta'):
                name = (meta.attrib.get('name') or '').strip().lower()
                if name == 'cover':
                    cover_id = (meta.attrib.get('content') or '').strip() or None
                    if cover_id:
                        break

            cover_href: str | None = None
            # EPUB3 often uses properties="cover-image" on the manifest item.
            for item in opf_root.findall('.//{*}item'):
                props = (item.attrib.get('properties') or '').lower()
                if 'cover-image' in props:
                    cover_href = (item.attrib.get('href') or '').strip() or None
                    if cover_href:
                        break

            if not cover_href and cover_id:
                for item in opf_root.findall('.//{*}item'):
                    if (item.attrib.get('id') or '').strip() == cover_id:
                        cover_href = (item.attrib.get('href') or '').strip() or None
                        if cover_href:
                            break

            # Fallback 1: first image in manifest
            if not cover_href:
                for item in opf_root.findall('.//{*}item'):
                    href = (item.attrib.get('href') or '').strip()
                    if not href:
                        continue
                    media_type = (item.attrib.get('media-type') or '').strip().lower()
                    href_l = href.lower()
                    if media_type.startswith('image/') or href_l.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
                        cover_href = href
                        break

            # Fallback 2: first image file in zip (last resort)
            if not cover_href:
                try:
                    names = [n for n in zf.namelist() if not n.endswith('/')]
                    for n in names:
                        nl = n.lower()
                        if nl.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')) and 'meta-inf/' not in nl:
                            cover_href = n
                            break
                except Exception:
                    cover_href = None

            if not cover_href:
                return None

            # Resolve path relative to OPF location.
            cover_path = _resolve_zip_path(opf_path, cover_href)

            try:
                data = zf.read(cover_path)
            except Exception:
                return None
            if not data:
                return None

            lower = cover_href.lower()
            if lower.endswith('.png'):
                return (data, '.png')
            if lower.endswith('.webp'):
                return (data, '.webp')
            if lower.endswith('.jpeg') or lower.endswith('.jpg'):
                return (data, '.jpg')
            if lower.endswith('.gif'):
                # Store as png/jpg is more work; keep as png-like for preview handling.
                return (data, '.png')

            # Fallback by magic header
            if data.startswith(b'\x89PNG\r\n\x1a\n'):
                return (data, '.png')
            if data[:3] == b'\xff\xd8\xff':
                return (data, '.jpg')
            if data[:4] == b'RIFF' and b'WEBP' in data[:16]:
                return (data, '.webp')
            return None
    except Exception:
        return None


def _read_zip_text(zf: zipfile.ZipFile, path: str) -> str | None:
    try:
        with zf.open(path) as f:
            return f.read().decode('utf-8', errors='ignore')
    except Exception:
        return None


def _first_text(root: ET.Element, xpath: str) -> str:
    node = root.find(xpath)
    return _clean_text(node.text or '') if node is not None else ''


def _all_text(root: ET.Element, xpath: str) -> list[str]:
    out: list[str] = []
    for n in root.findall(xpath):
        t = _clean_text(n.text or '')
        if t:
            out.append(t)
    return out


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def extract_epub_metadata(file_path: str) -> EpubMetadata:
    """Best-effort metadata extraction from an EPUB container.

    Reads META-INF/container.xml -> OPF package document.
    """

    title = authors = publisher = year = isbn = doi = ''

    with zipfile.ZipFile(file_path, 'r') as zf:
        container_xml = _read_zip_text(zf, 'META-INF/container.xml')
        if not container_xml:
            return EpubMetadata(title='', authors='', publisher='', year='', isbn='', doi='')

        try:
            root = ET.fromstring(container_xml)
        except Exception:
            return EpubMetadata(title='', authors='', publisher='', year='', isbn='', doi='')

        rootfile = root.find('.//{*}rootfile')
        opf_path = rootfile.attrib.get('full-path') if rootfile is not None else None
        if not opf_path:
            return EpubMetadata(title='', authors='', publisher='', year='', isbn='', doi='')

        opf_xml = _read_zip_text(zf, opf_path)
        if not opf_xml:
            return EpubMetadata(title='', authors='', publisher='', year='', isbn='', doi='')

        try:
            opf_root = ET.fromstring(opf_xml)
        except Exception:
            return EpubMetadata(title='', authors='', publisher='', year='', isbn='', doi='')

        # Common EPUB metadata fields are in dc:* elements.
        title = _first_text(opf_root, './/{*}title')
        author_list = _all_text(opf_root, './/{*}creator')
        authors = '; '.join(author_list)
        publisher = _first_text(opf_root, './/{*}publisher')
        date = _first_text(opf_root, './/{*}date')
        m = _YEAR_RE.search(date)
        if m:
            year = m.group(1)

        # Identifiers may include ISBN/DOI in various forms.
        for node in opf_root.findall('.//{*}identifier'):
            txt = _clean_text(node.text or '')
            if not txt:
                continue
            if not isbn:
                found = extract_isbn_from_text(txt)
                if found:
                    isbn = found
            if not doi:
                found_doi = extract_doi_from_text(txt)
                if found_doi:
                    doi = found_doi
            if isbn and doi:
                break

        # Fallback: scan the OPF document text.
        if not isbn:
            found = extract_isbn_from_text(opf_xml)
            if found:
                isbn = found
        if not doi:
            found_doi = extract_doi_from_text(opf_xml)
            if found_doi:
                doi = found_doi

    return EpubMetadata(
        title=title,
        authors=authors,
        publisher=publisher,
        year=year,
        isbn=isbn,
        doi=doi,
    )
