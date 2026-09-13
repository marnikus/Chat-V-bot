"""PromptLibrary — the two editable Grok prompt templates.

Each template is a string with `{conversation}` / `{last_message}` /
`{nick}` placeholders. The defaults below ship with the app; an edit made in
the Prompt Editor window is stored in the `grok.prompts` config section and
therefore survives a restart (acceptance: "Edited prompts persist between
sessions").

A template the user broke — deleted, blanked, or filled with an unknown
placeholder — falls back to the shipped default rather than sending garbage
to the API (RULE 13: never persist state you cannot read back).
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")

#: template id → (title, default text). The ids are the wire contract the UI
#: and the config section share; never rename one, add instead.
DEFAULTS: dict[str, tuple[str, str]] = {
    "suggest_reply": (
        "Suggest next message",
        "You are helping to continue a private chat with {nick}.\n"
        "Here is the conversation so far, oldest first:\n\n"
        "{conversation}\n\n"
        "Write ONE short next message that fits this conversation, in the "
        "same language the other person uses. Reply with the message text "
        "only — no quotes, no explanation."),
    "analyze_reaction": (
        "Analyze person's reaction",
        "Classify the reaction of {nick} to the conversation, judging by "
        "their last answer:\n\n\"{last_message}\"\n\n"
        "Answer with exactly one word — positive, negative or uncertain — "
        "then a dash and a short reason, for example:\n"
        "positive - they answered warmly and asked a question back."),
}

PLACEHOLDERS = ("conversation", "last_message", "nick")


def default_text(template_id: str) -> str:
    entry = DEFAULTS.get(template_id)
    return entry[1] if entry else ""


def title_of(template_id: str) -> str:
    entry = DEFAULTS.get(template_id)
    return entry[0] if entry else template_id


def is_usable(text: str) -> bool:
    """A stored template is used only when it is text with a known shape."""
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        text.format(**{key: "" for key in PLACEHOLDERS})
    except (KeyError, IndexError, ValueError):
        return False
    return True


class PromptLibrary:
    """Read, edit and render the templates; the config section is the store."""

    SECTION = "grok"
    KEY = "prompts"

    def __init__(self, config=None) -> None:
        self._config = config

    def _stored(self) -> dict:
        if self._config is None:
            return {}
        value = self._config.get(self.SECTION, self.KEY, default={})
        return value if isinstance(value, dict) else {}

    def text(self, template_id: str) -> str:
        """The user's template when it is usable, else the shipped default."""
        stored = self._stored().get(template_id)
        return stored if is_usable(stored) else default_text(template_id)

    def all(self) -> list[dict]:
        """Every template as the Prompt Editor window lists them."""
        return [{"id": key, "title": title_of(key), "text": self.text(key),
                 "default": default_text(key),
                 "edited": self.text(key) != default_text(key)}
                for key in DEFAULTS]

    def save(self, template_id: str, text: str) -> bool:
        """Store an edited template. False when it is unknown or unusable."""
        if template_id not in DEFAULTS or not is_usable(text):
            return False
        stored = dict(self._stored())
        stored[template_id] = text
        self._config.set(self.SECTION, self.KEY, stored)
        self._config.save()
        return True

    def reset(self, template_id: str) -> bool:
        """Drop the user's edit, so the shipped default is used again."""
        stored = dict(self._stored())
        if template_id not in stored:
            return False
        stored.pop(template_id)
        self._config.set(self.SECTION, self.KEY, stored)
        self._config.save()
        return True

    def render(self, template_id: str, values: dict) -> str:
        """The exact text that will be sent to Grok, placeholders filled."""
        filled = {key: str(values.get(key, "") or "") for key in PLACEHOLDERS}
        try:
            return self.text(template_id).format(**filled)
        except (KeyError, IndexError, ValueError):
            return default_text(template_id).format(**filled)
