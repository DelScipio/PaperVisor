from nicegui import ui
import urllib.parse
from papervisor.services.media import preview_image_path_for, file_to_data_url

def dummy_cover_data_url(*, title: str | None) -> str:
    t = (title or '').strip() or 'No cover available'
    # Keep SVG simple and theme-agnostic.
    svg = f"""<svg xmlns='http://www.w3.org/2000/svg' width='480' height='720' viewBox='0 0 480 720'>
<rect width='480' height='720' rx='24' fill='#2b2b2b'/>
<rect x='32' y='32' width='416' height='656' rx='18' fill='#3a3a3a'/>
<text x='240' y='340' text-anchor='middle' font-family='Arial, sans-serif' font-size='22' fill='#d0d0d0'>No cover available</text>
<text x='240' y='385' text-anchor='middle' font-family='Arial, sans-serif' font-size='16' fill='#b0b0b0'>{t[:42]}</text>
</svg>"""
    return 'data:image/svg+xml;utf8,' + urllib.parse.quote(svg)

def render_media_box(*, paper, file_type: str, try_regen_fn, try_fetch_fn) -> None:
    if not paper.file_path:
        ui.label('No preview').classes('text-xs pv-text-dimmer')
        return

    prev = preview_image_path_for(paper_id=paper.id)
    img_src: str | None = None
    if prev is not None and prev.exists():
        img_src = file_to_data_url(prev)
    else:
        ui.label('No preview yet').classes('text-xs pv-text-dimmer')
        img_src = dummy_cover_data_url(title=paper.title)

    # Image with hover overlay actions.
    with ui.element('div').classes('pv-meta-cover relative group w-full max-w-[240px] mx-auto'):
        ui.image(img_src).classes('w-full')
        with ui.row().classes(
            'absolute top-2 right-2 gap-1 opacity-0 group-hover:opacity-100 transition-opacity'
        ):
            if file_type == 'paper':
                ui.button('Snapshot', on_click=try_regen_fn).props('flat dense').classes('pv-meta-action-btn')
            else:
                ui.button('Fetch', on_click=try_fetch_fn).props('flat dense').classes('pv-meta-action-btn')
                ui.button('Regen', on_click=try_regen_fn).props('flat dense').classes('pv-meta-action-btn')
