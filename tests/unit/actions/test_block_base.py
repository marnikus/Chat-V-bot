"""AB# — the shared block skeleton in `actions/base.py`.

Four blocks (Return to Main, Click Main Tab, Find & Click, Click Send) do the
same job: hold a few settings, hand them to `visual_click.find_and_click`, and
describe themselves to the config panel. Their settings are declared once as
`BlockField`s, and `FindClickBlock` derives the constructor's cleaning, the
`config_schema()` entries and the runner's keyword arguments from that one
tuple. `MarkerBlock` is the same idea for blocks the engine drives itself.

Everything here is about the contract the preset files and the UI rely on:
`to_dict()` must keep emitting the same keys in the same order, `config_schema()`
must keep its keys and their order, and the constructor signatures must not
change (Area B/C builds blocks from saved dicts by keyword).
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

from actions.base import (BlockField, FindClickBlock, MarkerBlock,  # noqa: F401
                          _UNSET)
from actions.base_action import ActionResult, BaseAction
from actions.click_back import ClickBack
from actions.click_main_tab import ClickMainTab
from actions.click_send import ClickSend
from actions.custom_find import CustomFind
from actions.find_click_runner import find_and_click


class Recorder:
    """Collects `find_and_click`'s keyword arguments instead of touching CDP."""

    def __init__(self):
        self.calls = []
        self.result = ActionResult.OK

    async def __call__(self, cdp, **kwargs):
        self.calls.append(kwargs)
        return self.result

    @property
    def kwargs(self):
        return self.calls[0]


def patch_runner(monkeypatch, recorder):
    # wherever the name lives today or after the refactor: the block's module
    # or the shared base — patch every place it can be looked up from.
    for module in ("actions.base", "actions.click_back", "actions.click_main_tab",
                   "actions.click_send", "actions.custom_find",
                   "actions.find_click_runner", "backend.visual_click"):
        monkeypatch.setattr(__import__(module, fromlist=["*"]),
                            "find_and_click", recorder, raising=False)


# ── BlockField itself ────────────────────────────────────────────────
def test_block_field_schema_entry_only_holds_what_is_set():
    """Empty option/help keys would change what the UI panel receives."""
    plain = BlockField("tab_name", "text", "Tab name", default="x")
    assert plain.to_schema() == {"type": "text", "default": "x",
                                 "label": "Tab name"}
    rich = BlockField("mode", "select", "Mode", default="a",
                      options=("a", "b"), help="pick one")
    assert rich.to_schema() == {"type": "select", "default": "a",
                                "label": "Mode",
                                "options": ["a", "b"], "help": "pick one"}


def test_block_field_clean_is_applied_and_can_be_a_plain_builtin():
    assert BlockField("n", "number", "N", default=0,
                      clean=lambda v: max(0, int(v))).coerce("-3") == 0
    assert BlockField("b", "checkbox", "B", default=True,
                      clean=bool).coerce(0) is False


# ── how the four clicking blocks are built from their fields ──────────
@pytest.mark.parametrize("cls", [ClickBack, ClickMainTab, ClickSend, CustomFind])
def test_every_declared_field_becomes_a_plain_attribute(cls):
    """RULE 3: settings are ordinary attributes, not a config dict."""
    block = cls()
    for field in cls.FIELDS:
        assert hasattr(block, field.name), field.name
        assert not field.name.startswith("_")


@pytest.mark.parametrize("cls", [ClickBack, ClickMainTab, ClickSend, CustomFind])
def test_fields_declared_as_passed_in_are_cleaned_the_same_way(cls):
    """Whatever cleaning a field declares is applied to defaults as well."""
    block = cls()
    for field in cls.FIELDS:
        expected = field.coerce(cls._field_default(field))
        assert getattr(block, field.name) == expected, (cls.__name__, field.name)


def test_a_preset_dict_round_trips_through_the_constructor():
    for cls in (ClickBack, ClickMainTab, ClickSend, CustomFind):
        block = cls(tab_name="Foo", match_text="Foo", custom_name="Foo",
                     confirm_pause_ms=0)
        again = type(block)(**block.to_dict())
        assert again.to_dict() == block.to_dict(), cls.__name__


