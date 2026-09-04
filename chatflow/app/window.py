"""Main window: Qt shell, menu, tray icon, status bar, file dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QFileDialog, QLabel, QMenu, QMainWindow,
                               QSystemTrayIcon, QStatusBar)


class MainWindow(QMainWindow):
    def __init__(self, webview, services):
        super().__init__()
        self.sv = services
        self.setWindowTitle("ChatFlow Orchestrator")
        self.resize(1440, 900)
        self.setCentralWidget(webview)
        services.window = self
        self._build_statusbar()
        self._build_menu()
        self._build_tray()

    # --- status bar -----------------------------------------------------------
    def _build_statusbar(self) -> None:
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self.lbl_conn = QLabel("Chrome: —")
        self.lbl_users = QLabel("")
        bar.addWidget(self.lbl_conn)
        bar.addPermanentWidget(self.lbl_users)

    def set_status(self, text: str) -> None:
        self.lbl_conn.setText(text)
        self.tray.setToolTip(f"ChatFlow Orchestrator — {text}")

    def set_counts(self, counts: dict) -> None:
        self.lbl_users.setText(
            f"Users: {counts.get('total', 0)} • new {counts.get('new', 0)} • "
            f"queued {counts.get('queued', 0)} • messaged {counts.get('messaged', 0)}")

    # --- menus -----------------------------------------------------------------
    def _make_icon(self):
        """Brand icon drawn at runtime (no image asset needed)."""
        from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#007acc"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(2, 2, 60, 60, 12, 12)
        p.setPen(QColor("#ececec"))
        p.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "CF")
        p.end()
        return QIcon(pm)

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("File")
        file_menu.addAction(self._action("Export CSV…", lambda: self.sv.api.exportCsv("{}")))
        file_menu.addAction(self._action("Import CSV…", lambda: self.sv.api.importCsv("{}")))
        file_menu.addSeparator()
        file_menu.addAction(self._action("Quit", self.close))
        tools_menu = bar.addMenu("Tools")
        tools_menu.addAction(self._action("Test Connection",
                                          lambda: self.sv.api.testConnection("{}")))
        tools_menu.addAction(self._action("Settings…",
                                          lambda: self._ui("openSettings")))
        tools_menu.addAction(self._action("Save Preset…",
                                          lambda: self._ui("openSavePreset")))

    def _action(self, label: str, slot) -> QAction:
        a = QAction(label, self)
        a.triggered.connect(slot)
        return a

    def _ui(self, fn: str) -> None:
        self.centralWidget().call_js("uiCommand", fn)

    # --- tray --------------------------------------------------------------------
    def _build_tray(self) -> None:
        icon = self._make_icon()
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(icon)
        self.tray.setToolTip("ChatFlow Orchestrator")
        menu = QMenu(self)
        menu.addAction("Stop", lambda: self.sv.api.stop("{}"))
        menu.addAction("Show", self.showNormal)
        menu.addAction("Quit", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.showNormal()
            if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    # --- file dialogs (used by bridge slots) ---------------------------------------
    def file_dialog_save(self, title: str, filter_: str) -> str:
        return QFileDialog.getSaveFileName(self, title, "", filter_)[0]

    def file_dialog_open(self, title: str, filter_: str) -> str:
        return QFileDialog.getOpenFileName(self, title, "", filter_)[0]

    def folder_dialog(self, title: str) -> str:
        return QFileDialog.getExistingDirectory(self, title)

    # --- lifecycle ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.sv.worker.shutdown()
            self.sv.worker.wait(3000)
            self.sv.db.close()
        except Exception:  # noqa: BLE001
            pass
        event.accept()
