from __future__ import annotations

from nicegui import ui

from papervisor.services.papers import rename_papers_to_match_patterns
from papervisor.services.patterns import (
    PatternSettings,
    get_pattern_settings,
    set_library_override,
    set_library_override_for,
)
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header
from papervisor.ui.components.page_states import show_initial_panel_loading
from papervisor.ui.components.patterns_editor import render_patterns_editor


def render_patterns_tab(
    *,
    user_id: int,
    panel_loading: dict[str, bool],
    libraries_provider,
) -> None:
    @ui.refreshable
    def render_patterns() -> None:
        if show_initial_panel_loading(
            panel_loading=panel_loading,
            key='patterns',
            message='Loading patterns…',
            refresh=render_patterns.refresh,
        ):
            return

        try:
            settings: PatternSettings = get_pattern_settings()
        except Exception as ex:
            dialog_header(
                title='File Naming Patterns',
                icon='rule',
                subtitle='Patterns are unavailable until the database is migrated.',
            )
            with dialog_card(max_width_class='', extra_classes='mt-2'):
                ui.label(str(ex)).classes('text-xs pv-text-dim')
                ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer pt-1')
            return

        libs = libraries_provider()
        owned_by_me: set[str] = {str(l.id) for l in libs if bool(getattr(l, 'is_owned_by_me', False))}
        owned_libs = [l for l in libs if str(getattr(l, 'id', '')) in owned_by_me]

        def _save_overrides(payload) -> list[str]:
            # Editor may send {lib_id: str} (legacy) or {lib_id: {'paper': str, 'book': str}} (new).
            if not isinstance(payload, dict):
                return []
            changed_library_ids: list[str] = []
            for library_id, patterns in payload.items():
                lid = str(library_id)
                if lid not in owned_by_me:
                    continue
                before = settings.library_overrides.get(lid) or {}
                before_paper = str(before.get('paper', '') or '').strip()
                before_book = str(before.get('book', '') or '').strip()
                if isinstance(patterns, dict):
                    p_paper = str(patterns.get('paper', '') or '').strip() or None
                    p_book = str(patterns.get('book', '') or '').strip() or None
                    after_paper = str(p_paper or '').strip()
                    after_book = str(p_book or '').strip()
                    if before_paper != after_paper or before_book != after_book:
                        changed_library_ids.append(lid)
                    set_library_override_for(library_id=lid, file_type='paper', pattern=p_paper)
                    set_library_override_for(library_id=lid, file_type='book', pattern=p_book)
                else:
                    p = str(patterns or '').strip() or None
                    after = str(p or '').strip()
                    if before_paper != after or before_book != after:
                        changed_library_ids.append(lid)
                    set_library_override(library_id=lid, pattern=p)
            return changed_library_ids

        def _migrate(library_ids: list[str] | None):
            return rename_papers_to_match_patterns(library_ids=library_ids)

        render_patterns_editor(
            settings=settings,
            libraries=owned_libs,
            allow_edit_default=False,
            can_edit_library=lambda _lib: True,
            on_save_default=None,
            on_save_overrides=_save_overrides,
            on_migrate=_migrate,
            save_overrides_label='Save My Library Patterns',
        )

    render_patterns()
    return render_patterns
