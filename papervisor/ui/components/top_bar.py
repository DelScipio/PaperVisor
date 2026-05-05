from __future__ import annotations

from collections.abc import Callable
import time

from nicegui import ui


def top_bar(
    *,
    on_toggle_left: Callable[[], None] | None = None,
    on_toggle_filters: Callable[[], None] | None = None,
    on_import: Callable[[], None] | None = None,
    on_logout: Callable[[], None] | None = None,
    search_value: str | None = None,
    search_mode: str = "all",
    on_search_change: Callable[[str], None] | None = None,
    on_search_mode_change: Callable[[str], None] | None = None,
    inbox_count: int | None = None,
    on_open_inbox: Callable[[], None] | None = None,
    is_admin: bool = False,
    on_open_profile: Callable[[], None] | None = None,
) -> None:
    scope_options = {
        "all": "All",
        "title": "Title",
        "authors": "Authors",
        "publisher": "Publisher",
        "journal": "Journal",
        "tags": "Tags",
        "doi": "DOI",
        "isbn": "ISBN",
    }

    # Accept option keys, labels, and common aliases from Quasar/NiceGUI events.
    scope_aliases = {
        "all": "all",
        "any": "all",
        "title": "title",
        "titles": "title",
        "author": "authors",
        "authors": "authors",
        "publisher": "publisher",
        "publishers": "publisher",
        "journal": "journal",
        "journals": "journal",
        "tag": "tags",
        "tags": "tags",
        "doi": "doi",
        "isbn": "isbn",
    }

    label_to_key = {str(v).strip().lower(): str(k) for k, v in scope_options.items()}

    def _normalize_scope_mode(raw: object) -> str:
        s = str(raw or "").strip()
        if s in scope_options:
            return s
        sl = s.lower()
        if sl in label_to_key:
            return label_to_key[sl]
        return scope_aliases.get(sl, "all")

    initial_scope_mode = _normalize_scope_mode(search_mode)

    # Keep the search bar on its own row for small/medium screens (better usability),
    # and switch to a single-row layout only on large screens.
    with ui.row().classes(
        "w-full max-w-none items-center gap-3 px-4 py-2 flex-wrap lg:flex-nowrap"
    ):
        with ui.row().classes("items-center gap-2 flex-nowrap"):
            if on_toggle_left is not None:
                ui.button(icon="menu", on_click=on_toggle_left).props(
                    'dense flat round aria-label="Menu"'
                ).classes("pv-topbar-btn").tooltip("Menu")

            if on_toggle_filters is not None:
                ui.button(icon="tune", on_click=on_toggle_filters).props(
                    'dense flat round aria-label="Filters"'
                ).classes("pv-topbar-btn").tooltip("Filters")

            with (
                ui.button(on_click=lambda: ui.navigate.to("/"))
                .props("flat dense no-caps")
                .classes("px-3 py-1 pv-brand-btn")
            ):
                ui.label("PaperVisor").classes("text-lg font-semibold")

        ui.space()

        with ui.row().classes(
            "items-center w-full lg:flex-1 lg:justify-end order-last lg:order-none"
        ):
            with ui.row().classes(
                "items-center pv-search-pair flex-nowrap w-full lg:max-w-[680px]"
            ):
                with (
                    ui.input(placeholder="Search...")
                    .props("dense outlined clearable")
                    .classes("pv-search-input flex-1 min-w-0") as search
                ):
                    if search_value is not None:
                        search.value = search_value
                    if on_search_change is not None:
                        # Debounce to reduce requests while typing.
                        pending = False
                        last_change = 0.0
                        latest_value = str(search.value or "")
                        last_sent = None

                        def _schedule(value: str) -> None:
                            nonlocal pending, last_change, latest_value
                            pending = True
                            last_change = time.monotonic()
                            latest_value = str(value or "")

                        def _flush() -> None:
                            nonlocal pending, last_sent
                            pending = False
                            v = str(latest_value or "")
                            if v == last_sent:
                                return
                            last_sent = v
                            on_search_change(v)

                        def _poll() -> None:
                            nonlocal pending, last_change
                            if not pending:
                                return
                            if (time.monotonic() - float(last_change)) < 0.35:
                                return
                            _flush()

                        ui.timer(0.10, _poll)

                        # Use event args (new model value). Reading `search.value` here can lag by 1 char.
                        def _on_search_event(e) -> None:
                            args = getattr(e, "args", "")
                            if isinstance(args, dict):
                                args = args.get("value", "")
                            _schedule(str(args or ""))

                        search.on("update:model-value", _on_search_event)
                        search.on("keydown.enter", lambda _e: _flush())
                    with search.add_slot("prepend"):
                        ui.icon("search").classes("pv-text-dimmer")

                mode_select = (
                    ui.select(
                        scope_options,
                        value=initial_scope_mode,
                    )
                    .props(
                        'dense outlined options-dense standout bg-color="black" filled '
                        'dropdown-icon="expand_more" popup-content-class="pv-menu pv-no-shadow"'
                    )
                    .classes("pv-search-filter w-[120px] lg:w-[150px] shrink-0")
                )
                if on_search_mode_change is not None:
                    last_mode_sent = initial_scope_mode

                    def _emit_search_mode(raw_value: object) -> None:
                        nonlocal last_mode_sent
                        next_mode = _normalize_scope_mode(raw_value)
                        if next_mode == last_mode_sent:
                            return
                        last_mode_sent = next_mode
                        on_search_mode_change(next_mode)

                    def _on_search_mode_event(e) -> None:
                        args = getattr(e, "args", None)
                        if isinstance(args, dict):
                            args = args.get("value", None)
                        _emit_search_mode(args)

                    mode_select.on("update:model-value", _on_search_mode_event)
                    mode_select.on("change", _on_search_mode_event)

                    def _poll_mode_sync() -> None:
                        # Fallback: some NiceGUI/Quasar interactions can miss event delivery.
                        _emit_search_mode(getattr(mode_select, "value", None))

                    ui.timer(0.30, _poll_mode_sync)

        with ui.row().classes("items-center gap-2 flex-nowrap"):
            if on_open_inbox is not None:
                count = int(inbox_count or 0)
                inbox_aria = f"Inbox, {count} unread {'message' if count == 1 else 'messages'}" if count > 0 else "Inbox"
                with (
                    ui.button(icon="notifications", on_click=on_open_inbox)
                    .props(f'dense flat round aria-label="{inbox_aria}"')
                    .classes("pv-topbar-btn")
                    .tooltip(inbox_aria)
                ):
                    if count > 0:
                        ui.badge(str(count)).props('color="primary"').classes("pv-chip")

            import_handler = on_import or (lambda: None)
            ui.button(icon="cloud_upload", on_click=import_handler).props(
                'dense flat round aria-label="Upload"'
            ).classes("pv-topbar-btn").tooltip("Upload")

            if is_admin:
                ui.button(
                    icon="settings", on_click=lambda: ui.navigate.to("/admin")
                ).props('dense flat round aria-label="Settings"').classes(
                    "pv-topbar-btn"
                ).tooltip("Settings")

            if on_open_profile is not None:
                ui.button(icon="person", on_click=on_open_profile).props(
                    'dense flat round aria-label="Profile"'
                ).classes("pv-topbar-btn").tooltip("Profile")

            if on_logout is not None:
                ui.button(icon="logout", on_click=on_logout).props(
                    'dense flat round aria-label="Logout"'
                ).classes("pv-topbar-btn").tooltip("Logout")
