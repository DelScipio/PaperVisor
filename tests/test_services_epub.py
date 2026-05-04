from __future__ import annotations

import zipfile
from pathlib import Path

from papervisor.services.epub import extract_epub_cover


def _write_epub(tmp_path: Path, *, opf_xml: str, files: dict[str, bytes], opf_path: str = 'OPS/content.opf') -> Path:
    epub_path = tmp_path / 'sample.epub'

    container_xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
        "<rootfiles>"
        f"<rootfile full-path='{opf_path}' media-type='application/oebps-package+xml'/>"
        "</rootfiles>"
        "</container>"
    )

    with zipfile.ZipFile(epub_path, 'w') as zf:
        zf.writestr('META-INF/container.xml', container_xml)
        zf.writestr(opf_path, opf_xml)
        for name, data in files.items():
            zf.writestr(name, data)

    return epub_path


def test_extract_epub_cover_fallback_reads_archive_path_when_opf_is_nested(tmp_path: Path) -> None:
    opf_xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>"
        "<metadata/>"
        "<manifest>"
        "<item id='chap1' href='text/ch1.xhtml' media-type='application/xhtml+xml'/>"
        "</manifest>"
        "</package>"
    )
    jpg = b'\xff\xd8\xff\xe0fake-jpeg'

    epub = _write_epub(
        tmp_path,
        opf_xml=opf_xml,
        files={
            'OPS/text/ch1.xhtml': b'<html></html>',
            'OPS/images/cover.jpg': jpg,
        },
    )

    extracted = extract_epub_cover(str(epub))

    assert extracted is not None
    data, ext = extracted
    assert data == jpg
    assert ext == '.jpg'


def test_extract_epub_cover_strips_fragment_and_query_from_manifest_href(tmp_path: Path) -> None:
    opf_xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<package xmlns='http://www.idpf.org/2007/opf' version='3.0'>"
        "<metadata/>"
        "<manifest>"
        "<item id='cover' href='images/cover.png?cache=1#xywh=0,0,10,10' media-type='image/png' properties='cover-image'/>"
        "</manifest>"
        "</package>"
    )
    png = b'\x89PNG\r\n\x1a\n\x00\x00\x00IEND'

    epub = _write_epub(
        tmp_path,
        opf_xml=opf_xml,
        files={
            'OPS/images/cover.png': png,
        },
    )

    extracted = extract_epub_cover(str(epub))

    assert extracted is not None
    data, ext = extracted
    assert data == png
    assert ext == '.png'
