"""GrokClient — the ONE place that talks to an AI completions API.

Named for Grok because that is the provider it shipped with, but it is now
the generic transport: WHICH provider it talks to is a `ProviderSpec` from
`bot_providers`, and only the request shaping and reply parsing vary. The
timeout, the empty-prompt and missing-key guards and the
exception-to-`Result` funnel are identical for every provider, so there is
one of each.

A domain failure (no API key, HTTP error, unparseable body) is a typed
`Result`, never an exception: the AI Bot Chat window must be able to say
*why* it has no suggestion instead of dying behind an unhandled task
(AGENT_RULES RULE 4 — empty is not broken).

The transport is `aiohttp`, already a dependency. Nothing here imports Qt,
a bridge or a store, so the client is testable with a fake session.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from core.result import Err, Ok, Result
from services import bot_providers

log = logging.getLogger("chatbot")

DEFAULT_TIMEOUT_S = 30


def mask(api_key: str) -> str:
    """A key as the dialog may show it: proof it is stored, not the secret."""
    key = str(api_key or "")
    return f"{key[:4]}…{key[-4:]}" if len(key) > 12 else ("set" if key else "")


class GrokSettings:
    """The connection settings of ONE provider, inside the `grok` section.

    Layout, and why: the provider that shipped first keeps the original flat
    keys (`grok.api_key`, `grok.model`, `grok.url`), so an existing install
    keeps working untouched. Any other provider lives under
    `grok.providers.<id>`. Per-provider storage is what makes switching
    providers non-destructive — the acceptance criterion is that changing
    provider must not lose anything, and keys share that requirement with
    the templates, which live in `grok.prompts` and are never read here.
    """

    def __init__(self, config=None, provider: str = "") -> None:
        self._config = config
        self.provider = str(provider or "") or self.active_id(config)
        self.spec = bot_providers.spec_of(self.provider)

    @staticmethod
    def active_id(config) -> str:
        """Which provider the app is currently set to use."""
        if config is None:
            return bot_providers.DEFAULT_PROVIDER
        value = config.get("grok", "provider",
                           default=bot_providers.DEFAULT_PROVIDER)
        return str(value or bot_providers.DEFAULT_PROVIDER)

    def _bucket(self) -> dict:
        """This provider's stored settings; the first provider is flat."""
        if self._config is None:
            return {}
        if self.provider == bot_providers.DEFAULT_PROVIDER:
            return {}
        buckets = self._config.get("grok", "providers", default={})
        bucket = (buckets or {}).get(self.provider)
        return bucket if isinstance(bucket, dict) else {}

    def _read(self, key: str, default: Any) -> Any:
        if self._config is None:
            return default
        if self.provider != bot_providers.DEFAULT_PROVIDER:
            value = self._bucket().get(key)
            return default if value in (None, "") else value
        value = self._config.get("grok", key, default=default)
        return default if value in (None, "") else value

    @property
    def api_key(self) -> str:
        return str(self._read("api_key", "")).strip()

    @property
    def url(self) -> str:
        return str(self._read("url", self.spec.url)).strip() or self.spec.url

    @property
    def model(self) -> str:
        return (str(self._read("model", self.spec.model)).strip()
                or self.spec.model)

    @property
    def endpoint(self) -> str:
        """The URL actually posted to (Gemini needs the model in the path)."""
        return bot_providers.endpoint(self.spec, self.url, self.model)

    @property
    def timeout_s(self) -> int:
        try:
            return max(1, int(self._read("timeout_s", DEFAULT_TIMEOUT_S)))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_S

    def save(self, api_key: str, model: str = "", url: str = "") -> bool:
        """Store this provider's settings from the AI Settings dialog.

        A blank field leaves the stored value alone, so re-saving the model
        does not wipe a key the password input never echoes back. Writes
        only this provider's keys — never another provider's, and never
        `grok.prompts`.
        """
        if self._config is None:
            return False
        fields = {"api_key": api_key, "model": model, "url": url}
        given = {k: str(v).strip() for k, v in fields.items()
                 if str(v or "").strip()}
        if given:
            self._write(given)
        self._config.save()
        return True

    def _write(self, given: dict) -> None:
        if self.provider == bot_providers.DEFAULT_PROVIDER:
            for key, value in given.items():
                self._config.set("grok", key, value)
            return
        buckets = dict(self._config.get("grok", "providers", default={}) or {})
        bucket = dict(buckets.get(self.provider) or {})
        bucket.update(given)
        buckets[self.provider] = bucket
        self._config.set("grok", "providers", buckets)

    def use(self, provider: str) -> bool:
        """Make `provider` the active one. Touches no key and no template."""
        if self._config is None or provider not in bot_providers.PROVIDERS:
            return False
        self._config.set("grok", "provider", provider)
        self._config.save()
        return True

    def state(self) -> dict:
        """What the dialog shows: a MASKED key, never the key itself."""
        return {"provider": self.provider, "title": self.spec.title,
                "has_key": bool(self.api_key), "masked": mask(self.api_key),
                "model": self.model, "url": self.url,
                "endpoint": self.endpoint}


def reply_text(body: Any, provider: str = "") -> Result[str]:
    """The assistant text of a response, or a typed error.

    Each failure keeps its own code because the window shows them to the
    user: "the endpoint is not speaking JSON" and "the model had nothing to
    say" are different problems with different fixes.
    """
    return bot_providers.reply_of(bot_providers.spec_of(provider), body)


class GrokClient:
    """One `complete(prompt)` call against the configured AI endpoint."""

    def __init__(self, config=None, session_factory=None,
                 provider: str = "") -> None:
        self.settings = GrokSettings(config, provider)
        #: injected in tests; the default builds an `aiohttp.ClientSession`
        self._session_factory = session_factory

    @property
    def spec(self):
        return self.settings.spec

    def _payload(self, prompt: str) -> dict:
        return bot_providers.body_of(self.spec, self.settings.model, prompt)

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        import aiohttp
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.timeout_s))

    async def _post(self, prompt: str) -> Result[str]:
        headers = bot_providers.headers_of(self.spec, self.settings.api_key)
        async with self._session() as session:
            async with session.post(self.settings.endpoint,
                                    json=self._payload(prompt),
                                    headers=headers) as response:
                if int(getattr(response, "status", 0)) != 200:
                    return Err("grok_http",
                               f"HTTP {getattr(response, 'status', '?')}")
                return bot_providers.reply_of(self.spec,
                                              await response.json())

    async def complete(self, prompt: str) -> Result[str]:
        """Ask Grok once. Every failure comes back as `Err`, never raised."""
        if not str(prompt or "").strip():
            return Err("grok_no_prompt", "the prompt is empty")
        if not self.settings.api_key:
            return Err("grok_no_key",
                       f"no {self.spec.title} API key — set one in the AI "
                       f"Settings dialog (the ⚙ button in the AI Bot Chat "
                       f"window)")
        try:
            return await self._post(prompt)
        except Exception as exc:                            # noqa: BLE001
            log.warning("Grok request failed: %s", exc)
            return Err("grok_unreachable", str(exc)[:200])


def client_for(config, session_factory: Optional[Any] = None,
               provider: str = "") -> GrokClient:
    """Factory kept next to the client so callers need one import."""
    return GrokClient(config=config, session_factory=session_factory,
                      provider=provider)
