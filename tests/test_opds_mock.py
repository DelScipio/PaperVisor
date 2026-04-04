import sys
from xml.etree import ElementTree as ET
sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

try:
    from papervisor.services.opds import generate_acquisition_feed
    from papervisor.services.opds import OPDSFacetLink
    from papervisor.db.models import Paper
    from papervisor.domain import MarkerItem
    from datetime import UTC, datetime
except Exception as e:
    print(f"IMPORT ERROR: {e}")
    sys.exit(1)

def test_no_db():
    print("Testing generate_acquisition_feed with mock data...")
    p1 = Paper(id="1234", title="Test Paper 1", updated_at=datetime.now(UTC), file_path="test.pdf")
    
    m1 = MarkerItem(id="m1", name="Important", icon="star", is_smart=False, scope="all", paper_count=1, owner_user_id=1, visibility="global", is_owned_by_me=True)
    m2 = MarkerItem(id="m2", name="AI", icon="robot", is_smart=True, scope="all", paper_count=1, owner_user_id=1, visibility="global", is_owned_by_me=True)
    
    paper_markers_map = {
        "1234": [m1, m2]
    }
    
    xml = generate_acquisition_feed(
        feed_id="urn:test",
        title="Mock Feed",
        papers=[p1],
        base_url="http://localhost:8000",
        self_href="http://localhost/test",
        paper_markers_map=paper_markers_map
    )
    
    print(xml)
    
    if "Important" in xml and "http://papervisor.app/markers" in xml and "AI" in xml:
        print("\nSUCCESS: Both markers rendered in the XML format!")
    else:
        print("\nFAILURE: Markers missing!")

if __name__ == "__main__":
    test_no_db()


def test_entry_renders_only_first_author() -> None:
    p1 = Paper(
        id="a1",
        title="Author Split Test",
        authors="Alice, Bob; Carol",
        updated_at=datetime.now(UTC),
        file_path="author-test.pdf",
    )

    xml = generate_acquisition_feed(
        feed_id="urn:test:first-author",
        title="First Author Feed",
        papers=[p1],
        base_url="http://localhost:8000",
        self_href="http://localhost/test/first-author",
        paper_markers_map={},
    )

    root = ET.fromstring(xml)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    author_names = [
        (elem.text or '').strip()
        for elem in root.findall('atom:entry/atom:author/atom:name', ns)
        if (elem.text or '').strip()
    ]

    assert author_names == ['Alice']


def test_acquisition_feed_includes_reorder_facets() -> None:
    p1 = Paper(
        id="f1",
        title="Facet Test",
        authors="Alice",
        updated_at=datetime.now(UTC),
        file_path="facet-test.pdf",
    )

    facets = [
        OPDSFacetLink(href="http://localhost/opds/all?sort=az", title="A–Z", active=False),
        OPDSFacetLink(href="http://localhost/opds/all?sort=newest", title="Newest", active=True),
        OPDSFacetLink(
            href="http://localhost/opds/books?sort=newest",
            title="Books",
            facet_group='Collection',
            active=False,
        ),
        OPDSFacetLink(
            href="http://localhost/opds/all?sort=newest",
            title="All Files",
            facet_group='Collection',
            active=True,
        ),
    ]

    xml = generate_acquisition_feed(
        feed_id="urn:test:facets",
        title="Facet Feed",
        papers=[p1],
        base_url="http://localhost:8000",
        self_href="http://localhost/opds/all",
        paper_markers_map={},
        facets=facets,
    )

    root = ET.fromstring(xml)
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'opds': 'http://opds-spec.org/2010/catalog',
    }

    facet_links = root.findall("atom:link[@rel='http://opds-spec.org/facet']", ns)
    assert len(facet_links) == 4

    az_link = next(link for link in facet_links if link.get('title') == 'A–Z')
    newest_link = next(link for link in facet_links if link.get('title') == 'Newest')
    all_files_link = next(link for link in facet_links if link.get('title') == 'All Files')
    books_link = next(link for link in facet_links if link.get('title') == 'Books')

    assert az_link.get('{http://opds-spec.org/2010/catalog}facetGroup') == 'Reorder'
    assert az_link.get('{http://opds-spec.org/2010/catalog}activeFacet') is None
    assert newest_link.get('{http://opds-spec.org/2010/catalog}facetGroup') == 'Reorder'
    assert newest_link.get('{http://opds-spec.org/2010/catalog}activeFacet') == 'true'
    assert all_files_link.get('{http://opds-spec.org/2010/catalog}facetGroup') == 'Collection'
    assert all_files_link.get('{http://opds-spec.org/2010/catalog}activeFacet') == 'true'
    assert books_link.get('{http://opds-spec.org/2010/catalog}facetGroup') == 'Collection'
    assert books_link.get('{http://opds-spec.org/2010/catalog}activeFacet') is None


