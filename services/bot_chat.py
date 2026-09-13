"""BotChatService — the AI Bot Chat window's use cases.

Four of them, in the order the window uses them:

* `today(nick)` — the messages of the CURRENT DAY for one person, read from
  the archive (the window is about the running session, not the whole
  history);
* `suggest_reply(nick)` — render the "suggest next message" template over
  those messages, ask Grok, and hand back a *pending* suggestion. It is never
  sent here: sending is `send_message`, which the window only calls after the
  user approved and then clicked "Send to Person";
* `analyze_reaction(nick)` — render the "analyze reaction" template over the
  person's last inbound message and classify the answer. It writes NOTHING;
* `apply_reaction(nick, reaction)` — the single confirmed write, shared by the
  "confirm the analysis" tick and by a manual click on another label, so the
  latest human decision is always the one in the database.

Everything answers a plain dict the bridge can serialise, or a `Result` for
the two operations that can fail on the wire.

ideal-size: 292 lines reason=just under RULE 18's 300 and holding. The
separable parts are already out: transcript shaping (`bot_transcript`),
prompt templates (`bot_prompts`), presets (`bot_presets`), connections
(`bot_connections`), label rules (`bot_reactions`). What remains is the
window's own flow — load, ask, confirm, write — plus the three module-level
delivery helpers that only this flow calls.
"""

from __future__ import annotations

import logging

from core.result import Err, Ok, Result
from services.bot_grok import GrokClient
from services.bot_prompts import PromptLibrary
from services.bot_reactions import ReactionLabels, parse
from services.bot_transcript import (as_transcript, item_text, items_of_day,
                                     last_inbound, today_key)

log = logging.getLogger("chatbot")

#: how many of the day's messages are worth sending as context
CONTEXT_LIMIT = 60
#: the two history scopes the Bot Chat window offers
SCOPE_TODAY = "today"
SCOPE_ALL = "all"
#: how far back to read before filtering to today. `HistoryQuery.page` is
#: frozen by the AREA D API snapshot and takes no `day=`, so the day filter
#: happens here; this bounds how many rows that costs.
PAGE_LIMIT = 200


def empty_detail(nick: str, page: dict) -> str:
    """Why the day is empty, in the words the window shows the user.

    "Nothing today" has two very different causes and the user can only act
    on one of them, so they must not share a message. The day is named
    because the archive dates a message from the page's clock stamps
    (`stores/history_repo_identity.resolve_days`), not from this process's
    calendar: just after midnight a conversation minutes old can legitimately
    still belong to the previous day, and a bare "no messages today" would
    read as data loss.
    """
    if page.get("reason") == "archive_closed":
        return "no database is open — open a world first"
    if page.get("reason") == "no_messages_at_all":
        return (f"no messages with {nick} in the archive at all — "
                f"collect the chat first")
    return (f"no messages with {nick} archived under {page.get('day')} — "
            f"collect the chat first, it may still be dated the previous "
            f"day, or untick “today only” to use the whole conversation")


def scoped_page(nick: str, rows, scope: str) -> dict:
    """The day payload for one scope, with an honest reason when it is empty.

    Module-level and pure: it reads no state off the service, and both the
    cap and the "which scope was empty" wording are things the tests want to
    pin down directly.
    """
    everything = scope == SCOPE_ALL
    found = list(rows or []) if everything \
        else items_of_day(rows, today_key())
    items = found[-CONTEXT_LIMIT:]
    empty_reason = "no_messages_at_all" if everything else "no_messages_today"
    return {"nick": nick, "items": items, "empty": not items,
            "day": today_key(),
            "scope": SCOPE_ALL if everything else SCOPE_TODAY,
            "truncated": len(found) > len(items), "total": len(found),
            "reason": "" if items else empty_reason}


async def open_partner(parser) -> str:
    """The nick the page says the OPEN tab is talking to ("" when unknown)."""
    if parser is None:
        return ""
    try:
        state = await parser.state()
    except Exception as exc:                                # noqa: BLE001
        log.warning("could not read the open chat: %s", exc)
        return ""
    return " ".join(str((state or {}).get("partner") or "").split()).strip()


