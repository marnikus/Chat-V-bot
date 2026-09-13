"""`HistoryBridge` — the facade over the archive window's seven surfaces.

The class owns the Qt signals and the construction (the context and the one
bus subscription); the behaviour lives one responsibility per mixin:

    runner       guarded async answering (_run_async / _schedule / _json_arg)
    reads        person history, search, stats, my-nick detection
    userdb       the Full User Database page and its counters
    deletion     the three reversible removals (RULE 12)
    person_ops   purge / restore / merge and the People-list helpers
    media        cached media, the cache folder and the clipboard
    settings     the archive settings, with and without a running archive

The mixins are PLAIN classes, not QObject subclasses, and that is load
bearing: `bridge/router.py` builds the QWebChannel class from each bridge's
metaobject starting at `methodOffset()`, so a signal or slot inherited from a
QObject *base* would sit below the offset and silently vanish from the wire
API. Mixins that only inherit `object` are scanned into this class's own
metaobject section, so the published surface is unchanged (the step-4
`Collector(QObject, LifecycleMixin, …)` precedent).

Layout: the mixins own no state and never import this module, so the facade is
the only module that imports them (`backend/history_query/` precedent).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.events import UserDbChanged

from .deletion import DeletionMixin
from .media import MediaMixin
from .person_ops import PersonOpsMixin
from .reads import ReadsMixin
from .runner import RunnerMixin
from .settings import SettingsMixin
from .userdb import UserDbMixin


class HistoryBridge(QObject, RunnerMixin, ReadsMixin, UserDbMixin,
                    DeletionMixin, PersonOpsMixin, MediaMixin,
                    SettingsMixin):
    """The message archive: reads, deletions, media, clipboard.

    Reads hit an async SQLite database, so a @Slot cannot answer inline: JS
    passes a `req_id` and Python answers on a signal carrying the same id
    (two windows can ask for two pages at once without answers crossing).
    The archive service (`services/history/`) owns the database.
    """

    history_page_ready = Signal(str, str)    # req_id, JSON page
    history_search_ready = Signal(str, str)  # req_id, JSON results
    history_stats_ready = Signal(str, str)   # req_id, JSON stats
    userdb_page_ready = Signal(str, str)     # req_id, JSON persons / stats
    userdb_changed = Signal(str)             # JSON {action, nick}
    media_ready = Signal(str, str)           # req_id, JSON media info
    history_error = Signal(str, str)         # scope, message

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.bus.subscribe(UserDbChanged,
                          lambda e: self.userdb_changed.emit(e.payload))