def test_marker_categories_use_marker_names_as_term() -> None:
    p1 = Paper(
        id="m-term-1",
        title="Marker Term Test",
        authors="Alice",
        updated_at=datetime.now(UTC),
        file_path="marker-term-test.pdf",
    )

    markers = [
        MarkerItem(id="marker-id-1", name="Important", icon="star", is_smart=False, scope="all", paper_count=1, owner_user_id=1, visibility="global", is_owned_by_me=True),
        MarkerItem(id="marker-id-2", name="AI", icon="robot", is_smart=True, scope="all", paper_count=1, owner_user_id=1, visibility="global", is_owned_by_me=True),
    ]

    xml = generate_acquisition_feed(
        feed_id="urn:test:marker-term",
        title="Marker Term Feed",
        papers=[p1],
        base_url="http://localhost:8000",
        self_href="http://localhost/opds/all",
        paper_markers_map={"m-term-1": markers},
    )

    root = ET.fromstring(xml)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}
    marker_categories = [
        el for el in root.findall('atom:entry/atom:category', ns)
        if el.get('scheme') == 'http://papervisor.app/markers'
    ]

    assert len(marker_categories) == 2
    terms = {el.get('term') for el in marker_categories}
    labels = {el.get('label') for el in marker_categories}

    assert terms == {'Important', 'AI'}
    assert labels == {'Important', 'AI'}
    assert 'marker-id-1' not in terms
    assert 'marker-id-2' not in terms


def test_summary_falls_back_to_abstract_when_subtitle_missing() -> None:
    paper = Paper(
        id="summary-fallback-1",
        title="Summary Fallback Test",
        subtitle=None,
        abstract="This abstract should appear in summary.",
        description=None,
        updated_at=datetime.now(UTC),
        file_path="summary-fallback.pdf",
    )

    xml = generate_acquisition_feed(
        feed_id="urn:test:summary-fallback",
        title="Summary Fallback Feed",
        papers=[paper],
        base_url="http://localhost:8000",
        self_href="http://localhost/opds/all",
        paper_markers_map={},
    )

    root = ET.fromstring(xml)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    summary = root.find('atom:entry/atom:summary', ns)
    content = root.find('atom:entry/atom:content', ns)

    assert summary is not None
    assert (summary.text or '').strip() == "This abstract should appear in summary."
    assert content is not None
    assert "This abstract should appear in summary." in (content.text or '')


def test_content_includes_description_and_abstract_when_both_exist() -> None:
    paper = Paper(
        id="summary-fallback-2",
        title="Combined Content Test",
        subtitle="Short subtitle",
        abstract="Abstract body.",
        description="Longer description body.",
        updated_at=datetime.now(UTC),
        file_path="combined-content.pdf",
    )

    xml = generate_acquisition_feed(
        feed_id="urn:test:combined-content",
        title="Combined Content Feed",
        papers=[paper],
        base_url="http://localhost:8000",
        self_href="http://localhost/opds/all",
        paper_markers_map={},
    )

    root = ET.fromstring(xml)
    ns = {'atom': 'http://www.w3.org/2005/Atom'}

    summary = root.find('atom:entry/atom:summary', ns)
    content = root.find('atom:entry/atom:content', ns)

    assert summary is not None
    assert (summary.text or '').strip() == "Short subtitle"
    assert content is not None
    content_text = (content.text or '').strip()
    assert "Longer description body." in content_text
    assert "Abstract body." in content_text
