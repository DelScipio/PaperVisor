from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from nicegui import ui

from papervisor.domain import PaperItem
from papervisor.services.media import preview_image_url_for
from papervisor.services.papers import toggle_completed, toggle_favorite, toggle_to_read


# ── Empty-state helpers ──────────────────────────────────────────────────

_EMPTY_STATE_MAP: dict[str, tuple[str, str, str]] = {
    'search': ('search_off', 'No results found', 'Try adjusting your search terms or filters.'),
    'favorites': ('favorite_border', 'No favourites yet', 'Mark papers with ❤ to see them here.'),
    'to_read': ('bookmark_border', 'Reading list is empty', 'Bookmark papers to add them to your reading list.'),
    'library': ('menu_book', 'This library is empty', 'Upload papers or drag files here to get started.'),
    'marker': ('label_off', 'No papers in this marker', 'Assign papers to this marker to see them here.'),
    'all': ('folder_open', 'No files yet', 'Upload your first document to get started.'),
    'default': ('folder_open', 'Nothing here yet', 'Upload your first document to get started.'),
}


def empty_state(
    *,
    view: str = 'default',
    on_action: Callable[[], None] | None = None,
    action_label: str | None = None,
    action_icon: str | None = None,
) -> None:
    """Render a friendly empty-state placeholder with icon + message."""
    icon, title, subtitle = _EMPTY_STATE_MAP.get(view, _EMPTY_STATE_MAP['default'])
    with ui.element('div').classes('pv-empty-state'):
        ui.icon(icon).classes('pv-empty-state-icon')
        ui.label(title).classes('pv-empty-state-title')
        ui.label(subtitle).classes('pv-empty-state-subtitle')
        if on_action is not None:
            ui.button(
                action_label or 'Get started',
                icon=action_icon or 'cloud_upload',
                on_click=on_action,
            ).props('outline color=primary')


# ── Skeleton / loading placeholders ──────────────────────────────────────

def skeleton_poster_grid(count: int = 12) -> None:
    """Render placeholder skeleton tiles that pulse while data loads."""
    with ui.element('div').classes('w-full px-4 pt-1 pb-4 pv-poster-grid'):
        for _ in range(count):
            with ui.element('div').classes('pv-poster'):
                ui.element('div').classes('pv-skeleton w-full h-full')


def skeleton_poster_row(count: int = 8) -> None:
    """Render a horizontal scrolling row of skeleton tiles."""
    with ui.row().classes('w-full gap-4 px-4 py-4 flex-nowrap pv-marker-row'):
        for _ in range(count):
            with ui.element('div').classes('pv-poster'):
                ui.element('div').classes('pv-skeleton w-full h-full')


def skeleton_stats_row() -> None:
    """Render 4 placeholder stat cards while dashboard loads."""
    with ui.row().classes('w-full items-stretch gap-3 pt-3 pv-stats-row'):
        for _ in range(4):
            with ui.card().props('flat').classes('pv-surface pv-stat'):
                with ui.row().classes('w-full items-center gap-3'):
                    ui.element('div').classes('pv-skeleton').style('width:48px;height:48px;border-radius:12px')
                    with ui.column().classes('flex-1 gap-2'):
                        ui.element('div').classes('pv-skeleton').style('width:60%;height:28px')
                        ui.element('div').classes('pv-skeleton').style('width:40%;height:11px')


