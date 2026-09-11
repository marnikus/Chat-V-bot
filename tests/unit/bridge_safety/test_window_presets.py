"""QWebChannel window-preset CRUD and live-list contract."""

from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

import bridge.window_preset_bridge as preset_bridge
from bridge.context import BridgeContext
from bridge.window_preset_bridge import WindowPresetBridge
from backend.config_manager import ConfigManager
from services.layout_service import LayoutService
from services.window_preset_service import APP_VERSION, FORMAT, SCHEMA_VERSION


def document(name="Desk"):
    windows = [
        {"id": wid, "title": wid, "state": "open",
         "bounds": {"x": 0, "y": 0, "width": 0.5, "height": 0.5}}
        for wid in LayoutService.WINDOW_IDS
    ]
    return {
        "format": FORMAT, "schema_version": SCHEMA_VERSION,
        "app_version": APP_VERSION, "name": name,
        "created_at": "2026-09-10T12:00:00",
        "updated_at": "2026-09-10T12:00:00",
        "grid": {"type": "sash-tree", "version": LayoutService.GRID_VERSION,
                 "window_count": len(LayoutService.WINDOW_IDS),
                 "sizes_unit": "percent",
                 "tree": LayoutService.default_grid_tree()},
        "windows": windows,
        "window_states": {"closed": [], "minimized": []},
        "screen": {"width": 1400, "height": 900,
                   "device_pixel_ratio": 1},
    }


def make_bridge(tmp_path):
    config = ConfigManager(str(tmp_path / "config.json"))
    return WindowPresetBridge(BridgeContext(config=config)), config


def test_save_list_load_delete_and_signal(tmp_path):
    bridge, config = make_bridge(tmp_path)
    updates = []
    bridge.window_preset_list_updated.connect(updates.append)

    assert bridge.save_window_preset("Desk", json.dumps(document()))
    assert json.loads(bridge.list_window_presets())[0]["name"] == "Desk"
    assert updates
    stored = json.loads(bridge.load_window_preset("Desk"))
    assert stored["grid"]["tree"] == LayoutService.default_grid_tree()
    assert config.window_presets.load_preset("Desk")["name"] == "Desk"

    assert bridge.delete_window_preset("Desk")
    assert bridge.list_window_presets() == "[]"


def test_invalid_save_and_missing_operations_do_not_change_store(tmp_path):
    bridge, _config = make_bridge(tmp_path)
    assert not bridge.save_window_preset("Bad", "{oops")
    assert bridge.list_window_presets() == "[]"
    assert bridge.load_window_preset("ghost") == "null"
    assert not bridge.delete_window_preset("ghost")


def test_missing_config_degrades_to_empty_without_false_success():
    bridge = WindowPresetBridge(BridgeContext())
    assert bridge.list_window_presets() == "[]"
    assert bridge.load_window_preset("ghost") == "null"
    assert not bridge.save_window_preset("Desk", json.dumps(document()))
    assert not bridge.delete_window_preset("ghost")