def test_unknown_settings_still_land_in_config_and_are_written_back():
    """A preset from an older version keeps keys this block ignores."""
    block = ClickBack(extra_from_old_build={"a": 1})
    assert block.config == {"extra_from_old_build": {"a": 1}}
    assert block.to_dict()["extra_from_old_build"] == {"a": 1}


def test_pre_delay_and_enabled_may_arrive_inside_the_settings():
    block = ClickBack(**{"pre_delay_ms": 42, "enabled": False})
    assert block.pre_delay_ms == 42 and block.enabled is False
    assert "pre_delay_ms" not in block.config
    assert block.to_dict()["pre_delay_ms"] == 42


def test_constructor_signature_keeps_its_own_defaults():
    """The saved signature is a contract: the config panel builds by keyword."""
    sig = str(inspect.signature(ClickBack.__init__))
    assert "selector" in sig and "tab_name: str = " in sig
    assert "pre_delay_ms: int = 800" in sig
    assert str(inspect.signature(CustomFind.__init__)).count(":") >= 8


def test_defaults_come_from_the_constructor_not_a_second_copy():
    """FIELDS holds no second copy of a default that could drift from it."""
    for cls in (ClickBack, ClickMainTab, ClickSend, CustomFind):
        params = inspect.signature(cls.__init__).parameters
        for field in cls.FIELDS:
            param = params.get(field.name)
            assert param is not None, (cls.__name__, field.name)
            assert param.default is not inspect.Parameter.empty
            assert cls._field_default(field) == param.default
            if field.default is not _UNSET:
                assert field.default == param.default, (cls.__name__, field.name)


def test_to_dict_key_order_is_the_wire_format_the_presets_use():
    block = ClickBack()
    assert list(block.to_dict()) == (["block_id"] + [f.name for f in
                                                      ClickBack.FIELDS]
                                     + ["pre_delay_ms", "enabled"])
    assert json.dumps(block.to_dict())       # must stay JSON-serialisable


# ── what the blocks hand to the shared runner ─────────────────────────
@pytest.mark.parametrize("cls,expected", [
    (ClickBack, {"label_selector": "p.chat-title",
                 "match_text": "Гостиная", "click_enabled": True,
                 "label": "back tab “Гостиная”"}),
    (ClickMainTab, {"label_selector": "p.chat-title",
                    "match_text": "Гостиная", "click_enabled": True,
                    "label": "tab “Гостиная”"}),
    (ClickSend, {"label": "send button"}),
    (CustomFind, {"selector": "", "label_selector": "", "match_text": "",
                  "click_enabled": True, "click_selector": "",
                  "highlight_enabled": True, "confirm_pause_ms": 700,
                  "highlight_ms": 1200,
                  "label": "element ''"}),
])
def test_find_kwargs_are_the_runner_keywords(monkeypatch, cls, expected):
    recorder = Recorder()
    patch_runner(monkeypatch, recorder)
    block = cls()
    asyncio.run(block.execute("Nick", None, None))
    assert recorder.calls, "the block must click through find_and_click"
    for key, value in expected.items():
        assert recorder.kwargs[key] == value, (cls.__name__, key)


def test_every_click_block_passes_the_engine_through(monkeypatch):
    class Engine:
        def report(self, message, level="info"):
            pass

    recorder = Recorder()
    patch_runner(monkeypatch, recorder)
    for cls in (ClickBack, ClickMainTab, ClickSend, CustomFind):
        recorder.calls.clear()
        asyncio.run(cls().execute("Nick", None, Engine()))
        assert recorder.kwargs["engine"].__class__ is Engine


def test_click_send_retries_with_the_icon_fallback_and_says_so(monkeypatch):
    class Engine:
        def __init__(self):
            self.lines = []

        def report(self, message, level="info"):
            self.lines.append((message, level))

    recorder = Recorder()
    recorder.result = ActionResult.FAIL
    patch_runner(monkeypatch, recorder)
    engine = Engine()
    assert asyncio.run(ClickSend().execute("Nick", None, engine)) == \
        ActionResult.FAIL
    assert len(recorder.calls) == 2
    assert recorder.calls[1]["selector"] == "button:has(mat-icon)"
    assert recorder.calls[1]["label_selector"] == "mat-icon"
    assert recorder.calls[1]["match_text"] == "send"
    assert recorder.calls[1]["label"] == "send icon “send”"
    assert engine.lines[0][0] == ("↩ Submit button did not work — trying the "
                                  "mat-icon 'send' fallback")
    assert engine.lines[0][1] == "warn"


