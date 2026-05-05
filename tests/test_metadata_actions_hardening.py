from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs for heavy transitive dependencies so we can import
# papervisor.ui.dialogs.metadata.actions in isolation.
# ---------------------------------------------------------------------------

# Use MagicMock for all stubs so that attribute access (e.g. from X import Y)
# resolves cleanly without AttributeError.
for _name in (
    "fitz",
    "nicegui",
    "nicegui.ui",
    "sqlalchemy",
    "sqlalchemy.orm",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
    "PIL",
    "PIL.Image",
    "papervisor.services.papers",
    "papervisor.services.media",
    "papervisor.services.epub",
    "papervisor.services.doi",
    "papervisor.services.isbn",
    "papervisor.services.google_books",
    "papervisor.services.settings",
    "papervisor.core.config",
):
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock()

# nicegui.ui needs to be accessible as `ui` when `from nicegui import ui` is used.
_nicegui_mod = sys.modules.setdefault("nicegui", MagicMock())
_nicegui_mod.ui = sys.modules["nicegui.ui"]  # type: ignore[attr-defined]

# Now import the actions module directly (bypassing the package __init__ which
# would pull in the full dialog that has heavier transitive deps).
_spec = importlib.util.spec_from_file_location(
    "papervisor.ui.dialogs.metadata.actions",
    Path(__file__).parent.parent / "papervisor" / "ui" / "dialogs" / "metadata" / "actions.py",
)
assert _spec is not None and _spec.loader is not None
actions_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(actions_module)  # type: ignore[union-attr]

MetadataActions = actions_module.MetadataActions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_actions(file_path: str) -> tuple[MetadataActions, list[tuple[str, str]]]:
    """Return a MetadataActions instance with a fake paper and a notifications log."""
    notifications: list[tuple[str, str]] = []
    paper = SimpleNamespace(file_path=file_path)
    state = SimpleNamespace(paper=paper)
    dialog = SimpleNamespace(state=state)
    obj = MetadataActions.__new__(MetadataActions)
    obj.dialog = dialog
    # Patch _notify to capture calls without touching the NiceGUI runtime.
    obj._notify = lambda msg, *, color="info": notifications.append((msg, color))  # type: ignore[method-assign]
    return obj, notifications


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_download_denied_when_resolve_raises_oserror(tmp_path, monkeypatch) -> None:
    """The fail-closed branch must deny access when p.resolve() raises OSError."""
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True)
    inside = library_root / "paper.pdf"
    inside.write_bytes(b"%PDF")

    monkeypatch.setattr(
        actions_module,
        "get_paths",
        lambda: SimpleNamespace(library_files_dir=library_root),
    )

    obj, notifications = _make_actions(str(inside))

    original_resolve = Path.resolve

    def _raise_oserror(self: Path, **kwargs: object) -> Path:  # type: ignore[override]
        if self == inside:
            raise OSError("synthetic OS error")
        return original_resolve(self, **kwargs)

    monkeypatch.setattr(Path, "resolve", _raise_oserror)

    download_calls: list[Path] = []
    monkeypatch.setattr(actions_module.ui, "download", lambda p, **kw: download_calls.append(p))

    obj.download_paper_file()

    assert download_calls == [], "download must not be triggered on resolve failure"
    assert notifications, "user must be notified on resolve failure"
    assert notifications[0][1] == "warning", "notification must use 'warning' color"


def test_download_uses_resolved_path(tmp_path, monkeypatch) -> None:
    """The download call must use the resolved path, not the unresolved one."""
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True)
    inside = library_root / "paper.pdf"
    inside.write_bytes(b"%PDF")

    monkeypatch.setattr(
        actions_module,
        "get_paths",
        lambda: SimpleNamespace(library_files_dir=library_root),
    )

    obj, notifications = _make_actions(str(inside))

    download_calls: list[Path] = []
    monkeypatch.setattr(actions_module.ui, "download", lambda p, **kw: download_calls.append(p))

    obj.download_paper_file()

    assert notifications == [], f"unexpected notifications: {notifications}"
    assert len(download_calls) == 1
    assert download_calls[0] == inside.resolve(), "download must receive the resolved path"


def test_download_denied_for_path_outside_library(tmp_path, monkeypatch) -> None:
    """Files outside the library root must never be downloaded."""
    library_root = tmp_path / "library"
    library_root.mkdir(parents=True)
    outside = tmp_path / "secret.txt"
    outside.write_bytes(b"secret")

    monkeypatch.setattr(
        actions_module,
        "get_paths",
        lambda: SimpleNamespace(library_files_dir=library_root),
    )

    obj, notifications = _make_actions(str(outside))

    download_calls: list[Path] = []
    monkeypatch.setattr(actions_module.ui, "download", lambda p, **kw: download_calls.append(p))

    obj.download_paper_file()

    assert download_calls == [], "download must not trigger for paths outside library root"
    assert any(n[1] == "warning" for n in notifications), "user must be warned"
