from __future__ import annotations

import asyncio
from collections.abc import Callable

from nicegui import ui

from papervisor.services.papers import RenameResult
from papervisor.services.patterns import PLACEHOLDERS, PatternSettings, render_pattern, sanitize_rel_path
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header


_SAMPLE_PAPER = {
    'title': 'Attention Is All You Need',
    'subtitle': '',
    'authors': 'Ashish Vaswani; Noam Shazeer; Niki Parmar; Jakob Uszkoreit; Llion Jones; Aidan N. Gomez',
    'year': '2017',
    'series': '',
    'seriesIndex': '',
    'language': 'en',
    'publisher': 'NeurIPS',
    'isbn': '',
    'journal': 'Advances in Neural Information Processing Systems',
    'currentFilename': 'paper.pdf',
}

_SAMPLE_BOOK = {
    'title': 'Dune',
    'subtitle': '',
    'authors': 'Frank Herbert',
    'year': '1965',
    'series': 'Dune',
    'seriesIndex': '01',
    'language': 'en',
    'publisher': 'Chilton Books',
    'isbn': '9780441172719',
    'journal': '',
    'currentFilename': 'book.epub',
}


def _preview_text(pattern: str, *, file_type: str) -> str:
    ft = str(file_type or 'paper').strip().lower()
    sample = _SAMPLE_BOOK if ft == 'book' else _SAMPLE_PAPER
    rendered = render_pattern(pattern, sample)
    rendered = sanitize_rel_path(rendered).as_posix()
    ext = '.epub' if ft == 'book' else '.pdf'
    return f'Preview: /{rendered}{ext}'


