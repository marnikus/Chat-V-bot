"""Collector mixin 3b _tick first half (<150)."""
import asyncio, json, logging
from datetime import datetime
from typing import Optional
from backend import chat_agent_js
from backend.chat_parser import _signature
from backend.collector_parts.base import CollectorState
log = logging.getLogger("chatbot")
class CollectorMixin3b:
    async def _tick(self) -> str:
        state = await self.parser.state()
        if int(state.get("agent") or 0) < chat_agent_js.AGENT_VERSION:
            # No agent, or one that predates the pane-scoped parser: an old
            # agent cannot tell us who wrote what, so it may not be trusted.
            await self.parser.install()
            self._self_heals += 1
            state = await self.parser.state()
            self._log(f"Re-installed the in-page agent "
                      f"(v{int(state.get('agent') or 0)})", "info")
        self._agent = int(state.get("agent") or 0)
        self._error = ""
        self._last_probe = {
            "count": int(state.get("count") or 0),
            "panes": int(state.get("panes") or 0),
            "pane_source": str(state.get("pane_source") or ""),
            "participants": int(state.get("participants") or 0),
            "partner": str(state.get("partner") or ""),
            "in_authors": list(state.get("in_authors") or []),
            "out_authors": list(state.get("out_authors") or []),
            "scroll": dict(state.get("scroll") or {}),
        }

        if not state.get("ok", True):
            self._log("No chat on this page (state not ok)", "warn")
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")
        if state.get("tab") != "private":
            self._log(f"Active tab is “{state.get('tab')}”, not private —",
                      "warn", state.get("me") or "")
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")
        participants = int(state.get("participants") or 0)
        # "Exactly two people" is enforced whenever the page exposes a
        # count. A private pane WITHOUT a readable counter — the partner
        # with no avatar identification (2026-09-08) — falls through to the
        # author gate below, which refuses the chat the moment any third
        # nick writes here. No gender/avatar check belongs in this path:
        # filters only govern auto-detection in the Action block.
        if (self._settings["require_two_participants"]
                and participants > 0 and participants != 2):
            self._log(f"Refused: {participants} participants, not a private "
                      "chat", "warn", state.get("partner") or "")
            return self._refuse(
                CollectorState.GROUP_TAB,
                f"Group tab ({participants} people) — not collected")

        nick = " ".join(str(state.get("partner") or "").split()).strip()
        if not nick:
            self._log("No partner nick in the active tab", "warn")
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Not in private tab now")

        # My Nick is optional for the archive: in a verified two-person chat
        # the single outbound author IS me, so we adopt it for this session
        # (it is not persisted to config.json unless the user saves it).
        detected_me = " ".join(str(state.get("me") or "").split()).strip()
        outs = [str(o or "").strip() for o in
                (state.get("out_authors") or [])]
        if not detected_me:
            singles = [o for o in outs if o]
            if len(singles) == 1 and singles[0].lower() != nick.lower():
                detected_me = singles[0]
        if not self.my_nick and detected_me:
            self.configure(my_nick=detected_me)
            self._detected_my_nick = detected_me
            self._log(f"Detected My Nick as “{detected_me}”", "info", nick)
        elif (self.my_nick and detected_me
                and detected_me.lower() != self.my_nick.lower()
                and self.my_nick.lower() not in
                {o.lower() for o in outs if o}):
            # A saved My Nick can go stale: the user renames themselves on
            # the site, and from then on every tick would refuse the chat
            # because the pane's outbound author looks like a "stranger".
            # When the pane self-reports a DIFFERENT nick and the configured
            # one is not among the outbound authors, the pane wins for this
            # session (bug report 2026-09-08, "user now uses a diff name").
            previous = self.my_nick
            self.configure(my_nick=detected_me)
            self._detected_my_nick = detected_me
            self._log(f"My Nick changed from “{previous}” to "
                      f"“{detected_me}” — adopted from the page", "info",
                      nick)

        my_nick = self.my_nick or detected_me
        if my_nick and nick.lower() == my_nick.lower():
            self._log("Partner is the same as My Nick — refusing", "warn",
                      nick)
            return self._refuse(CollectorState.NOT_PRIVATE,
                                "Partner is ambiguous (same as My Nick)")

        head_sig = _signature(state.get("head"))
        tail_sig = _signature(state.get("tail"))
        head_any = _signature(state.get("head_any"))
        tail_any = _signature(state.get("tail_any"))

        if self._nick and nick != self._nick:
            try:
                if await self.repo.rename_if_same_conversation(
                        self._nick, nick, head_sig, tail_sig,
                        head_any=head_any, tail_any=tail_any,
                        dom_count=int(state.get("count") or 0),
                        pane_same=bool(state.get("pane_same"))):
                    self._log(f"Partner “{self._nick}” is now “{nick}” — the history continues", "info", nick)
            except Exception as e:  # noqa: BLE001
                log.debug("rename check for %s failed: %s", nick, e)
        self._tick_ctx = dict(nick=nick, state=state, my_nick=my_nick, head_sig=head_sig, tail_sig=tail_sig, head_any=head_any, tail_any=tail_any)
        return await self._tick_rest()

