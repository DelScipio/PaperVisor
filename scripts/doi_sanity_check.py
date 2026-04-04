from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from papervisor.services.doi import extract_doi_from_text


def extract_doi_from_pdf_like_text(text: str) -> str | None:
    """Mimic the extra normalization passes used in extract_doi_from_pdf.

    This lets us sanity-check behavior without requiring real PDFs/PyMuPDF.
    """

    if not text or not text.strip():
        return None

    candidates = (
        text,
        text.replace("\n", ""),
        " ".join(text.split()).replace(" / ", "/"),
    )

    for candidate in candidates:
        doi = extract_doi_from_text(candidate)
        if doi:
            return doi
    return None


def _check(name: str, got: str | None, expected: str) -> None:
    if got != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {got!r}")


def main() -> int:
    # These cases cover the common PDF quirks: line wraps and spacing around '/'.
    cases: list[tuple[str, str, str]] = [
        (
            "simple",
            "This paper DOI is 10.1000/xyz123 and it is important.",
            "10.1000/xyz123",
        ),
        (
            "uppercase_suffix",
            "DOI 10.1000/ABC.DEF-123 appears in caps.",
            "10.1000/ABC.DEF-123",
        ),
        (
            "split_newline_after_slash",
            "DOI: 10.1000/\nxyz123",
            "10.1000/xyz123",
        ),
        (
            "split_whitespace_around_slash",
            "Find it at 10.1000 / xyz123 in the header",
            "10.1000/xyz123",
        ),
        (
            "bracketed",
            "[10.1000/xyz123]",
            "10.1000/xyz123",
        ),
        (
            "trailing_punct",
            "See 10.1000/xyz123).",
            "10.1000/xyz123",
        ),
        (
            "doi_url",
            "https://doi.org/10.1000/xyz123",
            "10.1000/xyz123",
        ),
    ]

    for name, text, expected in cases:
        got = extract_doi_from_pdf_like_text(text)
        _check(name, got, expected)

    print(f"OK: {len(cases)} DOI cases passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
