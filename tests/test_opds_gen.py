import os
import sys

# Add the project root to the sys path
sys.path.insert(0, '/home/pmmsoares/Documents/Python/PaperVisor')

from papervisor.services.opds import get_all_papers, generate_acquisition_feed
from papervisor.services.markers import get_markers_for_papers

def test_opds_generation():
    print("Testing OPDS generation...")
    # Get a user id (assuming 1 is admin)
    user_id = 1
    papers = get_all_papers(user_id=user_id, limit=5)
    
    if not papers:
        print("No papers found. Cannot test.")
        return
        
    paper_ids = [str(p.id) for p in papers]
    print(f"Fetched {len(papers)} papers.")
    try:
        paper_markers_map = get_markers_for_papers(user_id=user_id, paper_ids=paper_ids)
        print("Successfully fetched markers map:")
        for pid, markers in paper_markers_map.items():
            print(f" Paper {pid}: {[m.name for m in markers]}")
            
        xml = generate_acquisition_feed(
            feed_id="test",
            title="Test Feed",
            papers=papers,
            base_url="http://localhost:8000",
            self_href="http://localhost:8000/opds",
            paper_markers_map=paper_markers_map
        )
        print("\nGenerated XML snippet:")
        print(xml[:1000])
        if "http://papervisor.app/markers" in xml:
            print("\nSUCCESS: Found marker scheme in XML!")
        else:
            print("\nWARNING: Did not find marker scheme in XML (maybe papers have no markers?)")
            
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_opds_generation()
