"""Named prompt presets — saved versions of a prompt template.

A *template* (`bot_prompts`) is one of the two things the app knows how to
ask for: "suggest next message", "analyze reaction". A *preset* is a saved
wording of one of them, so a user can keep "short and casual" next to
"formal, three sentences" and switch between them without retyping.

Presets belong to a template: the ones listed while editing "suggest next
message" are that template's presets. Applying a preset only fills the
editor — the user still presses Save for it to become the live template, so
selecting one to read it cannot change what the app sends.

Stored in `config/presets.json` under `prompt_presets`, alongside the AI
connections and the app's other named things. Deleting a preset touches no
connection and no API key: different section, different verbs.
"""

from __future__ import annotations

import logging
import re

from services import bot_prompts
from services.named_section import NamedSection

log = logging.getLogger("chatbot")

SECTION = "prompt_presets"

SAFE_ID = re.compile(r"[^a-z0-9_-]+")


def slug(template_id: str, title: str) -> str:
    """A stable id: the template it belongs to, plus the user's name."""
    base = SAFE_ID.sub("-", str(title or "").strip().lower()).strip("-")
    return f"{template_id}:{base or 'preset'}"


class PresetLibrary(NamedSection):
    """CRUD over the saved prompt presets."""

    SECTION = SECTION       # the config section this library owns

    def for_template(self, template_id: str) -> list[dict]:
        """Every preset saved for one template, as the dropdown lists them."""
        return [{"id": key, "title": str(row.get("title") or key),
                 "template": str(row.get("template") or ""),
                 "text": str(row.get("text") or "")}
                for key, row in sorted(self._all().items())
                if isinstance(row, dict)
                and row.get("template") == str(template_id)]

    def get(self, ident: str) -> dict | None:
        row = self._all().get(str(ident))
        if not isinstance(row, dict):
            return None
        return {"id": str(ident), "title": str(row.get("title") or ident),
                "template": str(row.get("template") or ""),
                "text": str(row.get("text") or "")}

    def save(self, template_id: str, title: str, text: str,
             ident: str = "") -> str:
        """Create a preset, or update `ident` when one is given.

        Returns the id, or "" when refused. An empty body is refused for the
        same reason `PromptLibrary.save` refuses one: a blank prompt is not
        a prompt. An unknown placeholder is fine — that is a warning, not a
        rejection (I-27).
        """
        if self._config is None or template_id not in bot_prompts.DEFAULTS:
            return ""
        if not str(text or "").strip() or not str(title or "").strip():
            return ""
        ident = str(ident or "").strip() or slug(template_id, title)
        self._config.named_set(SECTION, ident,
                               {"title": str(title).strip(),
                                "template": str(template_id),
                                "text": str(text)})
        return ident

    def delete(self, ident: str) -> bool:
        """Remove one preset. Never touches a connection or a template."""
        if self._config is None:
            return False
        return bool(self._config.named_delete(SECTION, str(ident)))
