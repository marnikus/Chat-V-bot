"""QWebChannel window-preset CRUD and live-list contract."""

from __future__ import annotations

import json

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
