from nicegui import ui
from papervisor.services.patterns import format_authors_et_al


def kv_cell(*, label: str, value: str) -> tuple[ui.element, ui.label]:
    with ui.column().classes("min-w-0 gap-0 py-1") as c:
        ui.label(label).classes("pv-meta-kv-label")
        v = ui.label(value or "—").classes("pv-meta-kv-value")
    return c, v


def kv_link_cell(*, label: str, value: str, href: str) -> tuple[ui.element, ui.link]:
    with ui.column().classes("min-w-0 gap-0 py-1") as c:
        ui.label(label).classes("pv-meta-kv-label")
        v = ui.link(value or "—", href, new_tab=True).classes(
            "pv-meta-kv-value pv-meta-kv-link"
        )
    return c, v


def section_card(*, icon: str, title: str) -> ui.card:
    c = ui.card().props("flat").classes("pv-meta-section w-full no-shadow")
    with c:
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon(icon).classes("text-primary text-base")
            ui.label(title).classes("pv-meta-section-title")
    return c


def is_doi_url(url: str, doi: str) -> bool:
    u = str(url or "").strip().lower().rstrip("/")
    d = str(doi or "").strip().lower()
    if not u or not d:
        return False
    return (
        u == f"https://doi.org/{d}"
        or u == f"http://doi.org/{d}"
        or u == f"https://dx.doi.org/{d}"
        or u == f"http://dx.doi.org/{d}"
    )


def render_details_view(
    paper,
    open_replace_dlg_fn=None,
    download_paper_fn=None,
    copy_path_fn=None,
) -> dict[str, ui.element]:
    """Render the read-only details view and return a dict of specific row elements for visibility toggling."""
    rows = {}

    header_card = (
        ui.card().props("flat bordered").classes("pv-meta-header w-full no-shadow")
    )
    with header_card:
        with ui.row().classes("w-full items-start justify-between gap-4"):
            with ui.column().classes("min-w-0 flex-1 gap-1"):
                ui.label(paper.title or "").classes(
                    "text-xl font-bold break-words tracking-tight"
                )
            with ui.element("span").classes("pv-meta-type-badge shrink-0"):
                ui.label("Book" if (paper.file_type or "paper") == "book" else "Paper")

        # File actions row
        with ui.row().classes(
            "pv-meta-file-row w-full items-center justify-between gap-2 mt-3"
        ):
            with ui.row().classes("items-center gap-2 min-w-0 flex-1"):
                ui.label(paper.file_path or "—").classes("text-sm truncate min-w-0")
            with ui.row().classes("items-center gap-1 shrink-0"):
                ui.button(icon="upload", on_click=open_replace_dlg_fn).props(
                    "flat dense"
                ).classes("pv-meta-action-btn").tooltip("Replace file")
                ui.button(icon="download", on_click=download_paper_fn).props(
                    "flat dense"
                ).classes("pv-meta-action-btn").tooltip("Download")
                ui.button(icon="content_copy", on_click=copy_path_fn).props(
                    "flat dense"
                ).classes("pv-meta-action-btn").tooltip("Copy file path")

    cards_grid = ui.element("div").classes("w-full grid grid-cols-1 gap-1")
    with cards_grid:
        id_card = section_card(icon="badge", title="Details")
        with id_card:
            id_grid = ui.element("div").classes(
                "w-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-4 gap-y-1"
            )
            with id_grid:
                kv_cell(label="Title", value=paper.title or "")
                kv_cell(
                    label="Authors", value=format_authors_et_al(paper.authors or "")
                )
                kv_cell(label="Year", value=paper.published_year or "")

                rows["publisher"], _ = kv_cell(
                    label="Publisher", value=paper.publisher or ""
                )
                rows["journal"], _ = kv_cell(label="Journal", value=paper.journal or "")

                doi_href = f"https://doi.org/{paper.doi}" if paper.doi else ""
                rows["doi"], _ = kv_link_cell(
                    label="DOI", value=paper.doi or "", href=doi_href
                )
                rows["isbn"], _ = kv_cell(label="ISBN", value=paper.isbn or "")

                rows["pubdate"], _ = kv_cell(
                    label="Publication", value=paper.publication_date or ""
                )
                rows["lang"], _ = kv_cell(label="Language", value=paper.language or "")
                rows["series"], _ = kv_cell(label="Series", value=paper.series or "")
                rows["series_idx"], _ = kv_cell(
                    label="Series #", value=paper.series_index or ""
                )
                rows["pages"], _ = kv_cell(
                    label="Pages", value=str(paper.page_count or "")
                )

                with ui.column().classes("min-w-0 gap-0.5") as view_genres_row:
                    ui.label("Genres").classes("text-xs pv-text-dimmer")
                    ui.label(paper.genres or "—").classes("text-sm")
                rows["genres"] = view_genres_row

                rows["url"], _ = kv_cell(label="URL", value=paper.url or "")
                rows["volume"], _ = kv_cell(label="Volume", value=paper.volume or "")
                rows["issue"], _ = kv_cell(label="Issue", value=paper.issue or "")
                rows["pages2"], _ = kv_cell(label="Pages", value=paper.pages or "")
                rows["keywords"], _ = kv_cell(
                    label="Keywords", value=paper.keywords or ""
                )

    desc_card = ui.card().props("flat").classes("pv-meta-desc-card w-full no-shadow")
    with desc_card:
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("subject").classes("text-primary text-base")
            ui.label("Description").classes("pv-meta-section-title")

        with ui.column().classes("w-full gap-1"):
            desc_text = str(
                paper.description
                if (paper.file_type or "paper") == "book"
                else paper.abstract or ""
            ).strip()
            view_desc_collapsed = ui.label(desc_text).classes(
                "pv-meta-desc-text break-words line-clamp-5"
            )
            view_desc_full = ui.label(desc_text).classes(
                "pv-meta-desc-text break-words"
            )
            view_desc_full.set_visibility(False)

            show_toggle = len(desc_text) >= 200
            desc_toggle = (
                ui.label("Show more")
                .classes("pv-meta-desc-toggle w-fit")
                .tooltip("Expand/collapse")
            )
            if not show_toggle:
                try:
                    desc_toggle.set_visibility(False)
                except Exception:
                    desc_toggle.visible = False

            state = {"expanded": False}

            def _toggle_desc(
                e, state=state, c=view_desc_collapsed, f=view_desc_full, t=desc_toggle
            ):
                state["expanded"] = not state["expanded"]
                if state["expanded"]:
                    try:
                        c.set_visibility(False)
                        f.set_visibility(True)
                    except Exception:
                        c.visible = False
                        f.visible = True
                    t.text = "Show less"
                else:
                    try:
                        c.set_visibility(True)
                        f.set_visibility(False)
                    except Exception:
                        c.visible = True
                        f.visible = False
                    t.text = "Show more"

            desc_toggle.on("click", _toggle_desc)

    return rows
