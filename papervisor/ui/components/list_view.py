from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from nicegui import ui

from papervisor.domain import PaperItem
from papervisor.services.media import preview_image_url_for
from papervisor.services.papers import get_paper, toggle_completed, toggle_favorite, toggle_to_read
from papervisor.services.tags import list_paper_tags
from papervisor.ui.components.poster_grid import empty_state


class PaperRow(ui.row):
    def __init__(
        self,
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
        super().__init__()
        self.user_id = user_id
        self.paper = paper
        self.on_open_metadata = on_open_metadata
        self.on_open_reader = on_open_reader
        self.on_share_paper = on_share_paper
        self.on_changed = on_changed
        self.remove_mode = remove_mode
        self.on_toggle_select = on_toggle_select

        self.is_selected = select_mode and paper.id in (selected_ids or [])
        self.state_is_completed = bool(getattr(paper, 'is_completed', False))
        self.state_progress = getattr(paper, 'reading_progress', 0.0) or 0.0
        self.state_is_favorite = bool(getattr(paper, 'is_favorite', False))
        self.state_is_to_read = bool(getattr(paper, 'is_to_read', False))
        self.author_text, self.tag_items = self._resolve_meta()

        row_classes = 'pv-list-row' + (' pv-list-row--selected' if self.is_selected else '')

        self.classes(row_classes).classes('group flex-nowrap')

        with self:
            # Batch-select checkbox (only in select mode)
            if select_mode and self.on_toggle_select is not None:
                with ui.column().classes('justify-center pl-3'):
                    ui.checkbox(
                        value=self.is_selected,
                        on_change=lambda _e, pid=self.paper.id: self.on_toggle_select(pid),
                    ).props('dense color=primary')

            # Cover image (always spans full height of card)
            with ui.element('div').classes('pv-list-cover').on('click', lambda _e, p=self.paper: self.on_open_reader(p)):
                prev_url = preview_image_url_for(paper_id=self.paper.id)
                if prev_url:
                    ui.image(prev_url).props('loading=lazy no-spinner').classes('w-full h-full object-cover transition-transform duration-300 group-hover:scale-105')
                else:
                    with ui.row().classes('w-full h-full items-center justify-center'):
                        ui.icon('insert_drive_file').classes('pv-text-dimmer')

            # Content area (Text + Actions wrapper)
            with ui.row().classes('flex-1 min-w-0 items-center justify-between flex-wrap sm:flex-nowrap pl-3 sm:pl-4 py-2 sm:py-3 gap-y-1 sm:gap-y-2'):

                # Clickable text column
                with ui.column().classes('flex-1 min-w-0 justify-center gap-1 cursor-pointer pv-list-text-col').on('click', lambda _e, p=self.paper: self.on_open_reader(p)):
                    ui.label(self.paper.title).classes('text-sm sm:text-base font-medium sm:font-semibold text-ellipsis overflow-hidden break-normal line-clamp-2 sm:line-clamp-3 w-full leading-tight').style('color: var(--pv-text)')
                    if getattr(self.paper, 'subtitle', None):
                        ui.label(self.paper.subtitle).classes('text-xs sm:text-sm truncate w-full pv-text-dim pv-list-subtitle')
                    if self.author_text:
                        with ui.row().classes('items-center gap-1 min-w-0 w-full flex-nowrap pv-list-meta-row'):
                            ui.icon('person').classes('pv-list-meta-icon')
                            ui.label(self.author_text).classes('text-xs truncate w-full pv-text-dimmer pv-list-author-text')
                    with ui.row().classes('items-center gap-1 min-w-0 w-full pv-list-tag-row'):
                        ui.badge(self._format_label()).props('outline').classes('pv-chip pv-list-tag-chip pv-list-format-chip')
                        if self.tag_items:
                            for tag in self.tag_items:
                                ui.badge(tag).props('outline').classes(
                                    f'pv-chip pv-list-tag-chip {self._tag_color_class(tag)}'
                                ).tooltip(tag)
                        else:
                            ui.badge('No tags').props('outline').classes('pv-chip pv-list-tag-chip pv-list-tag-chip--fallback')

                # Actions
                with ui.row().classes('pv-list-actions shrink-0 w-full sm:w-auto items-center justify-start sm:justify-end pr-0 sm:pr-4 flex-nowrap'):
                    self.render_actions()

            self.render_progress()

    @ui.refreshable_method
    def render_actions(self) -> None:
        comp_color = 'positive' if self.state_is_completed else 'grey-6'
        fav_color = 'negative' if self.state_is_favorite else 'grey-6'
        tr_color = 'warning' if self.state_is_to_read else 'grey-6'

        ui.button(icon='check_circle', on_click=self._toggle_completed).props(
            f'flat dense round color={comp_color}'
        ).classes('pv-list-action-btn pv-list-action-btn--completed').tooltip('Mark as completed')
        ui.button(icon='favorite', on_click=self._toggle_favorite).props(
            f'flat dense round color={fav_color}'
        ).classes('pv-list-action-btn pv-list-action-btn--favorite').tooltip('Favorite')
        ui.button(icon='bookmark', on_click=self._toggle_to_read).props(
            f'flat dense round color={tr_color}'
        ).classes('pv-list-action-btn pv-list-action-btn--to-read').tooltip('To Read')
        if self.on_share_paper is not None:
            ui.button(icon='share', on_click=lambda _e, p=self.paper: self.on_share_paper(p)).props(
                'flat dense round color=info'
            ).classes('pv-list-action-btn pv-list-action-btn--share').tooltip('Share')
        ui.button(icon='info', on_click=lambda _e, p=self.paper: self.on_open_metadata(p)).props(
            'flat dense round color=info'
        ).classes('pv-list-action-btn pv-list-action-btn--metadata').tooltip('Metadata')

    def _toggle_completed(self, _e=None) -> None:
        try:
            self.state_is_completed = bool(toggle_completed(paper_id=self.paper.id))
            if self.state_is_completed:
                self.state_progress = 1.0
        except Exception as ex:
            ui.notify(str(ex), color='negative')
            return
        self.render_actions.refresh()
        self.render_progress.refresh()
        if self.on_changed is not None:
            self.on_changed()

    def _resolve_meta(self) -> tuple[str, list[str]]:
        author = str(getattr(self.paper, 'authors', '') or '').strip()
        tags_raw = getattr(self.paper, 'tags', ()) or ()
        tags = [str(tag).strip() for tag in tags_raw if str(tag or '').strip()]

        if author and tags:
            return author, tags[:4]

        try:
            paper_row = get_paper(paper_id=self.paper.id)
            if not author and paper_row is not None:
                author = str(getattr(paper_row, 'authors', '') or '').strip()
            if not tags:
                tags = [str(tag).strip() for tag in list_paper_tags(paper_id=self.paper.id) if str(tag or '').strip()]
        except Exception:
            pass

        return author, tags[:4]

    def _format_label(self) -> str:
        suffix = str(getattr(self.paper, 'file_suffix', '') or '').strip().lower().lstrip('.')
        if suffix:
            return suffix.upper()
        ftype = str(getattr(self.paper, 'file_type', '') or '').strip().lower()
        if ftype:
            return ftype.upper()
        return 'FILE'

    def _tag_color_class(self, tag: str) -> str:
        key = str(tag or '').strip().lower()
        if not key:
            return 'pv-list-tag-chip--v1'
        bucket = (sum(ord(ch) for ch in key) % 4) + 1
        return f'pv-list-tag-chip--v{bucket}'

    def _toggle_favorite(self, _e=None) -> None:
        try:
            self.state_is_favorite = bool(toggle_favorite(paper_id=self.paper.id, user_id=self.user_id))
        except Exception as ex:
            ui.notify(str(ex), color='negative')
            return
        self.render_actions.refresh()
        if self.remove_mode == 'favorites' and not self.state_is_favorite:
            self.delete()
        if self.on_changed is not None:
            self.on_changed()

    def _toggle_to_read(self, _e=None) -> None:
        try:
            self.state_is_to_read = bool(toggle_to_read(paper_id=self.paper.id, user_id=self.user_id))
        except Exception as ex:
            ui.notify(str(ex), color='negative')
            return
        self.render_actions.refresh()
        if self.remove_mode == 'to_read' and not self.state_is_to_read:
            self.delete()
        if self.on_changed is not None:
            self.on_changed()

    @ui.refreshable_method
    def render_progress(self) -> None:
        prog = 1.0 if self.state_is_completed else self.state_progress
        prog = max(0.0, min(1.0, float(prog or 0.0)))
        if prog > 0.001:
            with ui.element('div').classes('pv-list-progress-track'):
                ui.element('div').classes('pv-list-progress-fill transition-all duration-400').style(f'width: {int(prog * 100)}%;')


def list_wall(
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

    with ui.column().classes('w-full px-4 py-2 gap-0 pv-list-grid'):
        for paper in papers:
            PaperRow(
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

