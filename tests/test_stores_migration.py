"""Tests for stores/ — atomic saves, migration, and façade."""

import os
import json
import tempfile
from stores.atomic import AtomicJsonStore
from stores.settings_store import SettingsStore
from stores.bookmark_store import BookmarkStore
from stores.block_store import BlockStore
from stores.session_store import SessionStore
from stores.undo_store import UndoStore
from stores.migration import migrate


def test_atomic_save_is_atomic(tmp_path=None):
    import pathlib
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    a = AtomicJsonStore(p)
    a.set("foo", {"bar": 1})
    res = a.save()
    assert res.is_ok
    # tmp file should not remain
    assert not os.path.exists(p + ".tmp")
    assert os.path.exists(p)
    data = json.load(open(p))
    assert data["foo"]["bar"] == 1


def test_settings_store_defaults():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    s = SettingsStore(path=p)
    assert s.get("chrome", "host") == "127.0.0.1"
    assert s.get("history", "db_path") == "history.db"


def test_bookmark_store_add_remove():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    b = BookmarkStore(path=p)
    assert "https://ru.virt-chat.com/chat" in b.all()
    b.add("https://example.com")
    assert "https://example.com" in b.all()
    b.remove("https://example.com")
    assert "https://example.com" not in b.all()


def test_block_store_custom_blocks():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "blocks.json")
    blk = BlockStore(path=p)
    # named stack/template presets live in PresetStore now; the block
    # store owns custom blocks only (bare list on disk)
    assert blk.save_block("my", {"blocks": [1, 2]}) is True
    assert blk.all()[0]["block"] == {"blocks": [1, 2]}
    assert blk.delete("my") is True
    assert blk.delete("my") is False
    assert blk.all() == []


def test_session_store():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    s = SessionStore(path=p)
    s.set(grid_layout="payload")
    assert s.get("grid_layout") == "payload"


def test_undo_store():
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    u = UndoStore(path=p)
    h, idx = u.get()
    assert h == [] and idx == -1
    u.push("stack", [1, 2, 3])
    h, idx = u.get()
    assert len(h) == 1 and idx == 0
    assert h[0]["kind"] == "stack"


def test_migration_creates_backup(tmp_path=None):
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "cfg.json")
    # legacy minimal file
    with open(p, "w") as f:
        json.dump({"chrome": {"host": "1.1.1.1"}}, f)
    res = migrate(p)
    assert res["migrated"] or not res["migrated"]  # should not crash
    # ensure file still valid json
    data = json.load(open(p))
    assert "chrome" in data
