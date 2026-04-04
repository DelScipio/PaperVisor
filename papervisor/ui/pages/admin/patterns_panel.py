from __future__ import annotations

from nicegui import ui

from papervisor.services.libraries import list_libraries
from papervisor.services.papers import rename_papers_to_match_patterns
from papervisor.services.patterns import (
    PatternSettings,
    get_pattern_settings,
    set_default_pattern_for,
)
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_header
from papervisor.ui.components.patterns_editor import render_patterns_editor


def render_patterns_panel(
    *,
    current_user_id: int | None = None,
    library_owner_user_id: int | None = None,
    owner_user_id_value: str = '',
    on_owner_user_id_change=None,
) -> None:
    try:
        settings: PatternSettings = get_pattern_settings()
    except Exception as ex:
        with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
            dialog_header(
                title='File Naming Patterns',
                icon='rule',
                subtitle='Patterns are unavailable until the database is migrated.',
                extra_classes='!px-3 !py-2',
                icon_classes='text-base',
                title_classes='text-sm',
                subtitle_classes='text-xs',
            )
        with dialog_card(max_width_class='', extra_classes='mt-2'):
            ui.label(str(ex)).classes('text-xs pv-text-dim')
            ui.label('Run: alembic upgrade heads').classes('text-xs pv-text-dimmer pt-1')
        return

    def _library_ids_without_specific_patterns() -> list[str]:
        all_libs = list_libraries(owner_user_id=None)
        return [
            str(getattr(lib, 'id'))
            for lib in all_libs
            if not bool(settings.library_overrides.get(str(getattr(lib, 'id')), {}))
        ]

    def _save_default(payload) -> list[str]:
        # Editor may send str (legacy) or {'paper': str, 'book': str} (new).
        if isinstance(payload, dict):
            set_default_pattern_for(file_type='paper', pattern=str(payload.get('paper', '') or ''))
            set_default_pattern_for(file_type='book', pattern=str(payload.get('book', '') or ''))
            return _library_ids_without_specific_patterns()
        set_default_pattern_for(file_type='paper', pattern=str(payload or ''))
        return _library_ids_without_specific_patterns()

    def _migrate(library_ids: list[str] | None):
        return rename_papers_to_match_patterns(library_ids=library_ids)

    render_patterns_editor(
        settings=settings,
        libraries=[],
        allow_edit_default=True,
        can_edit_library=lambda _lib: True,
        on_save_default=_save_default,
        on_save_overrides=None,
        on_migrate=_migrate,
        show_library_overrides=False,
    )
