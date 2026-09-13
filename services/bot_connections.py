"""Named AI connections — the things the user actually picks from.

A **provider** (`bot_providers`) is a vendor's wire format: there are two,
they are code, and the user cannot add one. A **connection** is a named,
user-created instance of a provider — "Grok grok-4.3", "Grok grok-2
(cheap)", "work Gemini" — with its own key, model and endpoint. Several
connections may share a provider; that is the whole point, and it is why
the per-provider bucket this replaces was not enough.

Stored in `config/presets.json` under `ai_connections`, through the same
`named_*` CRUD the app already uses for stack presets and message
templates. That buys atomic writes, restart persistence and the per-path
instance cache for free (RULE 5: one way to do a thing).

Keys are plaintext on this machine, as everywhere else in this repo. They
are never returned over the bridge except MASKED — see `Connection.state`.
"""

from __future__ import annotations

import logging
import re

from services import bot_providers
from services.bot_grok import mask
from services.named_section import NamedSection

log = logging.getLogger("chatbot")

SECTION = "ai_connections"

#: where the active connection's id is remembered
ACTIVE_KEY = "connection"

#: a connection id: lowercase, safe in a JSON key and a DOM id
SAFE_ID = re.compile(r"[^a-z0-9_-]+")


def slug(title: str, provider: str) -> str:
    """A stable id derived from the name the user typed."""
    base = SAFE_ID.sub("-", str(title or "").strip().lower()).strip("-")
    return base or f"{provider}-connection"


class Connection:
    """One configured way to reach a model."""

    def __init__(self, ident: str, data: dict) -> None:
        self.id = str(ident)
        self._data = data if isinstance(data, dict) else {}

    @property
    def provider(self) -> str:
        return str(self._data.get("provider") or "")

    @property
    def spec(self):
        return bot_providers.spec_of(self.provider)

    @property
    def title(self) -> str:
        return str(self._data.get("title") or "").strip() or self.id

    @property
    def api_key(self) -> str:
        return str(self._data.get("api_key") or "").strip()

    @property
    def model(self) -> str:
        return str(self._data.get("model") or "").strip() or self.spec.model

    @property
    def url(self) -> str:
        return str(self._data.get("url") or "").strip() or self.spec.url

    @property
    def endpoint(self) -> str:
        return bot_providers.endpoint(self.spec, self.url, self.model)

    def problem(self) -> str:
        """Why this connection cannot run a prompt, or "" when it can.

        A connection the user selected but which cannot work must SAY so —
        listing it as if it were fine and then doing nothing is the silent
        failure this whole feature keeps being bitten by.
        """
        if self.provider not in bot_providers.PROVIDERS:
            return f"unknown provider “{self.provider}”"
        if not self.api_key:
            return "no API key"
        return ""

    def state(self) -> dict:
        """What the dropdown and the settings window show. Never the key."""
        return {"id": self.id, "title": self.title, "provider": self.provider,
                "provider_title": self.spec.title, "model": self.model,
                "url": self.url, "endpoint": self.endpoint,
                "has_key": bool(self.api_key), "masked": mask(self.api_key),
                "problem": self.problem(), "ok": not self.problem()}


class ConnectionStore(NamedSection):
    """CRUD over the named connections, plus which one is active."""

    SECTION = SECTION       # the config section this library owns

    def all(self) -> list[Connection]:
        """Every connection, oldest first.

        On the very first read an empty store is filled: legacy per-provider
        settings are adopted if there are any, and then EVERY provider gets a
        row. That second half is why Grok and Google are both selectable on a
        fresh install — a provider with no connection would otherwise be a
        vendor the app supports and the user cannot reach. A seeded row has no
        key, so `problem()` reports it and `client_for` still refuses to send:
        visible and unusable, never invisible.
        """
        items = self._all()
        if not items:
            items = self._adopt_legacy()
        items = self._seed_missing(items)
        return [Connection(key, value) for key, value in items.items()]

    def _seed_missing(self, items: dict) -> dict:
        """Add a keyless row for any provider that has no connection yet."""
        if self._config is None:
            return items
        have = {str((row or {}).get("provider") or "")
                for row in items.values() if isinstance(row, dict)}
        for spec in bot_providers.PROVIDERS.values():
            if spec.id in have:
                continue
            items[spec.id] = {"title": spec.title, "provider": spec.id,
                              "api_key": "", "model": spec.model, "url": ""}
            self._config.named_set(SECTION, spec.id, items[spec.id])
        return items

    def get(self, ident: str) -> Connection | None:
        for conn in self.all():
            if conn.id == str(ident):
                return conn
        return None

    def active_id(self) -> str:
        """The id the Prompt Editor last selected (may be empty)."""
        if self._config is None:
            return ""
        return str(self._config.get("grok", ACTIVE_KEY, default="") or "")

    def active(self) -> Connection | None:
        """The connection prompts run through, or the first usable one."""
        connections = self.all()
        if not connections:
            return None
        chosen = self.active_id()
        for conn in connections:
            if conn.id == chosen:
                return conn
        return connections[0]

    def save(self, ident: str, fields: dict) -> str:
        """Create or update one connection; returns its id ("" on refusal).

        A blank `api_key` leaves the stored one alone, because the dialog
        never echoes a key back and "blank" therefore means "unchanged",
        not "erase" (I-29).
        """
        if self._config is None:
            return ""
        title = str(fields.get("title") or "").strip()
        provider = str(fields.get("provider") or "")
        if provider not in bot_providers.PROVIDERS:
            return ""
        ident = str(ident or "").strip() or slug(title, provider)
        self._config.named_set(SECTION, ident,
                               self._merged(ident, title, provider, fields))
        return ident

    def _merged(self, ident: str, title: str, provider: str,
                fields: dict) -> dict:
        """The stored row after an edit — a blank field keeps its old value."""
        old = self._all().get(ident) or {}
        row = {"title": title or old.get("title") or provider,
               "provider": provider}
        for key in ("api_key", "model", "url"):
            given = str(fields.get(key) or "").strip()
            row[key] = given or str(old.get(key) or "")
        return row

    def delete(self, ident: str) -> bool:
        """Remove a connection. Never touches a prompt preset."""
        if self._config is None:
            return False
        gone = bool(self._config.named_delete(SECTION, str(ident)))
        if gone and self.active_id() == str(ident):
            self._config.set("grok", ACTIVE_KEY, "")
            self._config.save()
        return gone

    def use(self, ident: str) -> bool:
        """Make this the connection prompts run through."""
        if self._config is None or self.get(ident) is None:
            return False
        self._config.set("grok", ACTIVE_KEY, str(ident))
        self._config.save()
        return True

    def _adopt_legacy(self) -> dict:
        """Turn the pre-connection per-provider settings into connections.

        Runs once, when no connection exists yet. An install that had a Grok
        key configured keeps working without the user re-typing it — and the
        legacy keys are left in place, so this stays reversible.
        """
        from services.bot_grok import GrokSettings
        if self._config is None:
            return {}
        adopted = {}
        for spec in bot_providers.PROVIDERS.values():
            settings = GrokSettings(self._config, spec.id)
            if not settings.api_key:
                continue
            adopted[spec.id] = {"title": f"{spec.title} — {settings.model}",
                                "provider": spec.id,
                                "api_key": settings.api_key,
                                "model": settings.model, "url": settings.url}
        for ident, row in adopted.items():
            self._config.named_set(SECTION, ident, row)
        if adopted:
            log.info("adopted %d legacy AI connection(s)", len(adopted))
        return adopted
