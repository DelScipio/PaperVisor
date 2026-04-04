from __future__ import annotations

from uuid import uuid4

from nicegui import ui

from papervisor.domain import PaperItem
from papervisor.services.papers import (
    get_dashboard_counts,
    list_continue_reading,
    list_favorite_papers,
    list_most_opened,
    reset_open_counts,
    toggle_completed,
    toggle_favorite,
    toggle_to_read,
)
from papervisor.services.media import preview_image_url_for
from papervisor.ui.components.poster_grid import (
    poster_grid,
    empty_state,
)
from papervisor.ui.components.page_states import inline_empty_state


def render_dashboard_view(
    *,
    user_id: int,
    open_reader,
    open_metadata,
    open_share_paper,
    on_refresh_all,
    on_refresh_left_nav,
) -> None:
    favorites = list_favorite_papers(user_id=user_id, library_id=None, limit=24)
    continue_reading = list_continue_reading(user_id=user_id, library_id=None, limit=24)
    most_opened = list_most_opened(user_id=user_id, library_id=None, limit=12)

    with ui.column().classes('w-full pv-dashboard-shell'):
        @ui.refreshable
        def render_dashboard_stats() -> None:
            counts = get_dashboard_counts(user_id=user_id, library_id=None)
            _render_dashboard_stats_row(counts=counts)

        render_dashboard_stats()

        def _changed() -> None:
            on_refresh_left_nav()
            render_dashboard_stats.refresh()

        _render_dashboard_primary_sections(
            user_id=user_id,
            sections=[
                ('Continue reading', continue_reading),
                ('Favorites', favorites),
            ],
            open_metadata=open_metadata,
            open_reader=open_reader,
            open_share_paper=open_share_paper,
            on_changed=_changed,
        )
        _render_most_opened_section(
            user_id=user_id,
            papers=most_opened,
            open_metadata=open_metadata,
            open_reader=open_reader,
            on_refresh_content=lambda: (render_dashboard_stats.refresh(), on_refresh_all()),
        )


def _render_dashboard_grid(
    *,
    user_id: int,
    title: str,
    papers: list[PaperItem],
    open_metadata,
    open_reader,
    open_share_paper,
    on_changed,
) -> None:
    if not papers:
        return
    with ui.element('section').classes('pv-dashboard-section'):
        poster_grid(
            user_id=user_id,
            title=title,
            papers=papers,
            on_open_metadata=open_metadata,
            on_open_reader=open_reader,
            on_share_paper=open_share_paper,
            on_changed=on_changed,
        )


def _render_dashboard_primary_sections(
    *,
    user_id: int,
    sections: list[tuple[str, list[PaperItem]]],
    open_metadata,
    open_reader,
    open_share_paper,
    on_changed,
) -> None:
    for title, papers in sections:
        _render_dashboard_grid(
            user_id=user_id,
            title=title,
            papers=papers,
            open_metadata=open_metadata,
            open_reader=open_reader,
            open_share_paper=open_share_paper,
            on_changed=on_changed,
        )


def _render_dashboard_stat_card(*, label: str, value: int, icon: str, color: str) -> None:
    with ui.card().props('flat').classes(f'pv-surface pv-stat pv-stat--{color}'):
        with ui.row().classes('w-full items-center gap-3'):
            with ui.element('div').classes(f'pv-stat-icon pv-stat-icon-{color}'):
                ui.icon(icon).classes('text-2xl')
            with ui.column().classes('flex-1 gap-0'):
                ui.label(str(int(value))).classes('pv-stat-value')
                ui.label(label).classes('pv-stat-label')


def _render_dashboard_stats_row(*, counts: dict[str, object]) -> None:
    stat_specs = [
        ('Total files', 'total', 'folder', 'blue'),
        ('Favorites', 'favorites', 'favorite', 'red'),
        ('To Read', 'to_read', 'bookmark', 'orange'),
        ('Completed', 'completed', 'check_circle', 'green'),
    ]
    with ui.row().classes('w-full items-stretch gap-3 pt-3 pv-stats-row'):
        for label, count_key, icon, color in stat_specs:
            _render_dashboard_stat_card(
                label=label,
                value=int(counts.get(count_key, 0)),
                icon=icon,
                color=color,
            )


