# Changelog

## 0.11.2 (2026-02-08)

- Release: version bump and container publish

## 0.11.1 (2026-02-08)

- Release: version bump and container publish

## 0.11.0 (2026-01-29)

### UI / Interface Improvements (Section 6)
- **Responsive mobile layout:** CSS custom properties for poster sizing with media-query breakpoints at 600/480 px; sidebar drawers auto-overlay on narrow screens (breakpoint=900)
- **Skeleton loading states:** `skeleton_poster_grid()`, `skeleton_poster_row()`, `skeleton_stats_row()` helper functions with pulsing CSS animation
- **Keyboard navigation:** j/k/arrow keys to navigate posters, Enter to open reader, e for metadata, f for favourite, / to focus search, Escape to deselect
- **List/table view:** toggle between grid and list views; list uses `ui.table` with title, type, progress, status, action columns; preference persisted per user
- **Metadata dialog autocomplete:** authors, publisher, and journal fields now show suggestions from existing data
- **Theme system refactor:** 300+ lines of inline CSS extracted to external `theme.css` with CSS custom properties; dark/light mode toggle on profile page; `:root[data-theme]` attribute switching
- **Drag-and-drop upload:** dropzone wrapper with icon, text, and drag-enter/leave visual feedback
- **Batch operations:** select-mode toggle in top bar, checkboxes on poster tiles, floating batch action bar (toggle favourite/to-read/completed, clear selection)
- **Breadcrumbs:** navigation trail below header showing Dashboard → Library/Marker/View path with clickable ancestor links
- **Empty state illustrations:** per-view icons, titles, subtitles, and CTA buttons when a view has no papers

## 0.10.6 (2026-01-28)

- DOI metadata: add abstract fallback chain (Crossref → Semantic Scholar → PubMed)

## 0.10.5 (2026-01-28)

- Metadata dialog: consolidated Details layout (book/paper), reduced duplication, improved spacing and responsiveness

## 0.10.0 (2026-01-27)

- Admin → OPDS: improved OPDS Server card presentation (status badge, switch toggle, endpoint quick actions)

## 0.0.8 (2026-01-27)

- Performance: serve poster images via `/library_files` URLs (no base64 encoding)
- Performance: infinite scroll/paging for large category views
- Performance: reduce PDF open latency by caching per-user access checks briefly
- Database: add indexes for common category and share permission queries
- Database: SQLite runtime tuning (WAL, busy timeout, cache/temp store)

## 0.0.7 (2026-01-27)

- UI polish: dashboard stats made more visual and responsive
- Poster tiles: slimmer title bar, hover-only corner actions, filled active icons
- Performance: avoid full grid refresh on toggle actions
- Search: squared corners, debounced updates, better tablet layout
- Destructive actions: solid red cancel/delete buttons
- Filters: facet sections now depend on file type and hide when empty

## Unreleased

- Add a name reprocesssing with destiny pattern of destinyy lubrary when moving files to other libary
- add different global pattern to book and paper, and foe each library

In metadata dialog:
- folder in book not showing nothing

In paper:
- random get button in metadata view, remove it.
- remove clicable folder from paper, copy presentation from book to paper, pure text.

- When changing file from paper to book and viseversa recygle already established fields on paper and book because im seeing different wait to show the fileds, fix it.

- add notification on retriving covers, get doi/isbn, get metadatas, saving