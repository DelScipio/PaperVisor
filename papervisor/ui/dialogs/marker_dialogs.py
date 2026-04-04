from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from nicegui import ui

from papervisor.domain import MarkerItem
from papervisor.services.markers import create_marker, delete_marker, get_marker, update_marker
from papervisor.services.tags import list_tags
from papervisor.ui.components.dialog_card import dialog_card
from papervisor.ui.components.dialog_sections import dialog_actions_row, dialog_header
from papervisor.ui.components.icon_picker import compact_icon_name_row

FieldKey = str
OperatorKey = str


FIELD_OPTIONS: dict[FieldKey, str] = {
    'title': 'Title',
    'authors': 'Authors',
    'tags': 'Tags',
    'publisher': 'Publisher',
    'journal': 'Journal',
    'language': 'Language',
    'year': 'Year',
    'file_type': 'Type',
}


OPS_TEXT: dict[OperatorKey, str] = {
    'equals': 'Equals',
    'not_equals': '≠ Not Equal',
    'empty': 'Empty',
    'not_empty': 'Not Empty',
    'contains': 'Contains',
    'not_contains': 'Does Not Contain',
}

OPS_TAGS: dict[OperatorKey, str] = {
    'includes_any': 'Includes Any',
    'includes_all': 'Includes All',
    'empty': 'Empty',
    'not_empty': 'Not Empty',
}

OPS_EXACT: dict[OperatorKey, str] = {
    'equals': 'Equals',
    'not_equals': '≠ Not Equal',
}

MAX_QUERY_DEPTH = 8
MAX_QUERY_CHILDREN = 50


def _event_value(e: object) -> Any:
    """Extract the new model value from NiceGUI events across versions."""
    args = getattr(e, 'args', None)
    if isinstance(args, dict) and 'value' in args:
        return args.get('value')
    if hasattr(e, 'value'):
        return getattr(e, 'value')
    return args


def _normalize_field(value: Any, *, fallback: str = 'title') -> str:
    v = str(value or '').strip()
    if v in FIELD_OPTIONS:
        return v
    for k, label in FIELD_OPTIONS.items():
        if str(label).lower() == v.lower():
            return str(k)
    return fallback


def _ops_for_field(field: str) -> dict[OperatorKey, str]:
    f = str(field or '').strip().lower()
    if f == 'tags':
        return OPS_TAGS
    if f in {'file_type'}:
        return OPS_EXACT
    return OPS_TEXT


def _default_value_for_field(field: str) -> Any:
    return [] if str(field or '').strip().lower() == 'tags' else ''


def _new_rule(field: str = 'title') -> dict[str, Any]:
    ops = _ops_for_field(field)
    op0 = next(iter(ops.keys()))
    return {'type': 'rule', 'field': field, 'operator': op0, 'value': _default_value_for_field(field)}


def _new_group() -> dict[str, Any]:
    return {'type': 'group', 'op': 'and', 'children': []}


def _normalize_group_op(value: Any) -> str:
    return 'or' if str(value or '').strip().lower() == 'or' else 'and'


def _normalize_rule_value(*, field: str, operator: str, value: Any) -> Any:
    if operator in {'empty', 'not_empty'}:
        return _default_value_for_field(field)

    if field == 'tags':
        raw_values: list[Any]
        if isinstance(value, list):
            raw_values = value
        elif str(value or '').strip():
            raw_values = [str(value or '').strip()]
        else:
            raw_values = []

        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            token = str(raw or '').strip()
            if not token:
                continue
            token_key = token.lower()
            if token_key in seen:
                continue
            seen.add(token_key)
            cleaned.append(token)
        return cleaned

    if value is None:
        return ''
    if isinstance(value, (dict, list, set, tuple)):
        return ''
    return str(value)


def _sanitize_rule_node(node: dict[str, Any]) -> dict[str, Any]:
    field = _normalize_field(node.get('field'))
    ops = _ops_for_field(field)
    operator = str(node.get('operator') or '').strip()
    if operator not in ops:
        operator = next(iter(ops.keys()))
    value = _normalize_rule_value(field=field, operator=operator, value=node.get('value'))
    return {'type': 'rule', 'field': field, 'operator': operator, 'value': value}


