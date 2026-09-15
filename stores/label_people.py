"""Per-person label assignment (H-C5 split).

Split out of `stores/label_assignments.py` by Round H step H-C5. These four
methods are the only ones that write `assign` — the nick → label-id map — and
they share one rule: an empty list is stored as *no key*, so "this person has
no labels" and "this person was never labelled" read the same to every caller.

Mixed into `stores.label_assignments.LabelAssignments`.

Import direction: `stores.label_rules` for the nick/id normalizers; nothing
imports back.
"""

from __future__ import annotations

from stores.label_rules import normalize_id, normalize_nick


class LabelPeopleMixin:
    """Assign / unassign / set / forget a person's labels; on ``LabelAssignments``."""

    def assign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        if not clean or not any(d["id"] == wanted for d in data["defs"]):
            return False
        current = data["assign"].get(clean, [])
        if wanted in current:
            return False
        data["assign"][clean] = current + [wanted]
        self._owner._save(data)
        return True

    def unassign(self, nick, label_id) -> bool:
        clean = normalize_nick(nick)
        wanted = normalize_id(label_id)
        data = self._owner._normalized()
        current = data["assign"].get(clean)
        if not current or wanted not in current:
            return False
        kept = [i for i in current if i != wanted]
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def set_for(self, nick, ids) -> bool:
        """Replace the whole label set of one person (used by 'Assign')."""
        clean = normalize_nick(nick)
        if not clean:
            return False
        data = self._owner._normalized()
        known = {d["id"] for d in data["defs"]}
        kept = list(dict.fromkeys(normalize_id(i) for i in (ids or [])
                                  if normalize_id(i) in known))
        current = data["assign"].get(clean, [])
        if kept == current:
            return False
        if kept:
            data["assign"][clean] = kept
        else:
            data["assign"].pop(clean, None)
        self._owner._save(data)
        return True

    def forget(self, nick) -> bool:
        """Drop every label of a person (used when a person is hard-deleted)."""
        clean = normalize_nick(nick)
        data = self._owner._normalized()
        if clean not in data["assign"]:
            return False
        data["assign"].pop(clean, None)
        self._owner._save(data)
        return True