def test_click_send_without_a_fallback_stops_at_the_first_failure(monkeypatch):
    recorder = Recorder()
    recorder.result = ActionResult.FAIL
    patch_runner(monkeypatch, recorder)
    assert asyncio.run(ClickSend(fallback_selector="").execute(
        "Nick", None, None)) == ActionResult.FAIL
    assert len(recorder.calls) == 1


def test_a_successful_first_attempt_never_tries_the_fallback(monkeypatch):
    recorder = Recorder()
    patch_runner(monkeypatch, recorder)
    assert asyncio.run(ClickSend().execute("Nick", None, None)) == \
        ActionResult.OK
    assert len(recorder.calls) == 1


def test_click_blocks_hold_the_pre_delay_before_the_probe(monkeypatch):
    recorder = Recorder()
    patch_runner(monkeypatch, recorder)
    block = CustomFind(pre_delay_ms=1)
    asyncio.run(block.execute("Nick", None, None))
    assert block.pre_delay_ms == 1                  # slept through BaseAction


# ── MarkerBlock ───────────────────────────────────────────────────────
def test_marker_blocks_report_once_and_are_skipped():
    from actions.repeat_loop import RepeatLoop
    from actions.conditional_skip import ConditionalSkip

    class Engine:
        def __init__(self):
            self.lines = []

        def report(self, message, level="info"):
            self.lines.append(message)

    for cls, fragment in ((RepeatLoop, "cycle count handled by the engine"),
                          (ConditionalSkip, "handled by the engine")):
        engine = Engine()
        assert asyncio.run(cls().execute("Nick", None, engine)) == \
            ActionResult.SKIP
        assert len(engine.lines) == 1
        assert fragment in engine.lines[0]


def test_marker_blocks_always_run_without_a_delay():
    """`pre_delay_ms` in an old preset must not resurrect a delay."""
    from actions.conditional_skip import ConditionalSkip
    from actions.repeat_loop import RepeatLoop

    for cls in (RepeatLoop, ConditionalSkip):
        assert cls().pre_delay_ms == 0
        assert cls(pre_delay_ms=900).pre_delay_ms == 0
        assert asyncio.run(cls().execute("Nick", None, None)) == \
            ActionResult.SKIP


# ── the registry and the shared base ─────────────────────────────────
def test_the_shared_base_is_registered_under_the_blocks_own_ids():
    """The id → block wiring the run console uses must survive the skeleton.

    `ActionRegistry` is global state and other test modules register stubs under
    real ids, so this checks the classes and the id list rather than asking the
    registry which class currently owns an id.
    """
    from actions.registry import ActionRegistry

    ids = set(ActionRegistry.all_ids())
    for block_id, cls in (("CLICK_BACK", ClickBack),
                          ("CLICK_MAIN_TAB", ClickMainTab),
                          ("CLICK_SEND", ClickSend), ("CUSTOM_FIND", CustomFind)):
        assert cls.block_id == block_id
        assert issubclass(cls, FindClickBlock)
        assert block_id in ids
        assert isinstance(cls().find_label(), str)


def test_config_schema_entries_match_the_declared_fields():
    block = CustomFind()
    schema = block.config_schema()
    assert list(schema) == ["pre_delay_ms"] + [f.name for f in CustomFind.FIELDS]
    for field in CustomFind.FIELDS:
        entry = schema[field.name]
        assert entry["label"] == field.label
        assert entry["type"] == field.type
        assert entry["default"] == getattr(block, field.name)


def test_the_blocks_do_not_define_their_own_schema_or_execute():
    """The whole point of the skeleton: these two live in one place now."""
    for cls in (ClickBack, ClickMainTab, CustomFind):
        assert cls.__dict__.get("config_schema") is None, cls.__name__
        assert cls.__dict__.get("execute") is None, cls.__name__


def test_action_result_constants_are_still_reachable_from_base():
    assert (ActionResult.OK, ActionResult.FAIL, ActionResult.SKIP) == \
        ("ok", "fail", "skip")
    assert issubclass(ClickBack, BaseAction)
