"""QWebChannel-exposed API (JS -> Python), run control + user memory.

All slots take a JSON string payload (or "{}") so the JS call shape is
uniform; they return JSON strings. Slots are split across mixin files to
respect the 150-line module budget.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Slot

from .api_composer import ComposerSlots, SettingsSlots
from .api_presets import PresetSlots, RuleSlots
from .util import jdump, jload


class RunSlots:
    """RUN / PAUSE / RESUME / STOP / test-connection."""

    @Slot(str, result=str)
    def runSequence(self, payload: str) -> str:
        p = jload(payload)
        self.sv.status_repo.requeue_due(self.sv.settings.cooldown_days)
        self.sv.worker.run_seq({"blocks": p.get("blocks", []),
                                "queued": self.sv.users.queued_nicks(),
                                "rules": [r.to_dict() for r in self.sv.filters.list()]})
        return jdump({"ok": True})

    @Slot(str, result=str)
    def pause(self, _p: str = "{}") -> str:
        self.sv.worker.pause()
        return jdump({"ok": True})

    @Slot(str, result=str)
    def resume(self, _p: str = "{}") -> str:
        self.sv.worker.resume()
        return jdump({"ok": True})

    @Slot(str, result=str)
    def stop(self, _p: str = "{}") -> str:
        self.sv.worker.stop()
        return jdump({"ok": True})

    @Slot(str, result=str)
    def testConnection(self, _p: str = "{}") -> str:
        self.sv.worker.test()
        return jdump({"ok": True, "note": "result arrives via test_result event"})


class UserSlots:
    """Tracker queries, per-user actions, CSV import/export."""

    @Slot(str, result=str)
    def getUsers(self, payload: str = "{}") -> str:
        f = jload(payload)
        rows = self.sv.users.list(status=f.get("status") or None,
                                  limit=int(f.get("limit", 500)),
                                  order=f.get("order", "recent"))
        return jdump({"rows": [u.to_dict() for u in rows],
                      "counts": self.sv.users.counts()})

    @Slot(str, result=str)
    def userAction(self, payload: str = "{}") -> str:
        f = jload(payload)
        action = f.get("action")
        if action == "reset":
            self.sv.users.set_status(f.get("id"), "NEW")
        elif action == "skip":
            self.sv.users.set_status(f.get("id"), "SKIPPED", f.get("reason"))
        elif action == "note":
            self.sv.users.set_notes(f.get("id"), f.get("notes", ""))
        elif action == "delete":
            self.sv.users.delete(f.get("id"))
        return jdump({"ok": True})

    @Slot(str, result=str)
    def resetUsers(self, _p: str = "{}") -> str:
        return jdump({"ok": True, "reset": self.sv.users.reset_all()})

    @Slot(str, result=str)
    def exportCsv(self, _p: str = "{}") -> str:
        from ..memory.csv_io import export_users
        path = self.sv.window.file_dialog_save("Export users CSV", "*.csv") \
            if self.sv.window else ""
        if not path:
            return jdump({"ok": False, "error": "cancelled"})
        return jdump({"ok": True, "path": path,
                      "count": export_users(self.sv.users, path)})

    @Slot(str, result=str)
    def importCsv(self, _p: str = "{}") -> str:
        from ..memory.csv_io import import_users
        path = self.sv.window.file_dialog_open("Import users CSV", "*.csv") \
            if self.sv.window else ""
        if not path:
            return jdump({"ok": False, "error": "cancelled"})
        return jdump({"ok": True, **import_users(self.sv.status_repo, path)})


class ChatFlowApi(RunSlots, UserSlots, PresetSlots, RuleSlots,
                  ComposerSlots, SettingsSlots, QObject):
    """Aggregates all slot mixins; registered on the QWebChannel as 'chatflow'."""

    def __init__(self, services):
        super().__init__()
        self.sv = services
