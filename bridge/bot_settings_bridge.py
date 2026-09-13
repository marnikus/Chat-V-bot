"""BotSettingsBridge — the AI Settings dialog's wire.

Its own bridge for the same reason the Prompt Editor has one: it is its own
surface (the ⚙ dialog in the AI Bot Chat window), and folding it into the
editor's bridge pushed that class past RULE 16's 15-method budget — the gate
caught it, which is what the gate is for.

What it owns: which providers exist, each one's saved settings, which is
active, and the connection test.

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
from services.bot_grok import GrokSettings, client_for

log = logging.getLogger("chatbot")


class BotSettingsBridge(BotSideBridge):
    """No signals of its own: answers ride the Bot Chat bridge, keyed by
    `req_id`, because the router exposes one signal of each name."""

    def _settings_of(self, provider) -> GrokSettings:
        """The settings of ONE provider, active or not."""
        return GrokSettings(self.ctx.config, str(provider or ""))

    @Slot(result=str)
    def bot_providers(self):
        """Every provider, each with its saved state and a MASKED key.

        The dialog needs to show that a key is stored without being able to
        leak it, so the key itself never crosses this wire in either
        direction except when the user is setting a new one.
        """
        active = GrokSettings.active_id(self.ctx.config)
        entries = []
        for spec in providers.PROVIDERS.values():
            entry = dict(spec.as_dict())
            entry.update(self._settings_of(spec.id).state())
            entry["active"] = spec.id == active
            entries.append(entry)
        return json.dumps({"active": active, "providers": entries},
                          ensure_ascii=False)

    @Slot(str, str, str, str, result=bool)
    def bot_save_provider(self, provider, api_key, model, url):
        """Save one provider's settings. Touches no other provider, and no
        prompt template — switching providers must never lose either."""
        return bool(self._settings_of(provider).save(api_key, model, url))

    @Slot(str, result=bool)
    def bot_use_provider(self, provider):
        """Make this the provider the AI Bot Chat sends to."""
        return bool(self._settings_of(provider).use(provider))

    @Slot(str, str)
    def bot_test_provider(self, req_id, provider):
        """One real request with the saved settings, reported as ok/why.

        Deliberately the SAME transport the feature uses, not a cheaper
        probe: a test that exercises a different path can pass while the
        real call fails, which is worse than no test at all.
        """
        owner = self._chat_bridge()
        schedule(owner, req_id, self._probe(provider))

    async def _probe(self, provider) -> dict:
        client = client_for(self.ctx.config, provider=str(provider or ""))
        answer = await client.complete("Reply with the single word: ok")
        if answer.is_err:
            return {"ok": False, "provider": client.settings.provider,
                    "code": answer.code, "detail": answer.detail}
        return {"ok": True, "provider": client.settings.provider,
                "model": client.settings.model,
                "detail": f"answered: {answer.value[:60]}"}