async def check_recipient(parser, nick: str) -> Result[str]:
    """Refuse unless the chat open in the browser really belongs to `nick`.

    Sending is the only irreversible act in this window, and the window's
    person (picked in User Memory) and the browser's open tab drift apart the
    moment anyone clicks another chat. `chat_sync` already refuses to *read* a
    conversation whose partner does not match (`partner_mismatch`); writing to
    the wrong person is worse, so the same comparison guards it here.

    The gate fails CLOSED like RULE 15's: a page that cannot be read is not
    permission to send.
    """
    from backend.chat_text import norm
    partner = await open_partner(parser)
    if not partner:
        return Err("bot_unknown_chat",
                   "cannot tell which chat is open — nothing was sent")
    if norm(partner) != norm(nick):
        return Err("bot_wrong_chat",
                   f"the open chat is “{partner}”, not “{nick}” — "
                   f"nothing was sent")
    return Ok(partner)


async def deliver(cdp, nick: str, text: str, parser=None) -> Result[str]:
    """Type `text` into `nick`'s chat and press send, verified.

    A module function, not a method: it needs the CDP client and nothing
    from the service, and it is the same verified two-step
    (`type_message` → `click_send`) the TYPE_MESSAGE / CLICK_SEND blocks use,
    so a direct custom message and an approved AI message are delivered by
    exactly one code path — and both pass the recipient gate first.
    """
    if not str(text or "").strip():
        return Err("bot_empty_message", "there is nothing to send")
    if cdp is None or not getattr(cdp, "is_connected", False):
        return Err("bot_not_connected", "not connected to a chat tab")
    allowed = await check_recipient(parser, nick)
    if allowed.is_err:
        return allowed
    from backend.message_injector import click_send, type_message
    if not await type_message(cdp, text):
        return Err("bot_type_failed", "the page did not accept the text")
    if not await click_send(cdp):
        return Err("bot_send_failed", "the send button could not be clicked")
    return Ok(text)


