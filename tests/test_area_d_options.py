"""Unit coverage for Area D's typed option boundaries."""
import asyncio
import json
from types import SimpleNamespace

from backend.chat_parser import SyncOptions
from backend.config_manager import ConfigManager
from backend.scroll_parser import ScrollOptions, ScrollParser


def test_sync_options_normalize_and_override():
    opts = SyncOptions.from_legacy(
        max_messages="12", chunk_pause_ms="-3", backfill_wait_s="bad",
        backfill_older=1)
    assert opts.max_messages == 12
    assert opts.chunk_pause_ms == 0
    assert opts.backfill_wait_s == 2.0
    assert opts.backfill_older is True


def test_scroll_options_clamp_values():
    opts = ScrollOptions.from_legacy(scroll_dy="-4", pause_ms="bad",
                                     max_scrolls="8", highlight_ms="-2")
    assert opts.scroll_dy == 0
    assert opts.pause_ms == 800
    assert opts.max_scrolls == 8
    assert opts.highlight_ms == 0


def test_scroll_parser_accepts_options_object():
    cdp = SimpleNamespace()
    opts = ScrollOptions(max_scrolls=3, scroll_dy=11)
    parser = ScrollParser(cdp, options=opts)
    assert parser.max_scrolls == 3
    assert parser._scroll_dy == 11


def test_config_scalar_sections_are_safe(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"state": "legacy", "chrome": "legacy"}))
    cfg = ConfigManager(str(path))
    assert cfg.get_state("nick", "fallback") == "fallback"
    assert cfg.named_all("chrome") == {}
    assert cfg.get("chrome", "port", default=9222) == 9222


def test_config_set_replaces_scalar_parent(tmp_path):
    cfg = ConfigManager(str(tmp_path / "config.json"))
    cfg.set("state", "legacy")
    cfg.set("state", "nick", "Me")
    assert cfg.get("state", "nick") == "Me"
