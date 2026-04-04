from __future__ import annotations
import asyncio
import json
from pathlib import Path
import uuid
from typing import Callable
from nicegui import ui
from contextlib import asynccontextmanager

from papervisor.services.papers import (
    update_paper_metadata,
    delete_paper,
)
from papervisor.services.media import (
    cover_path_for_ext,
    fetch_and_save_cover,
    generate_pdf_first_page_thumbnail,
)
from papervisor.services.epub import extract_epub_cover
from papervisor.services.doi import fetch_doi_metadata, extract_doi_from_pdf
from papervisor.services.isbn import fetch_openlibrary_metadata, extract_isbn_from_epub, extract_isbn_from_pdf
from papervisor.services.google_books import fetch_googlebooks_metadata, search_googlebooks_isbn
from papervisor.services.settings import (
    get_book_isbn_discovery_providers,
    get_book_metadata_fetch_providers,
    get_metadata_provider_timeout_seconds,
)
from papervisor.core.config import get_paths

class MetadataActions:
    """Encapsulates logic for metadata dialog actions to reduce main dialog size."""
    
    def __init__(self, dialog):
        """Pass the main dialog instance so we can read its state and notify it."""
        self.dialog = dialog
        
    @property
    def state(self):
        return self.dialog.state
        
    @property
    def paper(self):
        return self.dialog.state.paper

    def _notify(self, message: str, *, color: str = 'info') -> None:
        try:
            ui.notify(message, color=color)
        except RuntimeError as ex:
            if 'slot belongs to has been deleted' in str(ex):
                return
            raise

    @asynccontextmanager
    async def _action_context(self, busy_msg: str, enable_actions: bool = True):
        self.state.fetch_cancel_requested = False
        self.dialog._set_busy(busy_msg)
        if enable_actions:
            self.dialog._set_actions_enabled(False)
        try:
            yield
        except asyncio.CancelledError:
            pass
        except Exception as ex:
            clean_msg = busy_msg.replace("…", "").replace("...", "")
            self._notify(f'{clean_msg} failed: {ex}', color='negative')
        finally:
            self.dialog._set_busy(None)
            if enable_actions:
                self.dialog._set_actions_enabled(True)

    def _get_str(self, key: str) -> str | None:
        raw = self.dialog._get_input_value(key)
        if key == 'genres' and isinstance(raw, (list, tuple, set)):
            normalized = [str(v).strip() for v in raw if str(v).strip()]
            if not normalized:
                return None
            return ', '.join(normalized)
        val = str(raw or '').strip()
        return val if val else None

    def _get_int(self, key: str) -> int | None:
        try:
            val = str(self.dialog._get_input_value(key) or '').strip()
            return int(val) if val else None
        except ValueError:
            return None

    async def save_metadata(self) -> None:
        if not self.paper:
            return
            
        btn = self.dialog.save_btn
        if btn: btn.disable()
            
        try:
            self.dialog._set_busy('Saving…')
            self._notify('Saving...', color='info')

            old_file_name = Path(str(getattr(self.paper, 'file_path', '') or '')).name

            new_file_type = self._get_str('type') or self.paper.file_type or 'paper'
            new_file_type = new_file_type.lower()

            # Always persist both book and paper fields so switching type doesn't lose data.
            updated = update_paper_metadata(
                paper_id=self.paper.id,
                file_type=new_file_type,
                title=self._get_str('title') or '',
                doi=self._get_str('doi'),
                isbn=self._get_str('isbn'),
                authors=self._get_str('authors'),
                published_year=self._get_str('year'),
                journal=self._get_str('journal'),
                publisher=self._get_str('publisher'),

                description=self._get_str('desc'),
                language=self._get_str('lang'),
                genres=self._get_str('genres'),
                publication_date=self._get_str('pubdate'),
                series=self._get_str('series'),
                series_index=self._get_str('series_idx'),
                page_count=self._get_int('page_count'),

                abstract=self._get_str('abstract'),
                url=self._get_str('url'),
                volume=self._get_str('volume'),
                issue=self._get_str('issue'),
                pages=self._get_str('pages'),
                keywords=self._get_str('keywords'),
                rename_using_pattern=True # Ensure file path is migrated properly upon metadata update
            )

            self.dialog._apply_paper_obj(updated)

            new_file_name = Path(str(getattr(updated, 'file_path', '') or '')).name
            if old_file_name and new_file_name and old_file_name != new_file_name:
                stem = Path(new_file_name).stem
                parts = stem.rsplit(' ', 1)
                if len(parts) == 2 and parts[1].isdigit():
                    self._notify(f'Name existed, saved as {new_file_name}', color='info')

            self.state.dirty_state = False
            self.dialog._set_visible(self.dialog.dirty_badge, False)
            
            try:
                self.dialog.tabs.value = 'Details'
            except Exception:
                pass
                
            self._notify('Saved', color='positive')
            if self.dialog._on_changed is not None:
                self.dialog._on_changed()
        except Exception as ex:
            self._notify(str(ex), color='negative')
        finally:
            self.dialog._set_busy(None)
            if btn: btn.enable()

    def download_paper_file(self) -> None:
        try:
            fp = str(self.paper.file_path or '').strip()
            if not fp:
                self._notify('No file path available', color='warning')
                return
            p = Path(fp)
            if not p.is_absolute():
                p = get_paths().library_files_dir / p
            if not p.exists() or not p.is_file():
                self._notify('File not found on disk', color='warning')
                return
            try:
                root = get_paths().library_files_dir.resolve()
                rp = p.resolve()
                if root != rp and root not in rp.parents:
                    self._notify('File is outside library directory', color='warning')
                    return
            except Exception:
                pass
            ui.download(p, filename=p.name)
        except Exception as ex:
            self._notify(str(ex), color='negative')

    async def copy_paper_file_path(self) -> None:
        try:
            fp = str(self.paper.file_path or '').strip()
            if not fp:
                self._notify('No file path available', color='warning')
                return

            p = Path(fp)
            if not p.is_absolute():
                p = get_paths().library_files_dir / p

            await ui.run_javascript(f'navigator.clipboard.writeText({json.dumps(str(p))})')
            self._notify('File path copied', color='positive')
        except Exception as ex:
            self._notify(str(ex), color='negative')

    async def fetch_doi(self):
        if not self.paper:
            return
            
        timeout_sec = get_metadata_provider_timeout_seconds()
        doi = self.dialog._get_input_value('doi')
        if not doi:
            self._notify('Please provide a DOI first.', color='warning')
            return

        async with self._action_context('Fetching Crossref metadata…'):
            meta = await asyncio.to_thread(fetch_doi_metadata, doi=str(doi).strip(), timeout_s=timeout_sec)
            if self.state.fetch_cancel_requested:
                raise asyncio.CancelledError('Fetch canceled by user')
                
            if meta:
                # Apply all fields that aren't locked
                self.dialog._apply_paper(meta)
                self._notify('Metadata updated. Review inside Edit tab.', color='positive')
            else:
                self._notify('No metadata found for this DOI.', color='warning')

    async def fetch_isbn(self):
        if not self.paper:
            return
            
        timeout_sec = get_metadata_provider_timeout_seconds()
        isbn = self.dialog._get_input_value('isbn')
        if not isbn:
            self._notify('Please provide an ISBN first.', color='warning')
            return

        source = 'auto'
        try:
            source = str(self.dialog.book_source_in.value or 'auto').strip()
        except Exception:
            pass

        async with self._action_context('Fetching book metadata…'):
            def _get():
                if self.state.fetch_cancel_requested:
                    raise asyncio.CancelledError('Fetch canceled by user')
                opts = get_book_metadata_fetch_providers() if source == 'auto' else [source]
                for opt in opts:
                    if self.state.fetch_cancel_requested:
                        raise asyncio.CancelledError('Fetch canceled by user')
                    if opt == 'openlibrary':
                        m = fetch_openlibrary_metadata(isbn=str(isbn).strip(), timeout_s=timeout_sec)
                        if m: return m
                    elif opt == 'google':
                        m = fetch_googlebooks_metadata(isbn=str(isbn).strip(), timeout_s=timeout_sec)
                        if m: return m
                return None

            meta = await asyncio.to_thread(_get)
            if meta:
                self.dialog._apply_paper(meta)
                self._notify('Metadata updated. Review inside Edit tab.', color='positive')
            else:
                self._notify('No data found for this ISBN.', color='warning')

    async def extract_doi(self):
        if not self.paper:
            return
            
        fp = str(self.paper.file_path or '').strip()
        if not fp:
            self._notify('No file attached', color='warning')
            return
        p = Path(fp)
        if not p.is_absolute():
            p = get_paths().library_files_dir / p
        if not p.exists() or not p.is_file() or not str(p).lower().endswith('.pdf'):
            self._notify('A PDF file is required to extract DOI', color='warning')
            return

        async with self._action_context('Analyzing PDF…'):
            doi = await asyncio.to_thread(extract_doi_from_pdf, file_path=str(p))
            if self.state.fetch_cancel_requested:
                raise asyncio.CancelledError('Extraction canceled by user')
            if doi:
                if not self.state.locks.get('doi'):
                    self.dialog._set_input_value('doi', doi)
                self._notify(f'Found DOI: {doi}', color='positive')
            else:
                self._notify('No DOI detected in the first pages.', color='info')

    async def detect_isbn(self):
        if not self.paper:
            return
        fp = str(self.paper.file_path or '').strip()
        if not fp:
            self._notify('No file attached', color='warning')
            return
        p = Path(fp)
        if not p.is_absolute():
            p = get_paths().library_files_dir / p
        if not p.exists() or not p.is_file():
            self._notify('File not found', color='warning')
            return

        timeout_sec = get_metadata_provider_timeout_seconds()
        
        async with self._action_context('Analyzing file…'):
            def _detect():
                if str(p).lower().endswith('.epub'):
                    return extract_isbn_from_epub(file_path=str(p))
                elif str(p).lower().endswith('.pdf'):
                    return extract_isbn_from_pdf(file_path=str(p))
                return None

            isbn = await asyncio.to_thread(_detect)
            if self.state.fetch_cancel_requested:
                raise asyncio.CancelledError('Detection canceled by user')

            if isbn:
                if not self.state.locks.get('isbn'):
                    self.dialog._set_input_value('isbn', isbn)
                self._notify(f'Found ISBN: {isbn}', color='positive')
                return

            self.dialog._set_busy('Searching online catalogs by title/author…')
            t = self._get_str('title') or ''
            a = self._get_str('authors') or ''
            if not t:
                self._notify('No ISBN found (could not search online without title).', color='info')
                return

            def _search():
                opts = get_book_isbn_discovery_providers()
                for opt in opts:
                    if self.state.fetch_cancel_requested:
                        raise asyncio.CancelledError('Search canceled by user')
                    if opt == 'google':
                        res = search_googlebooks_isbn(title=t, author=a, timeout_s=timeout_sec)
                        if res: return res
                return None

            isbn = await asyncio.to_thread(_search)
            if self.state.fetch_cancel_requested:
                raise asyncio.CancelledError('Search canceled by user')

            if isbn:
                if not self.state.locks.get('isbn'):
                    self.dialog._set_input_value('isbn', isbn)
                self._notify(f'Found ISBN via web search: {isbn}', color='positive')
            else:
                self._notify('Could not detect ISBN automatically.', color='info')

    async def regen_snapshot(self):
        if not self.paper:
            return
        fp = str(self.paper.file_path or '').strip()
        if not fp:
            self._notify('No file attached', color='warning')
            return
        p = Path(fp)
        if not p.is_absolute():
            p = get_paths().library_files_dir / p
        if not p.exists() or not p.is_file():
            self._notify('File not found', color='warning')
            return

        self.dialog._set_busy('Generating thumbnail…')
        try:
            if str(p).lower().endswith('.epub'):
                extracted = await asyncio.to_thread(extract_epub_cover, str(p))
                if not extracted:
                    self._notify('Could not extract EPUB cover.', color='warning')
                    return
                data, ext = extracted

                def _write_extracted_cover() -> None:
                    out = cover_path_for_ext(paper_id=str(self.paper.id), ext=ext)
                    out.write_bytes(data)

                await asyncio.to_thread(_write_extracted_cover)
            elif str(p).lower().endswith('.pdf'):
                await asyncio.to_thread(generate_pdf_first_page_thumbnail, file_path=str(p), paper_id=str(self.paper.id))
            else:
                self._notify('Preview only supported for PDF and EPUB.', color='warning')
                return
            
            # Allow file system flush
            await asyncio.sleep(0.5)
            self.dialog._refresh_media()
            self._notify('Preview generated.', color='positive')
        except Exception as ex:
            self._notify(f'Preview generation failed: {ex}', color='negative')
        finally:
            self.dialog._set_busy(None)

    async def fetch_cover(self):
        if not self.paper:
            return
        isbn = str(self.dialog._get_input_value('isbn') or '').strip()
        t = str(self.dialog._get_input_value('title') or '').strip()
        a = str(self.dialog._get_input_value('authors') or '').strip()
        if not isbn and not t:
            self._notify('ISBN or Title required to fetch cover', color='warning')
            return

        self.dialog._set_busy('Fetching cover…')
        timeout_sec = get_metadata_provider_timeout_seconds()
        
        try:
            res = await asyncio.to_thread(
                fetch_and_save_cover,
                paper_id=str(self.paper.id),
                isbn=isbn,
                timeout_s=timeout_sec,
            )
            if res:
                await asyncio.sleep(0.5)
                self.dialog._refresh_media()
                self._notify('Cover fetched.', color='positive')
            else:
                self._notify('No high-quality cover found.', color='warning')
        except Exception as ex:
            self._notify(f'Cover fetch failed: {ex}', color='negative')
        finally:
            self.dialog._set_busy(None)
            
    async def process_replace_upload(self, e):
        """Handle the upload of a replacement file."""
        if not self.paper:
            return
            
        name = str(getattr(e, 'name', None) or getattr(e, 'filename', None) or 'upload.bin')
        content = getattr(e, 'content', None)
        data: bytes | None = None
        
        try:
            if content is None:
                data = None
            elif hasattr(content, 'read'):
                data = content.read()
            elif isinstance(content, (bytes, bytearray)):
                data = bytes(content)
        except Exception:
            data = None

        if not data:
            self._notify('Upload failed (empty file)', color='negative')
            return

        try:
            if self.dialog._user_id is not None and not bool(self.state.can_manage_paper_library):
                self._notify('No permission to replace file', color='warning')
                return
        except Exception:
            pass

        self.dialog._set_busy('Replacing file…')
        try:
            lib_id = str(self.paper.library_id or getattr(self.dialog.library_in, 'value', None) or '').strip()
            
            from papervisor.services.papers import replace_paper_file
            
            imported = await asyncio.to_thread(
                replace_paper_file,
                paper_id=str(self.paper.id),
                original_filename=name,
                content=data,
                library_id=lib_id,
                file_type=str(self.paper.file_type or 'paper'),
            )

            original_name = Path(str(name or '')).name
            final_name = Path(str(getattr(imported, 'saved_path', '') or '')).name
            if original_name and final_name and original_name != final_name:
                self._notify(f'Name existed, saved as {final_name}', color='info')

            self.dialog._apply_paper_obj(imported.paper)

            # Best-effort: regenerate preview for PDFs.
            try:
                fp = str(imported.paper.file_path or '').strip()
                if fp:
                    p = Path(fp)
                    if not p.is_absolute():
                        p = get_paths().library_files_dir / p
                    if str(p).lower().endswith('.pdf') and p.exists() and p.is_file():
                        await asyncio.to_thread(generate_pdf_first_page_thumbnail, file_path=str(p), paper_id=str(imported.paper.id))
            except Exception:
                pass

            self.dialog._refresh_media()
            self._notify('File replaced', color='positive')
            if self.dialog._on_changed is not None:
                self.dialog._on_changed()
            try:
                if self.dialog.replace_dlg:
                    self.dialog.replace_dlg.close()
            except Exception:
                pass
        except Exception as ex:
            self._notify(str(ex), color='negative')
        finally:
            self.dialog._set_busy(None)
