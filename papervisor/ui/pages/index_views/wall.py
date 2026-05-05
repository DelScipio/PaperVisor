from __future__ import annotations

from nicegui import ui
from dataclasses import replace

from papervisor.domain import PaperItem
from papervisor.services.papers import list_papers_filtered
from papervisor.services.markers import list_marker_papers_filtered
from papervisor.services.papers import PaperFilters
from papervisor.ui.components.poster_grid import poster_wall
from papervisor.ui.components.list_view import list_wall
from papervisor.ui.components.page_states import inline_loading_state


def render_wall_section(
    *,
    user_id: int,
    title: str,
    papers: list[PaperItem],
    view_name: str,
    has_more: bool,
    open_metadata,
    open_reader,
    open_share_paper,
    on_refresh_left_nav,
    remove_mode: str | None = None,
    on_empty_action=None,
    display_mode: str = "grid",
    get_list_limit,
    load_more_fn,
) -> None:
    with ui.column().classes("w-full"):

        def _changed() -> None:
            on_refresh_left_nav()

        wall_kwargs: dict[str, object] = {
            "user_id": user_id,
            "title": title,
            "papers": papers,
            "on_open_metadata": open_metadata,
            "on_open_reader": open_reader,
            "on_share_paper": open_share_paper,
            "on_changed": _changed,
            "view": view_name,
        }
        if remove_mode is not None:
            wall_kwargs["remove_mode"] = remove_mode
        if on_empty_action is not None:
            wall_kwargs["on_empty_action"] = on_empty_action

        if display_mode == "list":
            list_wall(**wall_kwargs)
        else:
            poster_wall(**wall_kwargs)
        _render_infinite_loader(has_more=has_more, load_more_fn=load_more_fn)


def _render_infinite_loader(*, has_more: bool, load_more_fn) -> None:
    if not has_more:
        return

    # Fallback button (kept hidden; JS triggers it when sentinel is visible).
    ui.button("", on_click=lambda _e=None: load_more_fn()).props(
        "id=pv_infinite_btn"
    ).classes("hidden")

    # Sentinel element observed by IntersectionObserver.
    ui.element("div").props("id=pv_infinite_sentinel").style("height: 1px; width: 100%")
    inline_loading_state("Loading more…")

    ui.run_javascript(
        """
(function(){
    const sentinel = document.getElementById('pv_infinite_sentinel');
    const btn = document.getElementById('pv_infinite_btn');
    if (!sentinel || !btn) return;

    // Avoid piling up observers across refreshes.
    if (window.pvInfObs) {
        try { window.pvInfObs.disconnect(); } catch (e) {}
    }

    window.pvInfObs = new IntersectionObserver((entries) => {
        for (const e of entries) {
            if (e.isIntersecting) {
                try { window.pvInfObs.disconnect(); } catch (err) {}
                btn.click();
                break;
            }
        }
    }, { root: null, rootMargin: '600px 0px', threshold: 0.01 });

    window.pvInfObs.observe(sentinel);
})();
        """
    )


def _paged_query(fetch_page, get_list_limit) -> tuple[list[PaperItem], bool]:
    lim = get_list_limit()
    raw = fetch_page(lim + 1)
    has_more = len(raw) > lim
    return raw[:lim], has_more


def _paged_filtered(*, get_list_limit, **kwargs) -> tuple[list[PaperItem], bool]:
    return _paged_query(
        lambda limit: list_papers_filtered(limit=limit, **kwargs), get_list_limit
    )


def _paged_marker_filtered(*, get_list_limit, **kwargs) -> tuple[list[PaperItem], bool]:
    return _paged_query(
        lambda limit: list_marker_papers_filtered(limit=limit, **kwargs), get_list_limit
    )


