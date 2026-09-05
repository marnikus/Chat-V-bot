"""Tri-state person filter used by the Scroll & Parse pipeline.

Each rule is one of three strings so that "don't care" stays distinguishable
from "must be false":

    "any"  — ignore this attribute
    "yes"  — the person MUST have it
    "no"   — the person MUST NOT have it

Storing the rules as plain block parameters (rather than in the global
CriteriaEngine) is what makes them round-trip through the preset machinery:
``BaseAction.to_dict()`` serialises every instance attribute automatically.
"""

import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("chatbot")

ANY = "any"
YES = "yes"
NO = "no"
TRISTATE = (ANY, YES, NO)

#: Attribute -> (human name when required, human name when forbidden)
_ATTRS = {
    "female": ("female", "not female"),
    "registered": ("registered", "not registered"),
    "guest": ("guest", "not guest"),
    "anonymous": ("anonymous", "not anonymous"),
}


def normalize(value, default: str = ANY) -> str:
    """Coerce anything the UI/preset may hold into a valid tri-state string."""
    if isinstance(value, bool):          # legacy presets stored booleans
        return YES if value else ANY
    text = str(value or "").strip().lower()
    if text in TRISTATE:
        return text
    if text in ("true", "1", "must", "require"):
        return YES
    if text in ("false", "0", "must_not", "exclude"):
        return NO
    return default


@dataclass
class FilterVerdict:
    """Why a person was accepted or rejected."""
    passed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.passed


class PersonFilter:
    """Evaluate people against tri-state rules (+ optional panel criteria)."""

    def __init__(self, female: str = YES, registered: str = NO,
                 guest: str = YES, anonymous: str = NO,
                 panel_criteria: Optional[object] = None):
        self.female = normalize(female)
        self.registered = normalize(registered)
        self.guest = normalize(guest)
        self.anonymous = normalize(anonymous)
        #: optional CriteriaEngine — ANDed with the rules above
        self.panel_criteria = panel_criteria

    # ── description ──────────────────────────────────────────────
    def rules(self) -> list[str]:
        out = []
        for attr, (yes_name, _no_name) in _ATTRS.items():
            mode = getattr(self, attr)
            if mode == YES:
                out.append(f"must be {yes_name}")
            elif mode == NO:
                out.append(f"must NOT be {yes_name}")
        return out

    def describe(self) -> str:
        rules = self.rules()
        text = "; ".join(rules) if rules else "no attribute rules (accept all)"
        if self.panel_criteria is not None:
            text += " + Filter panel criteria"
        return text

    @property
    def is_empty(self) -> bool:
        return not self.rules() and self.panel_criteria is None

    # ── evaluation ───────────────────────────────────────────────
    def check(self, person: dict) -> FilterVerdict:
        """Evaluate one person dict (female/registered/guest/anonymous keys)."""
        for attr, (yes_name, no_name) in _ATTRS.items():
            mode = getattr(self, attr)
            if mode == ANY:
                continue
            has = bool(person.get(attr, False))
            if mode == YES and not has:
                return FilterVerdict(False, no_name)
            if mode == NO and has:
                return FilterVerdict(False, yes_name)
        if self.panel_criteria is not None:
            try:
                if not self.panel_criteria.evaluate_user(person):
                    return FilterVerdict(False, "rejected by Filter panel criteria")
            except Exception as exc:      # never let a bad rule kill the run
                log.warning("Panel criteria evaluation failed: %s", exc)
        return FilterVerdict(True, "matches all criteria")

    def __call__(self, person: dict) -> bool:
        return self.check(person).passed


def sort_people(people: list) -> list:
    """Sort A–Z but with not-yet-messaged people first.

    ``messaged`` is False < True, so un-messaged people sort to the top; within
    each group the order is alphabetical and case-insensitive (``casefold``
    also handles Cyrillic correctly).
    """
    def key(p):
        if isinstance(p, dict):
            messaged, nick = p.get("messaged", False), p.get("nick", "")
        else:
            messaged, nick = getattr(p, "messaged", False), getattr(p, "nick", "")
        return (bool(messaged), str(nick).casefold())

    return sorted(people, key=key)