def _poster_tile(
    *,
    user_id: int,
    paper: PaperItem,
    on_open_metadata: Callable[[PaperItem], None],
    on_open_reader: Callable[[PaperItem], None],
    on_share_paper: Callable[[PaperItem], None] | None,
    on_changed: Callable[[], None] | None,
    remove_mode: str | None = None,
    select_mode: bool = False,
    selected_ids: list[str] | None = None,
    on_toggle_select: Callable[[str], None] | None = None,
) -> None:
    poster_dom_id = f'pv_poster_{paper.id}'
    progress_dom_id = f'pv_progress_{paper.id}'
    progress_fill_dom_id = f'pv_progress_fill_{paper.id}'
    comp_btn_dom_id = f'pv_comp_btn_{paper.id}'
    fav_btn_dom_id = f'pv_fav_btn_{paper.id}'
    tr_btn_dom_id = f'pv_tr_btn_{paper.id}'
    is_selected = select_mode and paper.id in (selected_ids or [])
    poster_classes = 'pv-poster' + (' pv-poster--selected' if is_selected else '')
    with ui.element('div').props(f'id={poster_dom_id}').classes(poster_classes):
        # Batch-select checkbox (only in select mode)
        if select_mode and on_toggle_select is not None:
            ui.checkbox(
                value=is_selected,
                on_change=lambda _e, pid=paper.id: on_toggle_select(pid),
            ).props('dense color=primary').classes('pv-poster-checkbox')

        # Corner toggles (completed + favorite)
        # Keep local state so we can update the tile without re-rendering the entire page.
        state_is_completed = bool(getattr(paper, 'is_completed', False))
        state_is_favorite = bool(getattr(paper, 'is_favorite', False))
        state_is_to_read = bool(getattr(paper, 'is_to_read', False))
        try:
            state_progress = float(getattr(paper, 'reading_progress', 0.0) or 0.0)
        except Exception:
            state_progress = 0.0
        if state_is_completed:
            state_progress = 1.0

        def _remove_self() -> None:
            ui.run_javascript(
                f"(function(){{const el=document.getElementById('{poster_dom_id}'); if(el) el.remove();}})();"
            )

        def _sync_dom_state() -> None:
            prog = 1.0 if state_is_completed else state_progress
            prog = max(0.0, min(1.0, float(prog or 0.0)))
            pct = int(prog * 100)
            js = f"""
(function(){{
    const setActive = (id, active) => {{
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.toggle('pv-active', active);
        el.classList.toggle('pv-inactive', !active);
        el.classList.toggle('pv-corner-btn--active', active);
        el.classList.toggle('pv-corner-btn--inactive', !active);
    }};
    setActive('{comp_btn_dom_id}', {str(state_is_completed).lower()});
    setActive('{fav_btn_dom_id}', {str(state_is_favorite).lower()});
    setActive('{tr_btn_dom_id}', {str(state_is_to_read).lower()});

    const bar = document.getElementById('{progress_dom_id}');
    const fill = document.getElementById('{progress_fill_dom_id}');
    if (bar && fill) {{
        if ({'true' if pct > 0 else 'false'}) {{
            bar.style.display = '';
            fill.style.width = '{pct}%';
        }} else {{
            bar.style.display = 'none';
            fill.style.width = '0%';
        }}
    }}
}})();
"""
            ui.run_javascript(js)

        def _toggle_completed(_e=None, p=paper) -> None:
            nonlocal state_is_completed, state_progress
            try:
                state_is_completed = bool(toggle_completed(paper_id=p.id))
                if state_is_completed:
                    state_progress = 1.0
            except Exception as ex:
                ui.notify(str(ex), color='negative')
                return
            _sync_dom_state()
            if on_changed is not None:
                on_changed()

        def _toggle_favorite(_e=None, p=paper) -> None:
            nonlocal state_is_favorite
            try:
                state_is_favorite = bool(toggle_favorite(paper_id=p.id, user_id=int(user_id)))
            except Exception as ex:
                ui.notify(str(ex), color='negative')
                return
            _sync_dom_state()
            if remove_mode == 'favorites' and not state_is_favorite:
                _remove_self()
            if on_changed is not None:
                on_changed()

        def _toggle_to_read(_e=None, p=paper) -> None:
            nonlocal state_is_to_read
            try:
                state_is_to_read = bool(toggle_to_read(paper_id=p.id, user_id=int(user_id)))
            except Exception as ex:
                ui.notify(str(ex), color='negative')
                return
            _sync_dom_state()
            if remove_mode == 'to_read' and not state_is_to_read:
                _remove_self()
            if on_changed is not None:
                on_changed()

        with ui.element('div').classes('pv-poster-corner'):
            ui.button(icon='check_circle', on_click=_toggle_completed).props(
                f'id={comp_btn_dom_id} flat dense round'
            ).classes(
                'pv-corner-btn pv-corner-btn--completed '
                + ('pv-active pv-corner-btn--active' if state_is_completed else 'pv-inactive pv-corner-btn--inactive')
            )
            ui.button(icon='favorite', on_click=_toggle_favorite).props(
                f'id={fav_btn_dom_id} flat dense round'
            ).classes(
                'pv-corner-btn pv-corner-btn--favorite '
                + ('pv-active pv-corner-btn--active' if state_is_favorite else 'pv-inactive pv-corner-btn--inactive')
            )
            ui.button(icon='bookmark', on_click=_toggle_to_read).props(
                f'id={tr_btn_dom_id} flat dense round'
            ).classes(
                'pv-corner-btn pv-corner-btn--to-read '
                + ('pv-active pv-corner-btn--active' if state_is_to_read else 'pv-inactive pv-corner-btn--inactive')
            )
            if on_share_paper is not None:
                ui.button(icon='share', on_click=lambda _e, p=paper: on_share_paper(p)).props(
                    'flat dense round'
                ).classes('pv-corner-btn pv-corner-btn--share pv-hover-only')

        with ui.element('div').classes('pv-poster-thumb'):
            # "Latest wins": show whichever asset was updated last (cover vs thumbnail).
            prev_url = preview_image_url_for(paper_id=paper.id)
            if prev_url:
                ui.image(prev_url).props('loading=lazy').classes('w-full h-full object-cover')
            else:
                ui.label('FILE').classes('text-center pv-text-dimmer pt-24')

        # Progress bar (hidden when 0)
        prog = 1.0 if state_is_completed else state_progress
        prog = max(0.0, min(1.0, float(prog or 0.0)))
        with ui.element('div').props(f'id={progress_dom_id}').classes('pv-poster-progress').style(
            'display: none;' if prog <= 0.001 else ''
        ):
            ui.element('div').props(f'id={progress_fill_dom_id}').classes('pv-poster-progress-fill').style(
                f'width: {int(prog * 100)}%'
            )

        with ui.element('div').classes('pv-poster-footer'):
            ui.label(paper.title).classes('pv-poster-title').tooltip(paper.title)

        with ui.element('div').classes('pv-poster-overlay').tooltip(paper.title):
            with ui.element('div').classes('pv-poster-overlay-actions'):
                ui.button(icon='info', on_click=lambda _e, p=paper: on_open_metadata(p)).props('flat dense round').classes(
                    'pv-fab pv-fab--metadata'
                ).tooltip('Metadata')
                ui.button(icon='description', on_click=lambda _e, p=paper: on_open_reader(p)).props('flat dense round').classes(
                    'pv-fab pv-fab--read cursor-pointer'
                ).tooltip('Open reader')

            ui.element('div').classes('pv-poster-overlay-bottom cursor-pointer').on('click', lambda _e, p=paper: on_open_reader(p))


