"""STEP 4 — Click on Person: open their chat in a new tab.

Locates the person's row in the users list by an EXACT nickname match (so
"Anna" never selects "Annabelle"), clicks it through the shared visual
confirmation runner — RED outline on the detected element, pause, ORANGE
outline on the click target, then the click — and finally confirms that a new
chat tab actually appeared before reporting the step as done.
"""

import asyncio
import json
import logging
from typing import Optional

from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.visual_click import find_and_click_exact

log = logging.getLogger("chatbot")


def _tab_evidence(before: Optional[dict], after: dict, nick: str) -> dict:
    """What changed in the tab list after the click (count delta / title)."""
    before_count = int((before or {}).get("count", 0) or 0)
    after_count = int(after.get("count", 0) or 0)
    titles = [str(t) for t in (after.get("titles") or [])]
    opened = after_count > before_count \
        or any(nick and nick in title for title in titles)
    return {"opened": opened, "before_count": before_count,
            "after_count": after_count, "titles": titles,
            "how": (f"tab count {before_count} → {after_count}"
                    if after_count > before_count
                    else f"a tab titled “{nick}” is open")}


def build_tab_count_js(tab_selector: str, title_selector: str) -> str:
    """JS returning the open chat tabs and their titles."""
    return """(function(){
  try {
    var tabs = document.querySelectorAll(%(tab)s);
    var titles = [];
    for (var i = 0; i < tabs.length; i++) {
      var t = tabs[i].querySelector(%(title)s);
      titles.push(((t ? t.textContent : tabs[i].textContent) || '')
                  .trim().replace(/\\s+/g, ' '));
    }
    return JSON.stringify({count: tabs.length, titles: titles});
  } catch (err) {
    return JSON.stringify({count: 0, titles: [], error: String(err)});
  }
})()""" % {"tab": json.dumps(tab_selector), "title": json.dumps(title_selector)}