def _sanitize_query_node(node: Any, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(node, dict):
        return _new_rule()

    if depth >= MAX_QUERY_DEPTH:
        return _new_group()

    ntype = str(node.get('type') or '').strip().lower()
    if ntype == 'rule' or any(k in node for k in ('field', 'operator', 'value')):
        return _sanitize_rule_node(node)

    children_raw = node.get('children')
    if not isinstance(children_raw, list):
        children_raw = []

    children: list[dict[str, Any]] = []
    for child in children_raw[:MAX_QUERY_CHILDREN]:
        if isinstance(child, dict):
            children.append(_sanitize_query_node(child, depth=depth + 1))

    return {
        'type': 'group',
        'op': _normalize_group_op(node.get('op')),
        'children': children,
    }


def _ensure_v2_query(query: dict[str, object] | None) -> dict[str, Any]:
    root_candidate: Any = None
    if isinstance(query, dict):
        if int(query.get('version') or 0) == 2 and isinstance(query.get('root'), dict):
            root_candidate = query.get('root')
        else:
            root_candidate = query
    root = _sanitize_query_node(root_candidate if root_candidate is not None else _new_group())
    if str(root.get('type') or '') != 'group':
        root = {'type': 'group', 'op': 'and', 'children': [root]}
    if not isinstance(root.get('children'), list):
        root['children'] = []
    if not root['children']:
        root['children'] = [_new_rule()]
    return {'version': 2, 'root': root}


class MarkerDialogs:
    def __init__(self, *, on_changed: Callable[..., None], user_id: int | None = None) -> None:
        self._on_changed = on_changed
        self._user_id = user_id
        self._create_dialog = ui.dialog()
        self._edit_dialog = ui.dialog()
        self._delete_dialog = ui.dialog()

    def _emit_changed(self, selected_marker_id: str | None = None) -> None:
        try:
            self._on_changed(selected_marker_id)
        except TypeError:
            self._on_changed()

    def open_create(self, *, on_created: Callable[[str], None] | None = None) -> None:
        self._create_dialog.clear()

        with self._create_dialog, dialog_card(max_width_class='max-w-2xl'):
            dialog_header(title='Create Marker', icon='category')

            icon_select, _icon_preview, name_input = compact_icon_name_row(icon_value='category')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._create_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        created = create_marker(
                            name=str(name_input.value or ''),
                            icon=str(icon_select.value or 'category'),
                            is_smart=False,
                            owner_user_id=self._user_id,
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return
                    except Exception as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Created: {created.name}', color='positive')
                    self._create_dialog.close()
                    if on_created is not None:
                        on_created(str(created.id))
                    self._emit_changed(str(created.id))

                ui.button('Create', on_click=submit).props('color=primary')

        self._create_dialog.open()

    def open_create_auto(self, *, on_created: Callable[[str], None] | None = None) -> None:
        self._create_dialog.clear()

        with self._create_dialog, dialog_card(max_width_class='max-w-4xl', extra_classes='pv-auto-marker-dialog'):
            dialog_header(
                title='Create Auto Marker',
                icon='auto_awesome',
                subtitle='Create rules to organize papers automatically.',
            )

            with ui.card().props('flat bordered').classes('pv-surface w-full no-shadow pv-auto-marker-section'):
                def _build_public_checkbox() -> None:
                    nonlocal is_public
                    is_public = ui.checkbox('Public', value=False).props('dense').classes('self-center')

                is_public = None
                icon_select, _icon_preview, name_input = compact_icon_name_row(
                    icon_value='auto_awesome',
                    extra_builder=_build_public_checkbox,
                )

            query_state: dict[str, Any] = _ensure_v2_query(None)

            self._render_auto_builder(query_state=query_state)

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._create_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        payload = {'version': 2, 'root': query_state['root']}
                        rules_json = json.dumps(payload, ensure_ascii=False)
                        created = create_marker(
                            name=str(name_input.value or ''),
                            icon=str(icon_select.value or 'auto_awesome'),
                            is_smart=True,
                            rules_json=rules_json,
                            visibility=('global' if bool(is_public.value) else 'private'),
                            owner_user_id=self._user_id,
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return
                    except Exception as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Created: {created.name}', color='positive')
                    self._create_dialog.close()
                    if on_created is not None:
                        on_created(str(created.id))
                    self._emit_changed(str(created.id))

                ui.button('Create', on_click=submit).props('color=primary')

        self._create_dialog.open()

    def open_edit(self, marker: MarkerItem) -> None:
        marker, rule_existing = get_marker(marker_id=marker.id, user_id=self._user_id)
        if bool(marker.is_smart):
            self._open_edit_auto(marker=marker, rule_existing=rule_existing)
        else:
            self._open_edit_manual(marker=marker)

    def _open_edit_manual(self, *, marker: MarkerItem) -> None:
        self._edit_dialog.clear()
        with self._edit_dialog, dialog_card(max_width_class='max-w-2xl'):
            dialog_header(title='Edit Marker', icon='edit')

            icon_select, _icon_preview, name_input = compact_icon_name_row(
                icon_value=marker.icon or 'category',
                name_value=marker.name,
            )

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._edit_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        updated = update_marker(
                            marker_id=marker.id,
                            name=str(name_input.value or ''),
                            icon=str(icon_select.value or 'category'),
                            is_smart=False,
                            user_id=self._user_id,
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return
                    except Exception as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Updated: {updated.name}', color='positive')
                    self._edit_dialog.close()
                    self._on_changed()

                ui.button('Save', on_click=submit).props('color=primary')

        self._edit_dialog.open()

    def _open_edit_auto(self, *, marker: MarkerItem, rule_existing: dict[str, object] | None) -> None:
        self._edit_dialog.clear()
        with self._edit_dialog, dialog_card(max_width_class='max-w-4xl', extra_classes='pv-auto-marker-dialog'):
            dialog_header(
                title='Edit Auto Marker',
                icon='auto_awesome',
                subtitle='Update rules to keep this marker organized automatically.',
            )

            with ui.card().props('flat bordered').classes('pv-surface w-full no-shadow pv-auto-marker-section'):
                def _build_public_checkbox() -> None:
                    nonlocal is_public
                    is_public = ui.checkbox(
                        'Public',
                        value=str(getattr(marker, 'visibility', '') or 'private') == 'global',
                    ).props('dense').classes('self-center')

                is_public = None
                icon_select, _icon_preview, name_input = compact_icon_name_row(
                    icon_value=marker.icon or 'auto_awesome',
                    name_value=marker.name,
                    extra_builder=_build_public_checkbox,
                )

            query_state: dict[str, Any] = _ensure_v2_query(rule_existing if isinstance(rule_existing, dict) else None)

            self._render_auto_builder(query_state=query_state)

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._edit_dialog.close).props('flat color=negative')

                def submit() -> None:
                    try:
                        payload = {'version': 2, 'root': query_state['root']}
                        rules_json = json.dumps(payload, ensure_ascii=False)
                        updated = update_marker(
                            marker_id=marker.id,
                            name=str(name_input.value or ''),
                            icon=str(icon_select.value or 'auto_awesome'),
                            is_smart=True,
                            rules_json=rules_json,
                            visibility=('global' if bool(is_public.value) else 'private'),
                            user_id=self._user_id,
                        )
                    except ValueError as e:
                        ui.notify(str(e), color='negative')
                        return
                    except Exception as e:
                        ui.notify(str(e), color='negative')
                        return

                    ui.notify(f'Updated: {updated.name}', color='positive')
                    self._edit_dialog.close()
                    self._on_changed()

                ui.button('Save', on_click=submit).props('color=primary')

        self._edit_dialog.open()

    def _render_auto_builder(self, *, query_state: dict[str, Any]) -> None:
        try:
            tag_options = list_tags()
        except Exception:
            tag_options = []

        @ui.refreshable
        def render_builder() -> None:
            root = query_state['root']

            def render_group(*, group: dict[str, Any], depth: int, parent: dict[str, Any] | None = None, index: int | None = None) -> None:
                children = group.get('children')
                if not isinstance(children, list):
                    group['children'] = []
                    children = group['children']

                group_classes = 'pv-surface w-full no-shadow pv-auto-marker-group'
                if depth > 0:
                    group_classes += ' pv-auto-marker-group-nested'

                with ui.card().props('flat bordered').classes(group_classes):
                    with ui.row().classes('w-full items-center gap-2 pv-auto-marker-group-header'):
                        ui.label('Match').classes('text-xs pv-text-dimmer')
                        cond = ui.select({'and': 'ALL', 'or': 'ANY'}, value=_normalize_group_op(group.get('op'))).props('outlined dense').classes('w-24')
                        cond.bind_value(group, 'op')

                        ui.space()
                        ui.button('Rule', icon='add', on_click=lambda g=group: (g['children'].append(_new_rule()), render_builder.refresh())).props('flat dense')
                        ui.button('Group', icon='create_new_folder', on_click=lambda g=group: (g['children'].append(_new_group()), render_builder.refresh())).props('flat dense')
                        if parent is not None and index is not None:
                            ui.button(icon='delete', on_click=lambda p=parent, i=index: (p['children'].pop(i), render_builder.refresh())).props('flat dense color=negative')

                    if not children:
                        with ui.row().classes('w-full items-center gap-2 pv-auto-marker-empty'):
                            ui.label('No rules yet.').classes('text-xs pv-text-dimmer')
                            ui.button('Add first rule', icon='add', on_click=lambda g=group: (g['children'].append(_new_rule()), render_builder.refresh())).props('flat dense color=primary')

                    for idx, node in enumerate(list(children)):
                        if not isinstance(node, dict):
                            continue

                        node_type = str(node.get('type') or '')
                        if node_type == 'group':
                            render_group(group=node, depth=depth + 1, parent=group, index=idx)
                            continue

                        if node_type != 'rule':
                            continue

                        field = _normalize_field(node.get('field'))
                        node['field'] = field
                        ops = _ops_for_field(field)
                        operator = str(node.get('operator') or '').strip()
                        if operator not in ops:
                            operator = next(iter(ops.keys()))
                            node['operator'] = operator
                            node['value'] = _normalize_rule_value(field=field, operator=operator, value=node.get('value'))

                        with ui.card().props('flat bordered').classes('pv-surface w-full no-shadow pv-auto-marker-rule'):
                            with ui.row().classes('w-full items-center gap-2'):
                                field_sel = ui.select(FIELD_OPTIONS, value=field).props('outlined dense').classes('pv-auto-marker-field')

                                def _on_field_change(n=node) -> None:
                                    normalized_field = _normalize_field(n.get('field'))
                                    n['field'] = normalized_field
                                    n['operator'] = next(iter(_ops_for_field(normalized_field).keys()))
                                    n['value'] = _default_value_for_field(normalized_field)
                                    render_builder.refresh()

                                field_sel.bind_value(node, 'field')
                                field_sel.on_value_change(lambda: _on_field_change())

                                op_sel = ui.select(ops, value=operator).props('outlined dense').classes('pv-auto-marker-operator')
                                op_sel.bind_value(node, 'operator')

                                def _on_operator_change(n=node) -> None:
                                    n['value'] = _normalize_rule_value(
                                        field=_normalize_field(n.get('field')),
                                        operator=str(n.get('operator') or ''),
                                        value=n.get('value'),
                                    )
                                    render_builder.refresh()

                                op_sel.on_value_change(lambda: _on_operator_change())

                                active_operator = str(node.get('operator') or '')
                                active_field = _normalize_field(node.get('field'))
                                if active_operator in {'empty', 'not_empty'}:
                                    ui.input(value='No value required').props('outlined dense readonly').classes('flex-1')
                                elif active_field == 'tags':
                                    tag_values = node.get('value') if isinstance(node.get('value'), list) else []
                                    tags_in = ui.select(tag_options, value=tag_values, multiple=True).props('outlined dense use-chips use-input new-value-mode=add input-debounce=0').classes('flex-1')
                                    tags_in.bind_value(node, 'value')
                                else:
                                    val_in = ui.input(value=str(node.get('value') or '')).props('outlined dense clearable').classes('flex-1')
                                    val_in.bind_value(node, 'value')

                                ui.button(icon='delete', on_click=lambda g=group, i=idx: (g['children'].pop(i), render_builder.refresh())).props('flat dense color=negative')

            render_group(group=root, depth=0)

        with ui.card().props('flat bordered').classes('pv-surface w-full no-shadow pv-auto-marker-section'):
            with ui.row().classes('w-full items-center gap-2 flex-wrap'):
                ui.label('Rules').classes('text-sm font-medium')
                ui.label('Build conditions to include papers in this auto marker.').classes('text-sm pv-text-dimmer')
            render_builder()

    def open_delete(self, marker: MarkerItem) -> None:
        self._delete_dialog.clear()
        with self._delete_dialog, dialog_card(max_width_class='max-w-2xl'):
            dialog_header(title='Delete Marker', icon='delete_outline')
            ui.label(f'Delete “{marker.name}”?').classes('text-sm pv-text-dimmer')

            with dialog_actions_row():
                ui.button('Cancel', on_click=self._delete_dialog.close).props('flat color=negative')

                def confirm() -> None:
                    try:
                        delete_marker(marker_id=marker.id, user_id=self._user_id)
                    except Exception as e:
                        ui.notify(str(e), color='negative')
                        return
                    ui.notify('Marker deleted', color='positive')
                    self._delete_dialog.close()
                    self._on_changed()

                ui.button('Delete', on_click=confirm).props('color=negative')

        self._delete_dialog.open()


__all__ = ['MarkerDialogs', 'FIELD_OPTIONS', 'OPS_TEXT', 'OPS_TAGS', 'OPS_EXACT']