def poster_grid(
    *,
    user_id: int,
    title: str,
    papers: list[PaperItem],
    on_open_metadata: Callable[[PaperItem], None],
    on_open_reader: Callable[[PaperItem], None],
    on_share_paper: Callable[[PaperItem], None] | None = None,
    on_changed: Callable[[], None] | None = None,
    remove_mode: str | None = None,
    select_mode: bool = False,
    selected_ids: list[str] | None = None,
    on_toggle_select: Callable[[str], None] | None = None,
) -> None:
    row_dom_id = f'pv_marker_row_{uuid4().hex}'

    def _scroll(dx: int) -> None:
        ui.run_javascript(
            f"(function(){{const el=document.getElementById('{row_dom_id}'); if(el) el.scrollBy({{left:{dx}, top:0, behavior:'smooth'}});}})();"
        )

    with ui.row().classes('w-full items-center justify-between px-4 pt-3'):
        ui.label(title).classes('text-base font-semibold pv-text-dim')
        with ui.row().classes('items-center gap-1'):
            ui.button(icon='chevron_left', on_click=lambda _e=None: _scroll(-600)).props('flat dense round').classes('pv-topbar-btn')
            ui.button(icon='chevron_right', on_click=lambda _e=None: _scroll(600)).props('flat dense round').classes('pv-topbar-btn')

    with ui.row().props(f'id={row_dom_id}').classes('w-full gap-4 px-4 py-4 flex-nowrap pv-marker-row'):
        for paper in papers:
            _poster_tile(
                user_id=user_id,
                paper=paper,
                on_open_metadata=on_open_metadata,
                on_open_reader=on_open_reader,
                on_share_paper=on_share_paper,
                on_changed=on_changed,
                remove_mode=remove_mode,
                select_mode=select_mode,
                selected_ids=selected_ids,
                on_toggle_select=on_toggle_select,
            )


def poster_wall(
    *,
    user_id: int,
    title: str,
    papers: list[PaperItem],
    on_open_metadata: Callable[[PaperItem], None],
    on_open_reader: Callable[[PaperItem], None],
    on_share_paper: Callable[[PaperItem], None] | None = None,
    on_changed: Callable[[], None] | None = None,
    remove_mode: str | None = None,
    view: str = 'default',
    on_empty_action: Callable[[], None] | None = None,
    select_mode: bool = False,
    selected_ids: list[str] | None = None,
    on_toggle_select: Callable[[str], None] | None = None,
) -> None:
    if not papers:
        empty_state(view=view, on_action=on_empty_action)
        return

    with ui.element('div').classes('w-full px-4 pt-1 pb-4 pv-poster-grid'):
        for paper in papers:
            _poster_tile(
                user_id=user_id,
                paper=paper,
                on_open_metadata=on_open_metadata,
                on_open_reader=on_open_reader,
                on_share_paper=on_share_paper,
                on_changed=on_changed,
                remove_mode=remove_mode,
                select_mode=select_mode,
                selected_ids=selected_ids,
                on_toggle_select=on_toggle_select,
            )
