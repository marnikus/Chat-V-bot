"""Executor dry-run: full default sequence against a stateful fake page."""
import asyncio
import re

import pytest

from chatflow.blocks import context as ctx_mod
from chatflow.core.config import Settings
from chatflow.core.models import Block, FilterRule, RuleType, UserRow
from chatflow.engine.executor import SequenceExecutor
from chatflow.engine.humanize import Humanizer


class FakeOps:
    """Mimics the virt-chat page: 3 tabs-able rows, tabs, composer."""

    def __init__(self):
        self.typed, self.clicks, self.files, self.scrolls = [], [], [], []
        self.person_tab = None
        self.sent = False
        self.rows = [
            {"nickname": "Lizalo4ka", "classes": ["female-avatar", "anonymous-badge"]},
            {"nickname": "Dr0che", "classes": ["male-avatar", "anonymous-badge"]},
            {"nickname": "МилаяКися", "classes": ["female-avatar", "registered-badge"]},
        ]

    def _tab(self, i):
        tabs = ["Гостиная"] + ([self.person_tab] if self.person_tab else [])
        return tabs[i - 1]

    async def count(self, sel):
        if "div[role=tab]" in sel and "p.chat-title" not in sel:
            return 1 + (1 if self.person_tab else 0)
        if "container-item" in sel:
            return 3
        return 1

    async def exists(self, sel):
        return bool(self.person_tab) if "tab-close-button" in sel else True

    async def text(self, sel):
        return "0 / 1000" if self.sent else "12 / 1000"

    async def eval_js(self, js, sel=""):
        if "querySelectorAll" in js:  # ROWS_JS
            return self.rows
        if "unread" in js:  # TAB_TITLE_JS
            return self._tab(int(re.search(r"nth-child\((\d+)\)", sel).group(1)))
        if "el.value" in js:  # CLEAR_TEXTAREA_JS
            return True
        i = int(re.search(r"nth-child\((\d+)\)", sel).group(1))  # TEXT_JS
        return self.rows[i - 1]["nickname"]

    async def click(self, sel, timeout=None, retries=None):
        self.clicks.append(sel)
        if "tab-close-button" in sel:
            self.person_tab = None
        elif "container-item" in sel:
            i = int(re.search(r"nth-child\((\d+)\)", sel).group(1))
            self.person_tab = self.rows[i - 1]["nickname"]
        elif "type=submit" in sel:
            self.sent = True

    async def keyboard_type(self, ch):
        self.typed.append(ch)

    async def set_files(self, sel, path):
        self.files.append(path)

    async def scroll(self, sel, dy):
        self.scrolls.append(dy)

    async def wait(self, s):
        pass

    async def fill(self, sel, text):
        pass


def make_ctx(ops, events):
    s = Settings()
    s.jitter = 0.0
    s.typing_cps = 500
    s.typing_var = 0.0
    s.message = "Hi {nick}!"
    emit = lambda name, payload: events.append((name, payload))  # noqa: E731
    ctx = ctx_mod.BlockContext(ops, None, s, Humanizer(s), [], emit)
    ctx.rules = [
        FilterRule("1", RuleType.CLASS_INCLUDES.value, "female-avatar", "", True, 0),
        FilterRule("2", RuleType.CLASS_EXCLUDES.value, "registered-badge", "", True, 1),
    ]
    ctx.emit = emit
    return ctx


def b(action, **params):
    return Block.from_dict({"action_type": action, "params": params,
                            "delay_after": 0.0})


def test_full_default_sequence():
    ops = FakeOps()
    events = []
    ctx = make_ctx(ops, events)
    seq = [b("go_main_tab", tab_title="Гостиная"),
           b("scroll_parse", px=100, pause=0.01, empty_runs=1, max_scrolls=2),
           b("pick_target", order="top"),
           b("click_user"),
           b("type_message", source="single"),
           b("attach_image"),
           b("send_message"),
           b("close_tab")]
    ex = SequenceExecutor(lambda n, p: events.append((n, p)), lambda *a: None, ctx.s)
    summary = asyncio.run(ex.run_sequence(seq, ctx))
    assert summary["sent"] == 1 and summary["passes"] == 2
    assert "".join(ops.typed) == "Hi Lizalo4ka!"
    found = [p for n, p in events if n == "users_found"]
    assert found[0]["passed"] == ["Lizalo4ka"]
    sent = [p for n, p in events if n == "message_sent"]
    assert sent[0]["nickname"] == "Lizalo4ka"
    assert ctx.queued == []
    # send clicked before tab close
    assert ops.clicks.index(next(c for c in ops.clicks if "type=submit" in c)) \
        < ops.clicks.index(next(c for c in ops.clicks if "tab-close-button" in c))
    assert ops.scrolls, "expected wheel scrolls during parse"


def test_loop_and_condition():
    ops = FakeOps()
    events = []
    ctx = make_ctx(ops, events)
    seq = [b("condition", expr="1==2"), b("wait", seconds=0.02),
           b("wait", seconds=0.02), b("loop", iterations=2),
           b("wait", seconds=0.02), b("pick_target", order="top")]
    logs = []
    ex = SequenceExecutor(lambda n, p: events.append((n, p)),
                          lambda icon, msg: logs.append(msg), ctx.s)
    asyncio.run(ex.run_sequence(seq, ctx))
    waits = [p for n, p in events if n == "log" and p["msg"].startswith("Waited")]
    skips = [m for m in logs if m.startswith("Skipped")]
    # W1 skipped by the false condition; W2 once; W3 once (the pick_target in
    # the body terminates the sub-loop after the first iteration)
    assert len(waits) == 2, f"expected 2 waits, got {len(waits)}"
    assert len(skips) == 1
