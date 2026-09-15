"""The Qt main window: the WebEngine view, the bridge channel, and closing.

Owns three things and nothing else — building the `QWebEngineView` that hosts
`ui/index.html`, wiring the `QWebChannel` the JavaScript bridge talks over,
and the staged close that must not lose a pending grid layout.

The close protocol is the subtle part, so it is stated once here:

1. The first `closeEvent` **ignores** the event, saves the window geometry and
   asks the page to flush `SashGrid` / `StackDnD` persistence. The window
   stays up on purpose: closing now would drop an unsaved layout.
2. The flush answers one of three ways — the page returns `true` (an ack is
   coming as `grid_layout_persisted`), it returns anything else (no ack will
   ever come), or the 1 s timer expires. Only the first waits; the other two
   finish the close immediately, and a rejected save is logged, not retried
   (RULE 4 — a broken save is reported, never presented as a clean close).
3. `_finish_close` re-enters `closeEvent` with `_close_finished` set, which is
   accepted. The shutdown watchdog then arms: if the process has not exited
   after 3 s, `_force_quit` calls `os._exit(0)`, because a WebEngine render
   process can outlive the Qt loop and hold the exit open.

Import direction: Qt and the standard library only — this module must not
import `services` or `bridge`; `app/bootstrap.py` wires those in.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow

log = logging.getLogger("chatbot")
UI_PATH = Path(__file__).resolve().parent.parent / "ui" / "index.html"

#: Asks the page to flush both persistence owners. Returns true only when
#: SashGrid took the flush, which is the one case that produces a later
#: `grid_layout_persisted` ack; every other outcome must finish the close here.
#: Both calls are wrapped so a missing or throwing object cannot block closing.
_FLUSH_SCRIPT = """(function(){try{if(window.StackDnD&&typeof window.StackDnD.flushPersistence==='function')window.StackDnD.flushPersistence();}catch(e){}try{if(window.SashGrid&&typeof window.SashGrid.flushPersistence==='function')return !!window.SashGrid.flushPersistence();}catch(e){}return false;})();"""

#: How long the close waits for the page to answer before closing anyway.
_FLUSH_TIMEOUT_MS = 1000
#: How long the process gets to exit on its own before the watchdog forces it.
_SHUTDOWN_GRACE_MS = 3000


class MainWindow(QMainWindow):
    closing = Signal()

    def __init__(self, config=None):
        super().__init__()
        self._config = config
        self._bridge = None
        self._close_requested = self._close_finished = False
        self._layout_flush_pending = False
        self.setWindowTitle("🤖 ChatBot Automator")
        self.resize(1400, 900)
        self._view = QWebEngineView(self)
        self.setCentralWidget(self._view)
        self._restore_window_geometry()
        self._watchdog = self._single_shot_timer(_SHUTDOWN_GRACE_MS,
                                                 self._force_quit)
        self._layout_flush_timer = self._single_shot_timer(
            _FLUSH_TIMEOUT_MS, self._on_layout_flush_timeout)

    def _single_shot_timer(self, interval_ms: int, on_timeout) -> QTimer:
        """One shared shape for the two timers this window arms."""
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(on_timeout)
        return timer

    def set_bridge(self, bridge) -> None:
        self._bridge = bridge
        signal = getattr(bridge, "grid_layout_persisted", None)
        if signal is not None:
            signal.connect(self._on_grid_layout_persisted)

    def _restore_window_geometry(self) -> None:
        if not self._config:
            return
        saved = self._config.get_state("window_geometry", None)
        if not isinstance(saved, dict):
            return
        try:
            x, y = int(saved["x"]), int(saved["y"])
            w, h = int(saved["width"]), int(saved["height"])
        except (KeyError, TypeError, ValueError):
            return
        if w > 0 and h > 0:
            self.setGeometry(x, y, w, h)

    def _save_window_geometry(self) -> None:
        if not self._config:
            return
        g = self.geometry()
        self._config.set_state(window_geometry={"x": int(g.x()), "y": int(g.y()),
                                                "width": int(g.width()),
                                                "height": int(g.height())})

    def _request_grid_flush(self) -> None:
        if not self._bridge or not self._view or not self._view.page():
            self._finish_close(); return
        self._layout_flush_pending = True
        self._layout_flush_timer.start()
        try:
            self._view.page().runJavaScript(_FLUSH_SCRIPT,
                                            self._on_grid_flush_dispatched)
        except Exception as exc:
            log.warning("Grid close flush could not be dispatched: %s", exc)
            self._finish_close()

    def _flush_needs_finish(self, expects_ack) -> bool:
        """True when no ack is coming, so this call must finish the close.

        `expects_ack` is the page's return value: exactly `True` means
        SashGrid took the flush and will emit `grid_layout_persisted`, so the
        close waits for that. Anything else — no SashGrid, a throw, a `false`
        return — means nothing will ever arrive.
        """
        return (not self._close_finished and self._layout_flush_pending
                and expects_ack is not True)

    def _on_grid_flush_dispatched(self, expects_ack) -> None:
        if self._flush_needs_finish(expects_ack):
            self._finish_close()

    def _on_grid_layout_persisted(self, success) -> None:
        if not self._layout_flush_pending:
            return
        if not success:
            log.warning("Final grid layout was rejected while closing")
        self._finish_close()

    def _on_layout_flush_timeout(self) -> None:
        if self._layout_flush_pending:
            log.warning("Timed out waiting for final grid layout save; closing safely")
            self._finish_close()

    def _finish_close(self) -> None:
        """Idempotent: only the first call closes, the rest are no-ops."""
        if self._close_finished:
            return
        self._layout_flush_pending = False
        self._layout_flush_timer.stop()
        self._close_finished = True
        self.close()

    def closeEvent(self, event):
        """The staged close described in the module docstring.

        The event is *ignored* on the first request so the flush can finish;
        `_finish_close` re-enters here and that second pass is accepted.
        """
        if self._close_finished:
            self._accept_final_close(event)
            return
        if self._close_requested:
            event.ignore()
            return
        self._close_requested = True
        self._save_window_geometry()
        event.ignore()
        self._request_grid_flush()

    def _accept_final_close(self, event) -> None:
        """Accept the re-entrant close and arm the shutdown watchdog."""
        event.accept()
        log.info("Main window closed — shutting down")
        self.closing.emit()
        self._watchdog.start()

    def _force_quit(self) -> None:
        log.warning("Shutdown watchdog fired — forcing process exit")
        os._exit(0)


def create_window(config, bridge, ui_path: str | os.PathLike | None = None) -> MainWindow:
    window = MainWindow(config=config)
    window.set_bridge(bridge)
    channel = QWebChannel(window)
    channel.registerObject("bridge", bridge)
    window._channel = channel
    window._view.page().setWebChannel(channel)
    path = Path(ui_path or UI_PATH).resolve()
    window._view.load(QUrl.fromLocalFile(str(path)))
    window.show()
    return window