class BotChatService:
    """Today's conversation, the two Grok calls, and the confirmed write."""

    def __init__(self, archive=None, config=None, grok=None,
                 labels=None) -> None:
        self.archive = archive
        self.config = config
        #: the LabelStore, passed IN by the bridge (`ctx.label_store()`).
        #: Never read off `archive`: HistoryService keeps its store private as
        #: `_labels`, so digging for a public `.labels` there silently yields
        #: None in the running app and the labels half of the window dies.
        self.label_store = labels
        #: the one-undo-entry label transaction (`LabelBridge._labels_edit`),
        #: attached by the bridge. An attribute rather than a fifth
        #: constructor parameter: the bridge re-attaches it on every call
        #: anyway (a world switch rebuilds the store), and RULE 16 caps a
        #: signature at four.
        self.edit = None
        self.prompts = PromptLibrary(config)
        self.grok = grok if grok is not None else GrokClient(config=config)

    @property
    def labels(self) -> ReactionLabels | None:
        store = self.label_store
        return ReactionLabels(store) if store is not None else None

    async def load(self, nick: str, scope: str = SCOPE_TODAY) -> dict:
        """One person's messages: today's, or the whole conversation.

        Reads through `HistoryQuery.page` — the archive's ONE read — rather
        than a second hand-written SELECT. The first version did write its
        own and dropped the `media` join doing so, which is why a GIF
        rendered blank: the renderer was fine, the query was a worse copy of
        one that already existed (RULE 5). `scoped_page` then applies the
        scope and the cap.
        """
        query = getattr(self.archive, "query", None)
        db = getattr(self.archive, "db", None)
        if query is None or db is None or not getattr(db, "is_open", False):
            return {"nick": nick, "items": [], "empty": True,
                    "day": today_key(), "scope": scope,
                    "reason": "archive_closed"}
        page = await query.page(nick, limit=PAGE_LIMIT)
        return scoped_page(nick, page.get("items"), scope)

    async def today(self, nick: str) -> dict:
        """Today's messages — the default scope, kept for its four callers."""
        return await self.load(nick, SCOPE_TODAY)

    def context_of(self, nick: str, page: dict, custom: str = "") -> dict:
        """The values every prompt variable resolves against.

        The ONE place a template's context is built, so the Prompt Editor's
        preview cannot drift from what is actually sent. It holds today's
        messages and this person's label — nothing from the config, the
        filesystem or another conversation, which is what keeps private and
        system data out of prompts by construction.
        """
        items = page.get("items") or []
        last = item_text(last_inbound(items))
        return {"person_name": nick, "all_msg": as_transcript(items),
                "last_msg": last, "msg": custom or last,
                "reaction_label": self.active_label_name(nick)}

    def active_label_name(self, nick: str) -> str:
        """The label currently on this person, named as the user sees it."""
        state = self.reaction_state(nick)
        active = state.get("active") or ""
        for item in state.get("available") or []:
            if item.get("id") == active:
                return str(item.get("name") or "")
        return ""

    async def preview(self, nick: str, template_id: str,
                      scope: str = SCOPE_TODAY) -> dict:
        """Exactly what would be sent — the Prompt Editor shows it."""
        page = await self.load(nick, scope)
        return {"nick": nick, "template": template_id,
                "prompt": self.prompts.render(
                    template_id, self.context_of(nick, page))}

    async def suggest_reply(self, nick: str,
                            scope: str = SCOPE_TODAY) -> Result[dict]:
        """A pending reply suggestion — approved and sent by the user only.

        The scope is the window's checkbox: it must reach HERE and not only
        the message list, or the box would change what the user sees while
        the model kept reading a different conversation.
        """
        page = await self.load(nick, scope)
        if page["empty"]:
            return Err("bot_no_messages", empty_detail(nick, page))
        rendered = self.prompts.render("suggest_reply",
                                       self.context_of(nick, page))
        answer = await self.grok.complete(rendered)
        if answer.is_err:
            return answer
        return Ok({"nick": nick, "text": answer.value, "state": "pending"})

    async def analyze_reaction(self, nick: str,
                               scope: str = SCOPE_TODAY) -> Result[dict]:
        """The model's reading of the person's last answer. Writes nothing."""
        page = await self.load(nick, scope)
        last = last_inbound(page["items"])
        if not last:
            if page["empty"]:
                return Err("bot_no_messages", empty_detail(nick, page))
            return Err("bot_no_answer",
                       f"{nick} has not answered today ({page['day']}) — "
                       f"nothing to analyze")
        rendered = self.prompts.render("analyze_reaction",
                                       self.context_of(nick, page))
        answer = await self.grok.complete(rendered)
        if answer.is_err:
            return answer
        result = parse(answer.value)
        result.update({"nick": nick, "state": "pending",
                       "last_message": item_text(last)})
        return Ok(result)

    def reaction_state(self, nick: str) -> dict:
        """The three labels and the active one, for the window's pills."""
        labels = self.labels
        if labels is None:
            return {"nick": nick, "active": "", "available": []}
        return labels.state_of(nick)

    def apply_reaction(self, nick: str, reaction: str) -> Result[dict]:
        """The ONE write: a confirmed analysis or a manual label click.

        The write runs through `self.edit` — the bridge passes
        `LabelBridge._labels_edit` — so an AI-confirmed label is ONE entry on
        the global undo timeline and refreshes the Label Manager and the
        People count exactly like a label set by hand (RULE 12 / I-10).
        Without an editor (headless service tests) it writes directly, rather
        than growing a second copy of that transaction here.
        """
        labels = self.labels
        if labels is None:
            return Err("bot_no_world", "no world is open — open a database")
        if self.edit is None:
            changed = labels.apply(nick, reaction)
        else:
            changed = bool(self.edit(lambda _store: labels.apply(nick, reaction)))
        state = labels.state_of(nick)
        state["changed"] = changed
        return Ok(state)
