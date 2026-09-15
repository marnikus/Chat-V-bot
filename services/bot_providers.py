"""The AI providers the app can talk to, as data.

A provider is a small spec plus two pure functions — how to shape a request
and how to read a reply. It is deliberately NOT a class hierarchy: Grok and
Google differ in exactly four expressions (url, auth header, body, reply
path) and share about sixty lines of timeout/error handling, so subclasses
would duplicate the shared part to vary the tiny one. Adding a third
provider here is a table entry a reader can take in whole, which is what
"the architecture must allow more providers" actually asks for.

Verified against the vendors' own REST docs (September 2026):

* xAI Grok — `POST /v1/chat/completions`, `Authorization: Bearer <key>`,
  OpenAI-shaped body, reply at `choices[0].message.content`.
* Google Gemini — `POST /v1beta/models/<model>:generateContent`, key in the
  `x-goog-api-key` HEADER (not the query string), body
  `{"contents":[{"parts":[{"text": …}]}]}`, reply at
  `candidates[0].content.parts[0].text`, plus a `finishReason` that must be
  read: a `SAFETY` refusal returns a candidate with no text at all, and
  reporting that as "empty answer" would send the user hunting the wrong bug.
* Kimi (Moonshot) — `POST https://api.moonshot.ai/v1/chat/completions`,
  `Authorization: Bearer <key>`, OpenAI-shaped throughout. It reuses Grok's
  two functions exactly, which is the claim above being cashed: a third
  provider cost one row of this table and no new code.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from core.result import Err, Ok, Result

#: Gemini finish reasons that are not a normal completion, and what to tell
#: the user. `MAX_TOKENS` still carries usable text, so it is not in here.
REFUSALS = {
    "SAFETY": "the model refused this prompt on safety grounds",
    "PROHIBITED_CONTENT": "the model refused this prompt as prohibited",
    "RECITATION": "the model stopped to avoid reciting copyrighted text",
    "BLOCKLIST": "the prompt hit the provider's blocklist",
}


class ProviderSpec(NamedTuple):
    """Everything that differs between one AI HTTP API and another.

    A NamedTuple rather than a hand-written class: it is pure data, and the
    six fields would otherwise be six constructor parameters, which is over
    RULE 16's limit of four for a reason that does not apply to a record.
    """

    id: str
    title: str
    url: str                            # may contain `{model}`
    model: str
    auth: str                           # "bearer" | "x-goog-api-key"
    shape: str                          # "openai" | "gemini"

    def as_dict(self) -> dict:
        """What the Settings dialog lists — never a key, only the shape."""
        return {"id": self.id, "title": self.title, "url": self.url,
                "model": self.model, "needs_model_in_url": "{model}" in self.url}


PROVIDERS: dict[str, ProviderSpec] = {
    "grok": ProviderSpec(
        "grok", "Grok (xAI)", "https://api.x.ai/v1/chat/completions",
        "grok-2-latest", "bearer", "openai"),
    "google": ProviderSpec(
        "google", "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "{model}:generateContent",
        "gemini-2.0-flash", "x-goog-api-key", "gemini"),
    "kimi": ProviderSpec(
        "kimi", "Kimi (Moonshot)", "https://api.moonshot.ai/v1/chat/completions",
        "kimi-k2.6", "bearer", "openai"),
}

DEFAULT_PROVIDER = "grok"


def spec_of(provider_id: str) -> ProviderSpec:
    """The spec for an id, falling back to the default rather than raising."""
    return PROVIDERS.get(str(provider_id or ""), PROVIDERS[DEFAULT_PROVIDER])


def catalog() -> list[dict]:
    """Every provider, for the Settings dialog's list."""
    return [spec.as_dict() for spec in PROVIDERS.values()]


def endpoint(spec: ProviderSpec, url: str, model: str) -> str:
    """The URL to POST to — Gemini puts the model name in the path."""
    return (url or spec.url).replace("{model}", model or spec.model)


def headers_of(spec: ProviderSpec, api_key: str) -> dict:
    """The auth header this provider expects."""
    if spec.auth == "x-goog-api-key":
        return {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"}


def body_of(spec: ProviderSpec, model: str, prompt: str) -> dict:
    """The request body — the two APIs disagree about everything here."""
    if spec.shape == "gemini":
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    return {"model": model, "stream": False,
            "messages": [{"role": "user", "content": prompt}]}


def openai_reply(body: dict) -> Result[str]:
    """`choices[0].message.content`, or a typed error."""
    choices = body.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    if choice is None:
        return Err("grok_no_choices", str(body.get("error") or body)[:200])
    text = str(((choice or {}).get("message") or {}).get("content") or "")
    return Ok(text.strip()) if text.strip() else Err(
        "grok_empty", "the model returned an empty message")


def gemini_text(candidate: dict) -> str:
    """All the text parts of one Gemini candidate, joined."""
    parts = ((candidate or {}).get("content") or {}).get("parts") or []
    return "".join(str(part.get("text") or "") for part in parts
                   if isinstance(part, dict)).strip()


def no_candidate(body: dict) -> Result[str]:
    """Why a Gemini response carries no candidate at all."""
    blocked = (body.get("promptFeedback") or {}).get("blockReason")
    if blocked:
        return Err("grok_refused", f"the prompt was blocked: {blocked}")
    return Err("grok_no_choices", str(body.get("error") or body)[:200])


def gemini_reply(body: dict) -> Result[str]:
    """`candidates[0].content.parts[*].text`, with refusals named.

    A blocked prompt comes back as a candidate with a `finishReason` and no
    text. Calling that "empty" would be a lie the user cannot act on — a
    truncated answer (`MAX_TOKENS`), by contrast, IS an answer.
    """
    candidates = body.get("candidates")
    first = candidates[0] if isinstance(candidates, list) and candidates else None
    if first is None:
        return no_candidate(body)
    text = gemini_text(first)
    if text:
        return Ok(text)
    reason = str(first.get("finishReason") or "")
    if reason in REFUSALS:
        return Err("grok_refused", REFUSALS[reason])
    return Err("grok_empty", "the model returned an empty message")


def reply_of(spec: ProviderSpec, body: Any) -> Result[str]:
    """The assistant's text, whichever provider answered."""
    if not isinstance(body, dict):
        return Err("grok_bad_body", "the API answered with a non-object")
    return gemini_reply(body) if spec.shape == "gemini" else openai_reply(body)
