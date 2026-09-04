"""Bridge slots: message composer, settings, schemas, log saving."""
from __future__ import annotations

from PySide6.QtCore import Slot

from .util import jdump, jload


def _image_count(settings) -> int:
    from ..blocks.attach_image import list_images
    return len(list_images(settings.image_folder))


class ComposerSlots:
    @Slot(str, result=str)
    def getComposer(self, _p: str = "{}") -> str:
        s = self.sv.settings
        return jdump({"message": s.message, "pool": s.message_pool,
                      "image_folder": s.image_folder,
                      "attach_image": s.attach_image,
                      "image_count": _image_count(s)})

    @Slot(str, result=str)
    def saveComposer(self, payload: str = "{}") -> str:
        f = jload(payload)
        s = self.sv.settings
        if "message" in f:
            s.message = str(f["message"])[: s.msg_max_len]
        if "pool" in f:
            s.message_pool = str(f["pool"])
        if "attach_image" in f:
            s.attach_image = bool(f["attach_image"])
        s.save(self.sv.settings_path)
        return jdump({"ok": True, "image_count": _image_count(s)})

    @Slot(str, result=str)
    def browseImageFolder(self, _p: str = "{}") -> str:
        if not self.sv.window:
            return jdump({"ok": False, "error": "no window"})
        folder = self.sv.window.folder_dialog("Choose image folder")
        if not folder:
            return jdump({"ok": False, "error": "cancelled"})
        self.sv.settings.image_folder = folder
        self.sv.settings.save(self.sv.settings_path)
        return jdump({"ok": True, "path": folder,
                      "count": _image_count(self.sv.settings)})


class SettingsSlots:
    @Slot(str, result=str)
    def getSettings(self, _p: str = "{}") -> str:
        return jdump(self.sv.settings.to_dict())

    @Slot(str, result=str)
    def saveSettings(self, payload: str = "{}") -> str:
        from ..core.config import Settings
        merged = Settings.from_dict({**self.sv.settings.to_dict(),
                                     **jload(payload)})
        self.sv.settings = merged
        merged.save(self.sv.settings_path)
        self.sv.worker.s = merged
        return jdump({"ok": True})

    @Slot(str, result=str)
    def getBlockSchemas(self, _p: str = "{}") -> str:
        from ..blocks import registry
        return jdump(registry.schemas())

    @Slot(str, result=str)
    def saveLog(self, payload: str = "{}") -> str:
        text = jload(payload).get("text", "")
        if not self.sv.window:
            return jdump({"ok": False, "error": "no window"})
        path = self.sv.window.file_dialog_save("Save log", "*.txt")
        if not path:
            return jdump({"ok": False, "error": "cancelled"})
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return jdump({"ok": True, "path": path})
