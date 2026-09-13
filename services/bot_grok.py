"""GrokClient — the ONE place that talks to the Grok completions API.

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

log = logging.getLogger("chatbot")

DEFAULT_URL = "https://api.x.ai/v1/chat/completions"
DEFAULT_MODEL = "grok-2-latest"
DEFAULT_TIMEOUT_S = 30


class GrokSettings:
    """The connection half of the `grok` config section."""

    def __init__(self, config=None) -> None:
        self._config = config

    def _read(self, key: str, default: Any) -> Any:
        if self._config is None:
            return default
        value = self._config.get("grok", key, default=default)
        return default if value in (None, "") else value

    @property
    def api_key(self) -> str:
        return str(self._read("api_key", "")).strip()

    @property
    def url(self) -> str:
        return str(self._read("url", DEFAULT_URL)).strip() or DEFAULT_URL

    @property
    def model(self) -> str:
        return str(self._read("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL

    @property
    def timeout_s(self) -> int:
        try:
            return max(1, int(self._read("timeout_s", DEFAULT_TIMEOUT_S)))
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_S


def reply_text(body: Any) -> Result[str]:
    """The assistant text of a completions response, or a typed error."""
    if not isinstance(body, dict):
        return Err("grok_bad_body", "the API answered with a non-object")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return Err("grok_no_choices", str(body.get("error") or body)[:200])
    message = (choices[0] or {}).get("message") or {}
    text = str(message.get("content") or "").strip()
    if not text:
        return Err("grok_empty", "the model returned an empty message")
    return Ok(text)


class GrokClient:
    """One `complete(prompt)` call against the configured Grok endpoint."""

    def __init__(self, config=None, session_factory=None) -> None:
        self.settings = GrokSettings(config)
        #: injected in tests; the default builds an `aiohttp.ClientSession`
        self._session_factory = session_factory

    def _payload(self, prompt: str) -> dict:
        return {"model": self.settings.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False}

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        import aiohttp
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.settings.timeout_s))

    async def _post(self, prompt: str) -> Result[str]:
        headers = {"Authorization": f"Bearer {self.settings.api_key}",
                   "Content-Type": "application/json"}
        async with self._session() as session:
            async with session.post(self.settings.url, json=self._payload(prompt),
                                    headers=headers) as response:
                if int(getattr(response, "status", 0)) != 200:
                    return Err("grok_http",
                               f"HTTP {getattr(response, 'status', '?')}")
                return reply_text(await response.json())

    async def complete(self, prompt: str) -> Result[str]:
        """Ask Grok once. Every failure comes back as `Err`, never raised."""
        if not str(prompt or "").strip():
            return Err("grok_no_prompt", "the prompt is empty")
        if not self.settings.api_key:
            return Err("grok_no_key",
                       "no Grok API key — set it in the Prompt Editor window")
        try:
            return await self._post(prompt)
        except Exception as exc:                            # noqa: BLE001
            log.warning("Grok request failed: %s", exc)
            return Err("grok_unreachable", str(exc)[:200])


def client_for(config, session_factory: Optional[Any] = None) -> GrokClient:
    """Factory kept next to the client so callers need one import."""
    return GrokClient(config=config, session_factory=session_factory)
