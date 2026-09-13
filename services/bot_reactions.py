"""ReactionLabels — the three first-reaction labels, exactly one active.

The AI Bot Chat classifies a person's first reaction as positive, negative or
uncertain. Those are ordinary person labels (`stores/label_store.py`, world
bound — RULE 14), so they show up in both tables and travel with the world;
what is special is the *arity*: a person may carry at most ONE of the three at
a time, and the last decision — whoever made it — wins.

That is why `apply()` is a single `set_for()` and not "unassign then assign":
one call is one reversible entry on the global timeline (RULE 12), and there
is no intermediate state in which a person carries two reactions or none.

Nothing here decides *when* to write. The service calls `apply()` only from
the confirm / manual-override paths, so no label can be applied by the AI
alone (acceptance: "No labels applied without user confirmation").
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")

#: reaction id → (label name, colour). The ids are the wire contract shared by
#: the UI, the Grok answer parser and this module.
REACTIONS: dict[str, tuple[str, str]] = {
    "positive": ("Positive first reaction", "#00c853"),
    "negative": ("Negative first reaction", "#ff3b30"),
    "uncertain": ("Uncertain first reaction", "#ffcc00"),
}


def parse(answer: str) -> dict:
    """Grok's free text as `{reaction, reason}`; unknown wording is uncertain.

    The prompt asks for `positive - reason`, but a model may answer with a
    sentence. Matching on the first reaction word that occurs keeps a chatty
    answer usable instead of discarding it, and an answer naming none at all
    is *uncertain* — which is exactly what "we could not tell" means here.
    """
    text = str(answer or "").strip()
    lowered = text.lower()
    hits = [(lowered.find(key), key) for key in REACTIONS if key in lowered]
    reaction = min(hits)[1] if hits else "uncertain"
    reason = text.split("-", 1)[1].strip() if "-" in text else text
    return {"reaction": reaction, "reason": reason[:400], "raw": text[:800]}


class ReactionLabels:
    """Definitions, the active reaction of a person, and the single write."""

    def __init__(self, store) -> None:
        self._store = store

    def _def_for(self, reaction: str) -> dict | None:
        """The label definition of one reaction, created on first use."""
        name, color = REACTIONS[reaction]
        return self._store.by_name(name) or self._store.create(name, color)

    def ensure_defs(self) -> dict:
        """reaction id → label id, creating any definition still missing."""
        out = {}
        for reaction in REACTIONS:
            found = self._def_for(reaction)
            if found:
                out[reaction] = found["id"]
        return out

    def reaction_ids(self) -> dict:
        """reaction id → label id for the definitions that already exist."""
        out = {}
        for reaction, (name, _color) in REACTIONS.items():
            found = self._store.by_name(name)
            if found:
                out[reaction] = found["id"]
        return out

    def active(self, nick: str) -> str:
        """The reaction currently on this person, or "" when there is none."""
        carried = set(self._store.ids_for(nick))
        for reaction, label_id in self.reaction_ids().items():
            if label_id in carried:
                return reaction
        return ""

    def _one_reaction(self, nick: str, reaction: str) -> list | None:
        """The person's label ids with `reaction` on and the others off."""
        ids = self.ensure_defs()
        wanted = ids.get(reaction)
        if not wanted:
            return None
        others = {value for key, value in ids.items() if key != reaction}
        keep = [i for i in self._store.ids_for(nick) if i not in others]
        return keep if wanted in keep else keep + [wanted]

    def apply(self, nick: str, reaction: str) -> bool:
        """Make `reaction` the ONE active reaction label of `nick`.

        Returns False when nothing changed, so the caller can skip pushing an
        empty undo entry.
        """
        if reaction not in REACTIONS or not str(nick or "").strip():
            return False
        if self.active(nick) == reaction:
            return False
        keep = self._one_reaction(nick, reaction)
        if keep is None:
            return False
        return bool(self._store.set_for(nick, keep))

    def clear(self, nick: str) -> bool:
        """Remove whatever reaction label the person carries."""
        ids = set(self.reaction_ids().values())
        keep = [i for i in self._store.ids_for(nick) if i not in ids]
        if len(keep) == len(self._store.ids_for(nick)):
            return False
        return bool(self._store.set_for(nick, keep))

    def state_of(self, nick: str) -> dict:
        """What the window renders: the three labels and which one is on."""
        return {"nick": nick, "active": self.active(nick),
                "available": [{"id": key, "name": name, "color": color}
                              for key, (name, color) in REACTIONS.items()]}
