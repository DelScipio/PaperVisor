from nicegui import ui


def _split_multi_text(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    raw = str(value).strip()
    if not raw:
        return []
    normalized = raw.replace(';', ',')
    return [part.strip() for part in normalized.split(',') if part.strip()]

def render_edit_fields(*, locks, toggle_lock_fn, paper, update_field_fn) -> tuple[dict[str, ui.element], dict[str, ui.element], dict[str, ui.element]]:
    """Render the edit fields and return (inputs_dict, rows_dict, lock_btns_dict)."""
    
    inputs = {}
    rows = {}
    
    def lock_icon(key: str) -> str:
        return 'lock' if bool(locks.get(key)) else 'lock_open'
        
    lock_btns = {}
    def _make_lock_button(key: str) -> ui.button:
        b = ui.button(icon=lock_icon(key), on_click=lambda _e=None, k=key: toggle_lock_fn(k)).props('flat dense').classes('pv-meta-lock-btn')
        lock_btns[key] = b
        return b
        
    with ui.row().classes('w-full gap-2') as r:
        inputs['type'] = ui.select(
            {'paper': 'Paper', 'book': 'Book'},
            label='Type',
            value=paper.file_type or 'paper'
        ).props('outlined dense').classes('w-40 pv-meta-field')
        inputs['type'].on('update:model-value', lambda e: update_field_fn('type', e.args))
        
        inputs['title'] = ui.input(label='Title', value=paper.title or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['title'].on('update:model-value', lambda e: update_field_fn('title', e.args))
        _make_lock_button('title')
    rows['type_title'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['doi'] = ui.input(label='DOI', value=paper.doi or '').props('outlined dense clearable').classes('flex-1 pv-meta-field')
        inputs['doi'].on('update:model-value', lambda e: update_field_fn('doi', e.args))
        _make_lock_button('doi')
    rows['doi'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['isbn'] = ui.input(label='ISBN', value=paper.isbn or '').props('outlined dense clearable').classes('flex-1 pv-meta-field')
        inputs['isbn'].on('update:model-value', lambda e: update_field_fn('isbn', e.args))
        _make_lock_button('isbn')
    rows['isbn'] = r
        
    with ui.row().classes('w-full gap-2') as r:
        inputs['authors'] = ui.input(label='Authors', value=paper.authors or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['authors'].on('update:model-value', lambda e: update_field_fn('authors', e.args))
        _make_lock_button('authors')

        inputs['year'] = ui.input(label='Year', value=paper.published_year or '').props('outlined dense').classes('w-32 pv-meta-field')
        inputs['year'].on('update:model-value', lambda e: update_field_fn('year', e.args))
        _make_lock_button('year')
    rows['authors_year'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['journal'] = ui.input(label='Journal', value=paper.journal or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['journal'].on('update:model-value', lambda e: update_field_fn('journal', e.args))
        _make_lock_button('journal')
    rows['journal'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['publisher'] = ui.input(label='Publisher', value=paper.publisher or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['publisher'].on('update:model-value', lambda e: update_field_fn('publisher', e.args))
        _make_lock_button('publisher')
    rows['publisher'] = r

    # Book-specific
    with ui.row().classes('w-full gap-2') as r:
        inputs['pubdate'] = ui.input(label='Publication date', value=paper.publication_date or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['pubdate'].on('update:model-value', lambda e: update_field_fn('publication_date', e.args))
        _make_lock_button('publication_date')

        inputs['lang'] = ui.input(label='Language', value=paper.language or '').props('outlined dense').classes('w-40 pv-meta-field')
        inputs['lang'].on('update:model-value', lambda e: update_field_fn('language', e.args))
        _make_lock_button('language')
    rows['book_row1'] = r

    with ui.row().classes('w-full gap-2') as r:
        inputs['series'] = ui.input(label='Series', value=paper.series or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['series'].on('update:model-value', lambda e: update_field_fn('series', e.args))
        _make_lock_button('series')
        
        inputs['series_idx'] = ui.input(label='Series #', value=paper.series_index or '').props('outlined dense').classes('w-32 pv-meta-field')
        inputs['series_idx'].on('update:model-value', lambda e: update_field_fn('series_index', e.args))
        _make_lock_button('series_index')

        inputs['page_count'] = ui.input(label='Pages', value=str(paper.page_count or '')).props('outlined dense').classes('w-28 pv-meta-field')
        inputs['page_count'].on('update:model-value', lambda e: update_field_fn('page_count', e.args))
        _make_lock_button('page_count')
    rows['book_row2'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['genres'] = ui.select(
            options=[],
            label='Genres',
            value=_split_multi_text(getattr(paper, 'genres', None)),
            multiple=True,
            with_input=True,
            new_value_mode='add-unique',
        ).props('outlined dense use-chips').classes('flex-1 pv-meta-field')
        inputs['genres'].on('update:model-value', lambda e: update_field_fn('genres', e.args))
        opts = _split_multi_text(getattr(paper, 'genres', None))
        inputs['genres'].set_options(opts)
        _make_lock_button('genres')
    rows['genres'] = r

    with ui.row().classes('w-full items-start gap-2') as r:
        inputs['desc'] = ui.textarea(label='Description', value=paper.description or '').props('outlined dense autogrow').classes('flex-1 pv-meta-field')
        inputs['desc'].on('update:model-value', lambda e: update_field_fn('description', e.args))
        _make_lock_button('description')
    rows['description'] = r

    # Paper-specific
    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['url'] = ui.input(label='URL', value=paper.url or '').props('outlined dense').classes('flex-1 min-w-0 pv-meta-field')
        inputs['url'].on('update:model-value', lambda e: update_field_fn('url', e.args))
        _make_lock_button('url')
    rows['url'] = r

    with ui.row().classes('w-full gap-2') as r:
        inputs['volume'] = ui.input(label='Volume', value=paper.volume or '').props('outlined dense').classes('w-32 pv-meta-field')
        inputs['volume'].on('update:model-value', lambda e: update_field_fn('volume', e.args))
        _make_lock_button('volume')
        
        inputs['issue'] = ui.input(label='Issue', value=paper.issue or '').props('outlined dense').classes('w-32 pv-meta-field')
        inputs['issue'].on('update:model-value', lambda e: update_field_fn('issue', e.args))
        _make_lock_button('issue')
        
        inputs['pages'] = ui.input(label='Pages', value=paper.pages or '').props('outlined dense').classes('flex-1 pv-meta-field')
        inputs['pages'].on('update:model-value', lambda e: update_field_fn('pages', e.args))
        _make_lock_button('pages')
    rows['paper_row1'] = r

    with ui.row().classes('w-full items-center gap-2') as r:
        inputs['keywords'] = ui.input('Keywords', value=paper.keywords or '').props('outlined dense').classes('w-full pv-meta-field')
        inputs['keywords'].on('update:model-value', lambda e: update_field_fn('keywords', e.args))
    rows['keywords'] = r

    with ui.row().classes('w-full items-start gap-2') as r:
        inputs['abstract'] = ui.textarea('Abstract', value=paper.abstract or '').props('outlined dense autogrow').classes('flex-1 pv-meta-field')
        inputs['abstract'].on('update:model-value', lambda e: update_field_fn('abstract', e.args))
        _make_lock_button('abstract')
    rows['abstract'] = r

    return inputs, rows, lock_btns