def _render_most_opened_section(
    *,
    user_id: int,
    papers: list[PaperItem],
    open_metadata,
    open_reader,
    on_refresh_content,
) -> None:
    def _most_opened_tooltip(*, paper: PaperItem) -> str:
        since_reset = int(getattr(paper, 'open_count_since_reset', 0) or 0)
        total = int(getattr(paper, 'open_count_total', 0) or 0)
        return f'Opened: {since_reset} since reset / {total} total'

    def _run_paper_action(action) -> None:
        try:
            action()
        except Exception as ex:
            ui.notify(str(ex), color='negative')
        on_refresh_content()

    def _render_corner_toggle_button(*, icon: str, color: str, is_active: bool, on_click) -> None:
        ui.button(icon=icon, on_click=on_click).props(f'flat dense round color={color}').classes(
            'pv-corner-btn ' + ('pv-active' if is_active else 'pv-inactive')
        )

    def _render_most_opened_poster(*, paper: PaperItem, tooltip: str) -> None:
        def _render_poster_overlay_actions() -> None:
            with ui.element('div').classes('pv-poster-overlay-actions'):
                ui.button(icon='info', on_click=lambda _e, pp=paper: open_metadata(pp)).props('flat dense round').classes(
                    'pv-fab pv-fab--metadata'
                ).tooltip('Metadata')
                ui.button(icon='description', on_click=lambda _e, pp=paper: open_reader(pp)).props('flat dense round').classes(
                    'pv-fab pv-fab--read'
                ).tooltip('Open reader')

        with ui.element('div').classes('pv-poster'):
            with ui.element('div').classes('pv-poster-corner'):
                is_completed = bool(getattr(paper, 'is_completed', False))
                is_favorite = bool(getattr(paper, 'is_favorite', False))
                is_to_read = bool(getattr(paper, 'is_to_read', False))
                toggle_specs = [
                    (
                        'check_circle',
                        'primary' if is_completed else 'grey-7',
                        is_completed,
                        lambda pid=paper.id: toggle_completed(paper_id=pid),
                    ),
                    (
                        'favorite',
                        'red' if is_favorite else 'grey-7',
                        is_favorite,
                        lambda pid=paper.id: toggle_favorite(paper_id=pid, user_id=user_id),
                    ),
                    (
                        'bookmark',
                        'blue' if is_to_read else 'grey-7',
                        is_to_read,
                        lambda pid=paper.id: toggle_to_read(paper_id=pid, user_id=user_id),
                    ),
                ]

                for icon, color, is_active, action in toggle_specs:
                    _render_corner_toggle_button(
                        icon=icon,
                        color=color,
                        is_active=is_active,
                        on_click=lambda _e=None, act=action: _run_paper_action(act),
                    )
                ui.button(
                    icon='refresh',
                    on_click=lambda _e=None, pid=paper.id: _run_paper_action(
                        lambda: reset_open_counts(paper_id=pid)
                    ),
                ).props(
                    'flat dense round color=primary'
                ).classes('pv-corner-btn pv-hover-only')

            with ui.element('div').classes('pv-poster-thumb'):
                prev_url = preview_image_url_for(paper_id=paper.id)
                if prev_url:
                    ui.image(prev_url).props('loading=lazy').classes('w-full h-full object-cover')
                else:
                    ui.label('FILE').classes('text-center pv-text-dimmer pt-24')

            with ui.element('div').classes('pv-poster-footer'):
                ui.label(paper.title).classes('pv-poster-title').tooltip(tooltip)

            with ui.element('div').classes('pv-poster-overlay').tooltip(tooltip):
                _render_poster_overlay_actions()

                ui.element('div').classes('pv-poster-overlay-bottom').on(
                    'click', lambda _e, pp=paper: open_reader(pp)
                )

    def _render_most_opened_header(on_scroll_left, on_scroll_right) -> None:
        with ui.row().classes('w-full items-center justify-between px-4 pt-3 pv-dashboard-section-head'):
            with ui.row().classes('items-center gap-3'):
                ui.label('Most opened').classes('text-base font-semibold')
                ui.label('Counts since reset and total opens.').classes('text-xs pv-text-dimmer')
            with ui.row().classes('items-center gap-1'):
                ui.button(icon='chevron_left', on_click=on_scroll_left).props('flat dense round')
                ui.button(icon='chevron_right', on_click=on_scroll_right).props('flat dense round')

    def _setup_most_opened_scroller() -> tuple[str, object, object]:
        row_dom_id = f'pv_marker_row_{uuid4().hex}'

        def _scroll(dx: int) -> None:
            ui.run_javascript(
                f"(function(){{const el=document.getElementById('{row_dom_id}'); if(el) el.scrollBy({{left:{dx}, top:0, behavior:'smooth'}});}})();"
            )

        return (
            row_dom_id,
            lambda _e=None: _scroll(-600),
            lambda _e=None: _scroll(600),
        )

    with ui.element('section').classes('pv-dashboard-section'):
        most_opened_row_dom_id, on_scroll_left, on_scroll_right = _setup_most_opened_scroller()
        _render_most_opened_header(on_scroll_left=on_scroll_left, on_scroll_right=on_scroll_right)

        with ui.row().props(f'id={most_opened_row_dom_id}').classes(
            'w-full gap-4 px-4 py-4 flex-nowrap pv-marker-row'
        ):
            if not papers:
                inline_empty_state('No files yet.')
            for p in papers:
                tip = _most_opened_tooltip(paper=p)
                _render_most_opened_poster(paper=p, tooltip=tip)
