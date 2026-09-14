"""BotSettingsBridge — the AI Connections window's wire.

Its own bridge for the same reason the Prompt Editor has one: it is its own
surface (the ⚙ dialog opened from the Grok Prompt Editor), and folding it
into the
editor's bridge pushed that class past RULE 16's 15-method budget — the gate
caught it, which is what the gate is for.

What it owns: the user's NAMED connections — create, update, delete, choose
the active one, and test it. A connection is an instance of a provider, so
several may share one vendor; `bot_providers` describes the vendors, this
describes what the user configured.

Secrets travel ONE way. `bot_providers` reports a MASKED key ("xai-…mnop") so
the dialog can prove a key is stored without being able to leak it; the real
key crosses this wire only when the user is setting a new one.
"""

from __future__ import annotations

import json
import logging

from PySide6.QtCore import Slot

from bridge.bot_bridge import BotSideBridge, schedule
from services import bot_providers as providers
from services.bot_connections import ConnectionStore
from services.bot_grok import client_for

log = logging.getLogger("chatbot")


class BotSettingsBridge(BotSideBridge):
    """No signals of its own: answers ride the Bot Chat bridge, keyed by
    `req_id`, because the router exposes one signal of each name."""

    def _connections(self) -> ConnectionStore:
        """The named connections the user configured."""
        return ConnectionStore(self.ctx.config)

    @Slot(result=str)
    def bot_connections(self):
        """Every configured connection, plus the provider kinds to choose
        from. A key crosses this wire only MASKED (I-29)."""
        store = self._connections()
        active = store.active()
        return json.dumps(
            {"active": active.id if active else "",
             "connections": [conn.state() for conn in store.all()],
             "providers": providers.catalog()},
            ensure_ascii=False)

    @Slot(str, str, result=str)
    def bot_save_connection(self, ident, fields_json):
        """Create or update one connection; returns its id ("" on refusal).

        The five editable fields arrive as one JSON object rather than five
        positional strings: a seven-argument slot is both over RULE 16's
        limit and the kind of signature where a caller silently swaps
        `model` and `url`.
        """
        try:
            fields = json.loads(fields_json or "{}")
        except (TypeError, ValueError):
            return ""
        if not isinstance(fields, dict):
            return ""
        return str(self._connections().save(ident, fields))

    @Slot(str, result=bool)
    def bot_delete_connection(self, ident):
        """Delete one connection. Never touches a prompt preset (I-30)."""
        return bool(self._connections().delete(ident))

    @Slot(str, result=bool)
    def bot_use_connection(self, ident):
        """Make this the connection prompts run through."""
        return bool(self._connections().use(ident))

    @Slot(str, str)
    def bot_test_connection(self, req_id, ident):
        """One real request with the saved settings, reported as ok/why.

        Deliberately the SAME transport the feature uses, not a cheaper
        probe: a test that exercises a different path can pass while the
        real call fails, which is worse than no test at all.
        """
        owner = self._chat_bridge()
        schedule(owner, req_id, self._probe(ident))

    async def _probe(self, ident) -> dict:
        conn = self._connections().get(str(ident or ""))
        if conn is None:
            return {"ok": False, "code": "bot_no_connection",
                    "detail": "no such connection — save it first"}
        if conn.problem():
            return {"ok": False, "code": "bot_bad_connection",
                    "connection": conn.id, "detail": conn.problem()}
        client = client_for(self.ctx.config, connection=conn.id)
        answer = await client.complete("Reply with the single word: ok")
        if answer.is_err:
            return {"ok": False, "connection": conn.id,
                    "code": answer.code, "detail": answer.detail}
        return {"ok": True, "connection": conn.id, "model": conn.model,
                "detail": f"answered: {answer.value[:60]}"}
