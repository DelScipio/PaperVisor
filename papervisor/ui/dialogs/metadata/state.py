from dataclasses import dataclass, field
from papervisor.db.models import Paper

@dataclass
class DialogState:
    paper: Paper | None = None
    editing_state: bool = False
    dirty_state: bool = False
    suspend_dirty: int = 0
    fetch_cancel_requested: bool = False
    can_manage_paper_library: bool = False
    desc_expanded: bool = False
    
    locks: dict[str, bool] = field(default_factory=lambda: {
        'title': False,
        'authors': False,
        'year': False,
        'publisher': False,
        'journal': False,
        'doi': False,
        'isbn': False,
        'description': False,
        'genres': False,
        'publication_date': False,
        'language': False,
        'series': False,
        'series_index': False,
        'page_count': False,
        'abstract': False,
        'url': False,
        'volume': False,
        'issue': False,
        'pages': False,
    })
    
    @property
    def is_dirty_suspended(self) -> bool:
        return self.suspend_dirty > 0
        
    @is_dirty_suspended.setter
    def is_dirty_suspended(self, value: bool) -> None:
        if value:
            self.suspend_dirty += 1
        else:
            self.suspend_dirty = max(0, self.suspend_dirty - 1)
    
    def file_type(self) -> str:
        if self.paper:
            return str(self.paper.file_type or 'paper').strip().lower() or 'paper'
        return 'paper'