class ClickUser(BaseAction):
    block_id = "CLICK_USER"
    name = "Click User"
    icon = "👤"

    def __init__(self, selector: str = "user-item",
                 label_selector: str = ".primary-text",
                 click_selector: str = ".user-container",
                 tab_selector: str = "div[role='tab'].tab-item",
                 tab_title_selector: str = "p.chat-title",
                 verify_new_tab: bool = True, tab_pause_ms: int = 800,
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 respect_order: bool = False,
                 use_person_from_memory: bool = False,
                 pre_delay_ms: int = 1000, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.selector = selector
        self.label_selector = label_selector
        self.click_selector = click_selector
        self.tab_selector = tab_selector
        self.tab_title_selector = tab_title_selector
        self.verify_new_tab = bool(verify_new_tab)
        self.tab_pause_ms = max(0, int(tab_pause_ms))
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms))
        # When ON, the engine works the Status-New people in the Order (#)
        # column sequence (1 first, then 2 … N) instead of the order the
        # page happened to show this run.
        self.respect_order = bool(respect_order)
        # When ON, the engine switches the run to single-target mode: the
        # queue is ignored and this block clicks the person whose nick is
        # saved in {{nick}} memory this run (Pick Person / an earlier Click
        # User), never the next queued person.
        self.use_person_from_memory = bool(use_person_from_memory)

    async def _read_tabs(self, cdp: CDPClient) -> Optional[dict]:
        try:
            raw = await cdp.evaluate(
                build_tab_count_js(self.tab_selector, self.tab_title_selector))
        except Exception as exc:
            log.warning("Tab count probe failed: %s", exc)
            return None
        try:
            res = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            return None
        return res if isinstance(res, dict) else None

    # ── execution ────────────────────────────────────────────────
    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        """Open this person's chat, then prove a tab appeared.

        Three steps: work out which nick to click (the queue's user or the run's
        {{nick}} memory), click it through the shared visual-confirmation
        runner, and confirm the chat tab. Only the last step is
        block-specific — the find/click half is `visual_click`'s job (RULE 1),
        and the "did the page react?" check is what makes this block refuse
        rather than report a click nobody can see.
        """
        await self.pre_delay()
        nick = self._resolve_nick(user_nick, engine)
        if nick is None:
            return ActionResult.FAIL
        label = f"person “{nick}”"
        before = await self._tabs_before(cdp, engine)

        # Find (red) → pause → click target (orange) → click, via the shared runner.
        outcome = await find_and_click_exact(
            cdp,
            text=nick,
            selector=self.selector,
            label_selector=self.label_selector,
            click_selector=self.click_selector,
            highlight_enabled=self.highlight_enabled,
            confirm_pause_ms=self.confirm_pause_ms,
            label=label,
            engine=engine,
        )
        if outcome != ActionResult.OK:
            return outcome

        # The click selected this person: remember the nickname for every
        # {{nick}} field in the rest of this run, until the next selection.
        self._remember_selection(engine, nick)
        if not self.verify_new_tab:
            return ActionResult.OK
        return await self._verify_new_tab(cdp, engine, nick, label, before)

    def _say(self, engine: Optional[object], message: str,
             level: str = "info") -> None:
        """`engine.report` when there is a run console, silence when not."""
        report = getattr(engine, "report", None) if engine else None
        if report is not None:
            report(message, level)

    def _resolve_nick(self, user_nick: str,
                      engine: Optional[object]) -> Optional[str]:
        """The person to click: memory's nick, or the queued user.

        "Use Person from Memory" ignores the queue and clicks the nick saved in
        {{nick}} this run. Never click blindly — with no saved nick the block
        fails loudly instead of guessing at someone.
        """
        if not self.use_person_from_memory:
            return user_nick
        nick = (getattr(engine, "selected_nick", "") or "") if engine else ""
        if nick:
            return nick
        self._say(engine, "❌ Use Person from Memory: no person is saved in "
                          "memory this run — add a Pick Person block before "
                          "it (or let an earlier Click User click someone) so "
                          "{{nick}} has a value", "error")
        log.warning("Click User (memory): no selected nick to click")
        return None

    async def _tabs_before(self, cdp: CDPClient,
                           engine: Optional[object]) -> Optional[dict]:
        """Snapshot the tabs BEFORE the click, so "a new one appeared" is provable."""
        if not self.verify_new_tab:
            return None
        before = await self._read_tabs(cdp)
        if before is not None:
            self._say(engine, f"🗂 {before.get('count', 0)} chat tab(s) open "
                              "before the click", "info")
        return before

    @staticmethod
    def _remember_selection(engine: Optional[object], nick: str) -> None:
        if engine is None:
            return
        note = getattr(engine, "note_selected", None)
        if note is not None:
            note(nick)

    async def _pause_for_tab(self, engine) -> None:
        """Give the site a moment to open the chat tab (with the info line)."""
        if self.tab_pause_ms:
            self._say(engine, f"⏸ Waiting {self.tab_pause_ms} ms for the new "
                              "tab…", "info")
            await asyncio.sleep(self.tab_pause_ms / 1000.0)

    async def _verify_new_tab(self, cdp: CDPClient, engine, nick: str,
                              label: str, before: Optional[dict]) -> str:
        """The tab check: a new tab, or a tab that now carries the nick's name.

        Unreadable page means the click is trusted (`OK` with a warning) — the
        tab count is evidence, not a veto, because the click itself already
        succeeded.
        """
        await self._pause_for_tab(engine)
        after = await self._read_tabs(cdp)
        if after is None:
            self._say(engine, "⚠ Could not read the tab list to confirm the "
                              "new tab — assuming the click worked", "warn")
            return ActionResult.OK
        evidence = _tab_evidence(before, after, nick)
        if not evidence["opened"]:
            return self._no_new_tab(engine, nick, label,
                                    evidence["before_count"],
                                    evidence["after_count"],
                                    evidence["titles"])
        self._say(engine, f"✅ New tab confirmed for {label} "
                          f"({evidence['how']})", "success")
        log.info("Opened chat tab for %s", nick)
        return ActionResult.OK

    def _no_new_tab(self, engine, nick: str, label: str, before_count: int,
                    after_count: int, titles: list) -> str:
        listed = ", ".join(f"“{t[:24]}”" for t in titles[:5]) or "none"
        self._say(engine, f"❌ No new tab appeared for {label} — still "
                          f"{after_count} tab(s): {listed}", "error")
        log.warning("No new tab after clicking %s", nick)
        return ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["selector"] = {"type": "text", "default": "user-item",
                         "label": "Person row selector (CSS)"}
        s["label_selector"] = {"type": "text", "default": ".primary-text",
                               "label": "Nickname element inside (CSS)"}
        s["click_selector"] = {"type": "text", "default": ".user-container",
                               "label": "Element to click inside (CSS)"}
        s["tab_selector"] = {"type": "text",
                             "default": "div[role='tab'].tab-item",
                             "label": "Chat tab selector (for verification)"}
        s["tab_title_selector"] = {"type": "text", "default": "p.chat-title",
                                   "label": "Tab title element (CSS)"}
        s["verify_new_tab"] = {"type": "checkbox", "default": True,
                               "label": "Confirm a new tab opened"}
        s["tab_pause_ms"] = {"type": "number", "default": 800,
                             "label": "Pause after click, before check (ms)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        s["respect_order"] = {"type": "checkbox", "default": False,
                              "label": "Respect the Order (#) column — "
                                       "message people 1, 2, 3… N in list order"}
        s["use_person_from_memory"] = {
            "type": "checkbox", "default": False,
            "label": "Use Person from Memory — click the person saved as "
                     "{{nick}} this run, not the user list (Pick Person / an "
                     "earlier Click User must save the nick first)"}
        return s
