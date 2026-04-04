from __future__ import annotations

from nicegui import ui


def dialog_card(*, max_width_class: str = 'max-w-xl', extra_classes: str = ''):
    classes = ' '.join(
        part
        for part in (
            'pv-dialog-card',
            'w-full',
            str(max_width_class or '').strip(),
            str(extra_classes or '').strip(),
        )
        if part
    )
    return ui.card().props('flat bordered').classes(classes)


__all__ = ['dialog_card']