from __future__ import annotations
import asyncio

from nicegui import ui

from papervisor.services.libraries import list_libraries, list_libraries_for_user
from papervisor.services.sharing import get_library_access
from papervisor.services.markers import list_paper_markers, list_markers, set_paper_markers
from papervisor.services.tags import list_paper_tags, list_tags, set_paper_tags
from papervisor.services.papers import move_paper_to_library, get_paper
from papervisor.ui.dialogs.marker_dialogs import MarkerDialogs

def render_org_box(*, dialog, parent_col) -> None:
    paper = dialog.state.paper
    user_id = dialog._user_id

    can_manage_paper_library = False
    try:
        if user_id is not None and paper.library_id:
            acc = get_library_access(user_id=int(user_id), library_id=str(paper.library_id))
            can_manage_paper_library = bool(acc.is_owner or acc.can_manage)
    except Exception:
        can_manage_paper_library = False

    dialog.can_manage_paper_library = can_manage_paper_library

    try:
        if user_id is not None:
            libs = list_libraries_for_user(user_id=int(user_id))
        else:
            libs = list_libraries()
            
        if user_id is not None:
            move_targets = [
                l for l in libs
                if bool(getattr(l, 'is_owned_by_me', False)) or str(getattr(l, 'shared_role', '')).lower() == 'editor'
            ]
            lib_options_init = {str(l.id): str(l.name) for l in move_targets}
            if paper.library_id and str(paper.library_id) not in lib_options_init:
                cur_name = None
                for l in libs:
                    if str(l.id) == str(paper.library_id):
                        cur_name = str(l.name)
                        break
                lib_options_init[str(paper.library_id)] = cur_name or str(paper.library_id)
        else:
            lib_options_init = {str(l.id): str(l.name) for l in libs}
    except Exception:
        lib_options_init = {}

    with parent_col:
        marker_dialogs = MarkerDialogs(
            on_changed=lambda marker_id=None: _refresh_marker_options(select_new_id=str(marker_id) if marker_id else None),
            user_id=user_id,
        )
        dialog.library_in = ui.select(lib_options_init, label='Library', value=None).props('outlined dense').classes('w-full pv-meta-field')
        
        if paper.library_id and str(paper.library_id) in lib_options_init:
            dialog.library_in.value = str(paper.library_id)
        elif lib_options_init:
            dialog.library_in.value = next(iter(lib_options_init.keys()))
            
        if user_id is not None and not can_manage_paper_library:
            dialog.library_in.disable()

        # Markers
        try:
            all_shelves = [s for s in list_markers(user_id=user_id) if not bool(getattr(s, 'is_smart', False))]
            shelf_options = {str(s.id): str(s.name) for s in all_shelves}
            selected_shelves = list_paper_markers(paper_id=paper.id)
        except Exception:
            shelf_options = {}
            selected_shelves = []

        def _refresh_marker_options(*, select_new_id: str | None = None) -> None:
            try:
                all_shelves2 = [s for s in list_markers(user_id=user_id) if not bool(getattr(s, 'is_smart', False))]
                opts = {str(s.id): str(s.name) for s in all_shelves2}
            except Exception:
                opts = {}

            cur = list(getattr(dialog.shelves_in, 'value', None) or [])
            cur_ids = [str(x).strip() for x in cur if str(x).strip()]
            if select_new_id:
                cur_ids = [*cur_ids, str(select_new_id).strip()]
            cur_ids = [sid for sid in cur_ids if sid in opts]
            try:
                dialog.shelves_in.set_options(opts, value=cur_ids)
            except Exception:
                pass

        def _normalize_marker_ids(raw_values: list[object] | None) -> list[str]:
            try:
                opts = getattr(dialog.shelves_in, 'options', None) or {}
            except Exception:
                opts = {}

            ids: list[str] = []
            by_label: dict[str, str] = {
                str(label).strip().lower(): str(mid)
                for mid, label in dict(opts).items()
                if str(label).strip() and str(mid).strip()
            }
            for raw in raw_values or []:
                token = str(raw or '').strip()
                if not token:
                    continue
                if token in opts:
                    ids.append(token)
                    continue
                mapped = by_label.get(token.lower())
                if mapped:
                    ids.append(mapped)
            # keep stable order + dedupe
            deduped: list[str] = []
            seen: set[str] = set()
            for marker_id in ids:
                if marker_id in seen:
                    continue
                seen.add(marker_id)
                deduped.append(marker_id)
            return deduped

        dialog.shelves_in = (
            ui.select(
                shelf_options,
                label='Markers',
                value=[sid for sid in (selected_shelves or []) if str(sid) in shelf_options],
                multiple=True,
                with_input=True,
            )
            .props('outlined dense use-chips input-debounce=0')
            .classes('w-full pv-meta-field')
        )
        with ui.button('New marker', icon='add', on_click=lambda _e=None: None).props('outline dense color=primary').classes('w-full pv-meta-action-btn').style('font-size:12px; justify-content:center') as new_marker_btn:
            with ui.menu().classes('pv-menu pv-no-shadow'):
                ui.menu_item('New Marker', on_click=lambda: marker_dialogs.open_create(on_created=lambda mid: _refresh_marker_options(select_new_id=mid)))
                ui.menu_item('New Auto Marker', on_click=lambda: marker_dialogs.open_create_auto(on_created=lambda mid: _refresh_marker_options(select_new_id=mid)))
        if user_id is None:
            new_marker_btn.disable()

        # Tags
        try:
            tag_options = list_tags()
            selected_tags = list_paper_tags(paper_id=paper.id)
        except Exception:
            tag_options = []
            selected_tags = []

        try:
            tag_set = {str(t) for t in (tag_options or []) if str(t).strip()}
            for t in selected_tags or []:
                if str(t).strip():
                    tag_set.add(str(t))
            tag_options = sorted(tag_set, key=lambda s: s.lower())
        except Exception:
            pass

        dialog.tags_in = (
            ui.select(
                tag_options,
                label='Tags',
                value=selected_tags,
                multiple=True,
                with_input=True,
                new_value_mode='add-unique',
            )
            .props('outlined dense use-chips input-debounce=0')
            .classes('w-full pv-meta-field')
        )
        if user_id is not None and not can_manage_paper_library:
            dialog.tags_in.disable()

        def _save_classification() -> None:
            ui.notify('Saving...', color='info')
            new_library_id = str(dialog.library_in.value or '').strip() or None
            if not new_library_id:
                ui.notify('Library is required', color='warning')
                return
            updated = None
            if (paper.library_id or None) != new_library_id:
                if user_id is not None and not can_manage_paper_library:
                    ui.notify('Not allowed to move between libraries', color='negative')
                    return
                updated = move_paper_to_library(
                    paper_id=paper.id,
                    library_id=new_library_id,
                    rename_using_pattern=True,
                    user_id=user_id,
                )

            try:
                marker_ids = _normalize_marker_ids(list(dialog.shelves_in.value or []))
                set_paper_markers(paper_id=paper.id, marker_ids=marker_ids, user_id=user_id)
            except Exception as ex:
                ui.notify(str(ex), color='negative')
            try:
                if user_id is not None and not can_manage_paper_library:
                    pass
                else:
                    set_paper_tags(paper_id=paper.id, tags=list(dialog.tags_in.value or []), user_id=user_id)
            except Exception as ex:
                ui.notify(str(ex), color='negative')

            refreshed = get_paper(paper_id=paper.id) or updated or paper
            dialog._apply_paper_obj(refreshed)
            ui.notify('Saved', color='positive')
            if dialog._on_changed is not None:
                dialog._on_changed()

        dialog.class_save_row = ui.row().classes('w-full')
        with dialog.class_save_row:
            dialog.class_save_btn = ui.button('Save', icon='save', on_click=_save_classification).props('outline').classes('w-full pv-meta-save-btn')
