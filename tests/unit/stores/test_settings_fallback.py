"""Pin missing-vs-explicit overlay semantics before simplifying the lookup."""

import pytest

from stores.settings_store import SETTINGS_DEFAULTS, SettingsStore


@pytest.fixture
def store(tmp_path):
    return SettingsStore(str(tmp_path / "settings.json"))


def test_missing_sibling_restarts_the_full_defaults_path(store):
    store.set("history", "media", "download", False)
    assert store.get("history", "media", "max_file_mb") == 25
    assert store.get("history", "media", "download") is False
    assert store.data() == {"history": {"media": {"download": False}}}


@pytest.mark.parametrize("value", [None, False, 0, "", [], "disabled"])
def test_explicit_scalar_blocks_default_tree_traversal(store, value):
    marker = object()
    store.set("history", "media", value)
    assert store.get("history", "media") is value
    assert store.get("history", "media", "max_file_mb", default=marker) is marker


@pytest.mark.parametrize("keys", [
    ("unknown",), ("history", "unknown"),
    ("history", "media", "max_file_mb", "child"),
])
def test_missing_or_scalar_defaults_path_returns_caller_default(store, keys):
    marker = object()
    assert store.get(*keys, default=marker) is marker


def test_defaults_identity_short_circuit_is_preserved(store):
    section = SETTINGS_DEFAULTS["history"]
    assert store.get("history", "media", default=section) is section


def test_no_keys_returns_overlay_and_reads_do_not_persist_defaults(store):
    store.set("ui", "theme", "light")
    overlay = store.get()
    assert store.get() is overlay
    assert overlay == {"ui": {"theme": "light"}}
    assert store.get("chrome", "port") == 9222
    store.save()
    reloaded = SettingsStore(store.path)
    assert reloaded.data() == {"ui": {"theme": "light"}}