def render_patterns_editor(
    *,
    settings: PatternSettings,
    libraries: list[object],
    allow_edit_default: bool,
    can_edit_library: Callable[[object], bool],
    on_save_default: Callable[[str | dict[str, str]], list[str] | None] | None = None,
    on_save_overrides: Callable[[dict[str, dict[str, str]]], list[str] | None] | None = None,
    on_migrate: Callable[[list[str] | None], RenameResult] | None = None,
    save_overrides_label: str = 'Save',
    show_library_overrides: bool = True,
) -> None:
    with ui.column().classes('w-full gap-4'):
        with dialog_card(max_width_class='', extra_classes='p-0 pv-patterns-intro-card'):
            dialog_header(
                title='File Naming Patterns',
                icon='rule',
                subtitle=(
                    'Configure automatic file organization using metadata placeholders. '
                    'Patterns are used when uploading files, moving files within your library, '
                    'and after metadata updates.'
                ),
                extra_classes='!px-3 !py-2',
                icon_classes='text-base',
                title_classes='text-sm',
                subtitle_classes='!px-3 !pt-1 !pb-2 !text-xs',
            )

        override_inputs: dict[tuple[str, str], ui.input] = {}
        override_previews: dict[tuple[str, str], ui.label] = {}

        with dialog_card(max_width_class=''):
            with ui.column().classes('w-full gap-2'):
                ui.label('Default File Naming Patterns').classes('text-sm font-semibold pv-text-dim')
                ui.label('Defaults are used when no library-specific override is set.').classes('text-xs pv-text-dimmer')

                with ui.column().classes('w-full gap-2 pv-subtle-panel p-3'):
                    with ui.row().classes('w-full items-center gap-3'):
                        default_paper_input = ui.input('Default Pattern (Paper)', value=settings.default_paper_pattern).props('outlined dense').classes('flex-1 pv-meta-field')
                        default_book_input = ui.input('Default Pattern (Book)', value=settings.default_book_pattern).props('outlined dense').classes('flex-1 pv-meta-field')
                        if not allow_edit_default:
                            default_paper_input.disable()
                            default_book_input.disable()

                    default_preview_paper = ui.label(_preview_text(settings.default_paper_pattern, file_type='paper')).classes('text-xs pv-text-dimmer pt-1')
                    default_preview_book = ui.label(_preview_text(settings.default_book_pattern, file_type='book')).classes('text-xs pv-text-dimmer')
                    default_save_status = ui.label('').classes('text-xs pv-text-dimmer pt-1')

                async def _save_defaults_and_migrate() -> None:
                    if not allow_edit_default or on_save_default is None:
                        return

                    default_save_btn.disable()
                    default_save_status.text = 'Saving…'
                    affected_library_ids: list[str] | None = None
                    try:
                        affected_library_ids = on_save_default(
                            {
                                'paper': str(default_paper_input.value or ''),
                                'book': str(default_book_input.value or ''),
                            }
                        )
                        default_save_status.text = 'Saved.'
                        if on_migrate is not None:
                            default_save_status.text = 'Saved. Migrating files…'
                            ui.notify('Default patterns saved; migrating files…', color='positive')
                            result = await asyncio.to_thread(on_migrate, affected_library_ids)
                            default_save_status.text = (
                                f'Migration done: renamed={result.renamed}, skipped={result.skipped}, failed={result.failed}'
                            )
                            ui.notify(
                                f'Migration done: renamed={result.renamed}, skipped={result.skipped}, failed={result.failed}',
                                color='positive' if result.failed == 0 else 'warning',
                            )
                        else:
                            ui.notify('Default patterns saved', color='positive')
                    except TypeError:
                        affected_library_ids = on_save_default(str(default_paper_input.value or ''))
                        if on_migrate is not None:
                            result = await asyncio.to_thread(on_migrate, affected_library_ids)
                            default_save_status.text = (
                                f'Migration done: renamed={result.renamed}, skipped={result.skipped}, failed={result.failed}'
                            )
                        ui.notify('Default pattern saved', color='positive')
                    except Exception as ex:
                        default_save_status.text = f'Error: {ex}'
                        ui.notify(str(ex), color='negative')
                    finally:
                        default_save_btn.enable()

                def _update_default_previews() -> None:
                    dp = str(default_paper_input.value or '')
                    db = str(default_book_input.value or '')
                    default_preview_paper.text = _preview_text(dp, file_type='paper')
                    default_preview_book.text = _preview_text(db, file_type='book')
                    for (lid, ft), inp in override_inputs.items():
                        if not str(inp.value or '').strip():
                            prev = override_previews.get((lid, ft))
                            if prev is not None:
                                prev.text = _preview_text(dp if ft == 'paper' else db, file_type=ft)

                default_paper_input.on('update:model-value', lambda _e: _update_default_previews())
                default_book_input.on('update:model-value', lambda _e: _update_default_previews())

                with dialog_actions_row():
                    default_save_btn = ui.button('Save', on_click=_save_defaults_and_migrate).props('color=primary').classes('pv-meta-save-btn')
                    if not allow_edit_default:
                        default_save_btn.disable()

        overrides_save_status: ui.label | None = None

        async def _save_overrides() -> None:
            if on_save_overrides is None:
                return

            save_all_btn.disable()
            if overrides_save_status is not None:
                overrides_save_status.text = 'Saving…'
            try:
                payload: dict[str, dict[str, str]] = {}
                touched_library_ids: list[str] = []
                for lib in libraries:
                    lib_id = str(getattr(lib, 'id'))
                    if not can_edit_library(lib):
                        continue
                    touched_library_ids.append(lib_id)
                    payload[lib_id] = {
                        'paper': str(override_inputs[(lib_id, 'paper')].value or '').strip(),
                        'book': str(override_inputs[(lib_id, 'book')].value or '').strip(),
                    }

                changed_library_ids = on_save_overrides(payload)
                if changed_library_ids is None:
                    changed_library_ids = touched_library_ids

                if on_migrate is not None and changed_library_ids:
                    if overrides_save_status is not None:
                        overrides_save_status.text = 'Saved. Migrating files…'
                    ui.notify('Library patterns saved; migrating files…', color='positive')
                    result = await asyncio.to_thread(on_migrate, changed_library_ids)
                    if overrides_save_status is not None:
                        overrides_save_status.text = (
                            f'Migration done: renamed={result.renamed}, skipped={result.skipped}, failed={result.failed}'
                        )
                    ui.notify(
                        f'Migration done: renamed={result.renamed}, skipped={result.skipped}, failed={result.failed}',
                        color='positive' if result.failed == 0 else 'warning',
                    )
                else:
                    if overrides_save_status is not None:
                        overrides_save_status.text = 'Saved.'
                    ui.notify('Library patterns saved', color='positive')
            except Exception as ex:
                if overrides_save_status is not None:
                    overrides_save_status.text = f'Error: {ex}'
                ui.notify(str(ex), color='negative')
            finally:
                save_all_btn.enable()

        if show_library_overrides:
            with dialog_card(max_width_class=''):
                with ui.column().classes('w-full gap-3'):
                    ui.label('Library-Specific Overrides').classes('text-sm font-semibold pv-text-dim')
                    ui.label('Define patterns for specific libraries. Leave fields empty to use default patterns.').classes(
                        'text-xs pv-text-dimmer'
                    )

                    with ui.column().classes('w-full gap-2'):
                        for lib in libraries:
                            lib_id = str(getattr(lib, 'id'))
                            existing_paper = (settings.library_overrides.get(lib_id) or {}).get('paper', '')
                            existing_book = (settings.library_overrides.get(lib_id) or {}).get('book', '')

                            with ui.column().classes('w-full gap-2 pv-subtle-panel p-3'):
                                ui.label(str(getattr(lib, 'name', 'Library'))).classes('text-sm font-semibold pv-text-dim')

                                with ui.row().classes('w-full items-center gap-3'):
                                    inp_paper = ui.input('Paper', value=existing_paper).props(
                                        'outlined dense placeholder="Leave empty to use default pattern"'
                                    ).classes('flex-1 pv-meta-field')
                                    inp_book = ui.input('Book', value=existing_book).props(
                                        'outlined dense placeholder="Leave empty to use default pattern"'
                                    ).classes('flex-1 pv-meta-field')
                                    override_inputs[(lib_id, 'paper')] = inp_paper
                                    override_inputs[(lib_id, 'book')] = inp_book

                                    if not can_edit_library(lib):
                                        inp_paper.disable()
                                        inp_book.disable()

                                    def _clear_for(library_id: str) -> None:
                                        for ft in ('paper', 'book'):
                                            key = (library_id, ft)
                                            if key not in override_inputs:
                                                continue
                                            override_inputs[key].value = ''
                                            prev = override_previews.get(key)
                                            if prev is not None:
                                                dp = str(default_paper_input.value or '')
                                                db = str(default_book_input.value or '')
                                                prev.text = _preview_text(dp if ft == 'paper' else db, file_type=ft)

                                    clear_btn = ui.button('Clear', on_click=lambda _e=None, lid=lib_id: _clear_for(lid)).props('flat dense').classes('pv-meta-action-btn')
                                    if not can_edit_library(lib):
                                        clear_btn.disable()

                                prev_p = ui.label(_preview_text(existing_paper or str(default_paper_input.value or ''), file_type='paper')).classes(
                                    'text-xs pv-text-dimmer pt-1'
                                )
                                prev_b = ui.label(_preview_text(existing_book or str(default_book_input.value or ''), file_type='book')).classes(
                                    'text-xs pv-text-dimmer'
                                )
                                override_previews[(lib_id, 'paper')] = prev_p
                                override_previews[(lib_id, 'book')] = prev_b

                                def _bind_preview(library_id: str, ft: str) -> None:
                                    def _update() -> None:
                                        value = str(override_inputs[(library_id, ft)].value or '').strip()
                                        if not value:
                                            value = str(default_paper_input.value or '') if ft == 'paper' else str(default_book_input.value or '')
                                        override_previews[(library_id, ft)].text = _preview_text(value, file_type=ft)

                                    override_inputs[(library_id, ft)].on('update:model-value', lambda _e: _update())

                                _bind_preview(lib_id, 'paper')
                                _bind_preview(lib_id, 'book')

                    overrides_save_status = ui.label('').classes('text-xs pv-text-dimmer')
                    with dialog_actions_row(extra_classes='pt-0'):
                        save_all_btn = ui.button(save_overrides_label, on_click=_save_overrides).props('color=primary').classes('pv-meta-save-btn')

        with dialog_card(max_width_class=''):
            with ui.column().classes('w-full gap-2'):
                ui.label('Available Placeholders').classes('text-sm font-semibold pv-text-dim')
                ui.label(
                    'Use placeholders to insert metadata into file names and folder paths. '
                    'Values are resolved when uploading or moving files.'
                ).classes('text-xs pv-text-dimmer')

                with ui.row().classes('w-full gap-10'):
                    with ui.column().classes('flex-1'):
                        ui.label('Placeholders').classes('text-xs font-semibold pv-text-dim')
                        with ui.column().classes('gap-1 pt-1'):
                            for key, desc in PLACEHOLDERS.items():
                                ui.label(f'{{{key}}} — {desc}').classes('text-xs pv-text-dim')

                    with ui.column().classes('flex-1'):
                        ui.label('Optional blocks').classes('text-xs font-semibold pv-text-dim')
                        ui.label(
                            'Surround parts of your pattern with angle brackets <...> to make them optional. '
                            'If any placeholder inside the block has no value, the whole block is excluded.'
                        ).classes('text-xs pv-text-dimmer pt-1')
                        ui.label('Example:').classes('text-xs pv-text-dim pt-2')
                        ui.label('<{seriesIndex}> - {title}').classes('text-xs pv-text-dim')
                        ui.label('01 - Dune (if {seriesIndex} exists)').classes('text-xs pv-text-dimmer pt-1')
                        ui.label('Dune (if {seriesIndex} is missing)').classes('text-xs pv-text-dimmer')
