from __future__ import annotations

from collections.abc import Callable

from nicegui import ui


def dialog_header(
    *,
    title: str,
    icon: str | None = None,
    subtitle: str | None = None,
    extra_classes: str = '',
    icon_classes: str = '',
    title_classes: str = '',
    subtitle_classes: str = '',
    actions_builder: Callable[[], None] | None = None,
):
    classes = ' '.join(
        part
        for part in (
            'w-full items-center px-4 py-2 pv-dialog-header pv-share-header',
            str(extra_classes or '').strip(),
        )
        if part
    )
    container = ui.column().classes('w-full gap-0')
    with container:
        row = ui.row().classes(classes)
        with row:
            with ui.row().classes('items-center gap-2 min-w-0 flex-1'):
                if icon:
                    icon_cls = ' '.join(part for part in ('pv-text-dimmer text-lg', str(icon_classes or '').strip()) if part)
                    ui.icon(icon, size='sm').classes(icon_cls)
                title_cls = ' '.join(part for part in ('text-base font-semibold', str(title_classes or '').strip()) if part)
                ui.label(str(title or '')).classes(title_cls)

            if actions_builder is not None:
                with ui.row().classes('pv-dialog-header-actions items-center gap-1 shrink-0'):
                    actions_builder()
        ui.separator().classes('w-full pv-dialog-header-splitter')
        if subtitle is not None and str(subtitle).strip():
            subtitle_cls = ' '.join(
                part for part in ('w-full px-4 pt-2 pb-2 text-sm pv-text-dimmer pv-dialog-header-subtitle', str(subtitle_classes or '').strip()) if part
            )
            ui.label(str(subtitle)).classes(subtitle_cls)
    return row


def dialog_footer(*, extra_classes: str = ''):
    classes = ' '.join(
        part
        for part in (
            'w-full justify-end p-4 border-t pv-dialog-footer',
            str(extra_classes or '').strip(),
        )
        if part
    )
    return ui.row().classes(classes)


def dialog_body(*, extra_classes: str = ''):
    classes = ' '.join(
        part
        for part in (
            'w-full p-4 gap-3',
            str(extra_classes or '').strip(),
        )
        if part
    )
    return ui.column().classes(classes)


def dialog_actions_row(*, extra_classes: str = ''):
    classes = ' '.join(
        part
        for part in (
            'w-full justify-end gap-2 pt-2',
            str(extra_classes or '').strip(),
        )
        if part
    )
    return ui.row().classes(classes)


__all__ = ['dialog_header', 'dialog_footer', 'dialog_actions_row', 'dialog_body']