def render_query_views(
    *,
    user_id: int,
    view: str,
    state,
    eff_library_ids: list[str] | None,
    eff_filters: PaperFilters,
    sort_key: str,
    open_metadata,
    open_reader,
    open_share_paper,
    on_refresh_left_nav,
    open_upload_dialog,
    display_mode: str,
    get_list_limit,
    load_more_fn,
) -> bool:
    def _filtered_wall_section(
        *,
        title: str,
        query: str | None,
        mode: str,
        sort: str,
        view_name: str,
        on_empty_action=None,
    ) -> None:
        papers, has_more = _paged_filtered(
            get_list_limit=get_list_limit,
            user_id=user_id,
            library_ids=eff_library_ids,
            query=query,
            mode=mode,
            filters=eff_filters,
            sort=sort,
        )
        render_wall_section(
            user_id=user_id,
            title=title,
            papers=papers,
            view_name=view_name,
            has_more=has_more,
            open_metadata=open_metadata,
            open_reader=open_reader,
            open_share_paper=open_share_paper,
            on_refresh_left_nav=on_refresh_left_nav,
            on_empty_action=on_empty_action,
            display_mode=display_mode,
            get_list_limit=get_list_limit,
            load_more_fn=load_more_fn,
        )

    if view == "search":
        query = state.search_query.strip()
        mode = state.search_mode
        _filtered_wall_section(
            title=f"Search: {query}",
            query=query,
            mode=mode,
            sort=sort_key,
            view_name="search",
        )
        return True

    if view == "recent":
        _filtered_wall_section(
            title="Recently added",
            query=None,
            mode="all",
            sort="recent",
            view_name="all",
            on_empty_action=open_upload_dialog,
        )
        return True

    return False


def render_category_views(
    *,
    user_id: int,
    view: str,
    eff_library_ids: list[str] | None,
    eff_filters: PaperFilters,
    sort_key: str,
    open_metadata,
    open_reader,
    open_share_paper,
    on_refresh_left_nav,
    display_mode: str,
    get_list_limit,
    load_more_fn,
) -> bool:
    def _category_section(*, title: str, category: str) -> None:
        category_filters = (
            replace(eff_filters, favorites_only=True)
            if category == "favorites"
            else replace(eff_filters, to_read_only=True)
        )
        papers, has_more = _paged_filtered(
            get_list_limit=get_list_limit,
            user_id=user_id,
            library_ids=eff_library_ids,
            query=None,
            mode="all",
            filters=category_filters,
            sort=sort_key,
        )
        render_wall_section(
            user_id=user_id,
            title=title,
            papers=papers,
            view_name=category,
            has_more=has_more,
            open_metadata=open_metadata,
            open_reader=open_reader,
            open_share_paper=open_share_paper,
            on_refresh_left_nav=on_refresh_left_nav,
            remove_mode=category,
            display_mode=display_mode,
            get_list_limit=get_list_limit,
            load_more_fn=load_more_fn,
        )

    if view == "favorites":
        _category_section(title="Favorites", category="favorites")
        return True

    if view == "to_read":
        _category_section(title="To Read", category="to_read")
        return True

    return False


def render_marker_view(
    *,
    user_id: int,
    view: str,
    marker_id: str | None,
    marker_name_by_id: dict[str, str],
    eff_library_ids: list[str] | None,
    eff_filters: PaperFilters,
    sort_key: str,
    open_metadata,
    open_reader,
    open_share_paper,
    on_refresh_left_nav,
    display_mode: str,
    get_list_limit,
    load_more_fn,
) -> bool:
    if view != "marker" or not marker_id:
        return False

    title = marker_name_by_id.get(marker_id, "Marker")
    papers, has_more = _paged_marker_filtered(
        get_list_limit=get_list_limit,
        user_id=user_id,
        marker_id=marker_id,
        library_ids=eff_library_ids,
        filters=eff_filters,
        sort=sort_key,
    )
    render_wall_section(
        user_id=user_id,
        title=title,
        papers=papers,
        view_name="marker",
        has_more=has_more,
        open_metadata=open_metadata,
        open_reader=open_reader,
        open_share_paper=open_share_paper,
        on_refresh_left_nav=on_refresh_left_nav,
        display_mode=display_mode,
        get_list_limit=get_list_limit,
        load_more_fn=load_more_fn,
    )
    return True
