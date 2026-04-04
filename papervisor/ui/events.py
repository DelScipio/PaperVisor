"""Lightweight in-process event bus for cross-component communication.

Instead of passing ``on_changed`` callbacks deep into every dialog, the
event bus lets any component *emit* a named event and any interested
component *subscribe* to it.  This decouples dialogs from the specific
refresh functions they need to trigger.

Usage
-----

Emitting (inside a dialog after a mutation)::

    from papervisor.ui.events import emit, Event

    emit(Event.PAPER_UPDATED)
    emit(Event.LIBRARY_CREATED, library_id='abc')

Subscribing (inside the page that owns the ``@ui.refreshable`` targets)::

    from papervisor.ui.events import on, Event

    on(Event.PAPER_UPDATED, lambda **kw: render_content.refresh())
    on(Event.LIBRARY_CREATED, lambda **kw: _refresh_all())

The bus is **per-client** — each NiceGUI user session gets its own
isolated subscriber list.  No cross-user leakage.

Thread-safety: NiceGUI is single-threaded per client connection (asyncio
event loop), so no locking is required.
"""

from __future__ import annotations

import logging
from enum import Enum, unique
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Event names
# ------------------------------------------------------------------

@unique
class Event(str, Enum):
    """Domain events that components can publish / subscribe to."""

    # Paper mutations
    PAPER_CREATED = 'paper_created'
    PAPER_UPDATED = 'paper_updated'
    PAPER_DELETED = 'paper_deleted'
    PAPER_RESTORED = 'paper_restored'
    PAPER_IMPORTED = 'paper_imported'
    PAPER_MOVED = 'paper_moved'

    # Reading state
    READING_STATE_CHANGED = 'reading_state_changed'
    FAVORITE_TOGGLED = 'favorite_toggled'
    TO_READ_TOGGLED = 'to_read_toggled'
    COMPLETED_TOGGLED = 'completed_toggled'

    # Library mutations
    LIBRARY_CREATED = 'library_created'
    LIBRARY_UPDATED = 'library_updated'
    LIBRARY_DELETED = 'library_deleted'

    # Marker mutations
    MARKER_CREATED = 'marker_created'
    MARKER_UPDATED = 'marker_updated'
    MARKER_DELETED = 'marker_deleted'

    # Sharing
    SHARE_CREATED = 'share_created'
    SHARE_REMOVED = 'share_removed'

    # Tags
    TAG_CHANGED = 'tag_changed'

    # User / settings
    SETTINGS_CHANGED = 'settings_changed'


# ------------------------------------------------------------------
# Subscriber type
# ------------------------------------------------------------------

Subscriber = Callable[..., Any]


# ------------------------------------------------------------------
# Bus (per-client via module-level dict keyed by NiceGUI client id)
# ------------------------------------------------------------------

# Map: client_id -> { event_name -> [callbacks] }
_subscriptions: dict[str, dict[str, list[Subscriber]]] = {}


def _client_id() -> str:
    """Return the current NiceGUI client id, or a fallback for non-UI contexts."""
    try:
        from nicegui import context
        return str(context.client.id)
    except Exception:
        return '__global__'


def on(event: Event | str, callback: Subscriber) -> None:
    """Register *callback* to be called whenever *event* is emitted.

    The callback receives any keyword arguments passed to ``emit()``.
    """
    cid = _client_id()
    event_name = str(event.value if isinstance(event, Event) else event)
    _subscriptions.setdefault(cid, {}).setdefault(event_name, []).append(callback)


def off(event: Event | str, callback: Subscriber) -> None:
    """Unregister a previously registered callback."""
    cid = _client_id()
    event_name = str(event.value if isinstance(event, Event) else event)
    try:
        _subscriptions.get(cid, {}).get(event_name, []).remove(callback)
    except ValueError:
        pass


def emit(event: Event | str, **kwargs: Any) -> None:
    """Fire *event*, calling all registered subscribers with *kwargs*."""
    cid = _client_id()
    event_name = str(event.value if isinstance(event, Event) else event)
    callbacks = list(_subscriptions.get(cid, {}).get(event_name, []))
    for cb in callbacks:
        try:
            cb(**kwargs)
        except Exception:
            logger.warning('Event handler error for %s', event_name, exc_info=True)


def clear(client_id: str | None = None) -> None:
    """Remove all subscriptions for a client (cleanup on disconnect)."""
    cid = client_id or _client_id()
    _subscriptions.pop(cid, None)