def test_export_selects_folder_writes_portable_file_and_reveals_it(tmp_path, monkeypatch):
    bridge, config = make_bridge(tmp_path)
    assert bridge.save_window_preset("Desk", json.dumps(document()))
    export_folder = tmp_path / "exports"
    export_folder.mkdir()
    dialog = types.SimpleNamespace(
        getExistingDirectory=lambda *args: str(export_folder))
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets",
                        types.SimpleNamespace(QFileDialog=dialog))
    assert preset_bridge._choose_export_folder() == str(export_folder)
    assert preset_bridge._safe_filename("Desk / blue") == "window-preset-Desk-blue.json"
    real_open = preset_bridge._open_in_folder
    monkeypatch.setattr(preset_bridge, "_choose_export_folder",
                        lambda: str(export_folder))

    result = json.loads(bridge.export_window_preset("Desk"))
    exported = export_folder / "window-preset-Desk.json"
    assert result == {"ok": True, "name": "Desk", "path": str(exported)}
    assert json.loads(exported.read_text(encoding="utf-8"))["name"] == "Desk"

    opened = []
    monkeypatch.setattr(preset_bridge, "_open_in_folder",
                        lambda path: opened.append(path) or True)
    assert bridge.show_window_preset_in_folder("Desk")
    assert opened == [str(exported)]
    services = types.SimpleNamespace(
        QDesktopServices=types.SimpleNamespace(
            openUrl=lambda url: opened.append(url) or True))
    monkeypatch.setitem(sys.modules, "PySide6.QtGui", services)
    assert real_open(str(exported))

    bad_folder = tmp_path / "not-a-folder"
    bad_folder.write_text("not a folder", encoding="utf-8")
    monkeypatch.setattr(preset_bridge, "_choose_export_folder",
                        lambda: str(bad_folder))
    failed = json.loads(bridge.export_window_preset("Desk"))
    assert not failed["ok"]

    cancelled = WindowPresetBridge(BridgeContext(config=config))
    monkeypatch.setattr(preset_bridge, "_choose_export_folder", lambda: "")
    result = json.loads(cancelled.export_window_preset("Desk"))
    assert result == {"ok": False, "cancelled": True}

    fallback = WindowPresetBridge(BridgeContext(config=config))
    assert fallback.show_window_preset_in_folder("Desk")
    assert opened[-1] == config.window_presets.path

    monkeypatch.setattr(preset_bridge, "_open_in_folder", lambda _path: False)
    assert not fallback.show_window_preset_in_folder("Desk")

    def raise_open(_path):
        raise RuntimeError("explorer unavailable")

    monkeypatch.setattr(preset_bridge, "_open_in_folder", raise_open)
    assert not fallback.show_window_preset_in_folder("Desk")
    empty = WindowPresetBridge(BridgeContext())
    assert not empty.show_window_preset_in_folder("Desk")
    assert not json.loads(empty.export_window_preset("Desk"))["ok"]


class _FakeStore:
    def __init__(self, value=None, *, save_result=True):
        self.value = value
        self.save_result = save_result
        self.loaded = False
        self.raise_on = set()

    def list_presets(self):
        if "list" in self.raise_on:
            raise RuntimeError("list failed")
        return []

    def save_preset(self, _name, value):
        if "save_preset" in self.raise_on:
            raise RuntimeError("save failed")
        self.value = value

    def load_preset(self, _name):
        if "load" in self.raise_on:
            raise RuntimeError("load failed")
        return self.value

    def delete_preset(self, _name):
        if "delete" in self.raise_on:
            raise RuntimeError("delete failed")
        if self.value is None:
            return False
        self.value = None
        return True

    def save(self, force=False):
        return self.save_result

    def load(self):
        self.loaded = True


def _bridge_for_store(store):
    config = SimpleNamespace(window_presets=store)
    return WindowPresetBridge(BridgeContext(config=config))


def test_bridge_handles_store_exceptions_and_failed_flushes():
    store = _FakeStore()
    store.raise_on.add("list")
    assert _bridge_for_store(store).list_window_presets() == "[]"

    store = _FakeStore(save_result=False)
    bridge = _bridge_for_store(store)
    assert not bridge.save_window_preset("Desk", json.dumps(document()))
    assert store.loaded

    store = _FakeStore()
    store.raise_on.add("save_preset")
    assert not _bridge_for_store(store).save_window_preset(
        "Desk", json.dumps(document()))

    store = _FakeStore()
    store.raise_on.add("load")
    assert _bridge_for_store(store).load_window_preset("Desk") == "null"

    store = _FakeStore({"name": "not a valid preset"})
    assert _bridge_for_store(store).load_window_preset("Desk") == "null"

    store = _FakeStore(document(), save_result=False)
    bridge = _bridge_for_store(store)
    assert not bridge.delete_window_preset("Desk")
    assert store.loaded

    store = _FakeStore(document())
    store.raise_on.add("delete")
    assert not _bridge_for_store(store).delete_window_preset("Desk")
