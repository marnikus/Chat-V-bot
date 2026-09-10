"""LabelFilter — the include/exclude rule the collector asks about.

Extracted from `stores/label_store.py` by the AREA B2 split (design §2.5).
It is small and it stays small on purpose: this is the most safety-relevant
rule in the label system (an excluded person must never be messaged), so the
two invariants — exclusion always wins, and an empty filter lets everyone
through so the guard can never become a silent off-switch — are stated once,
next to the code that enforces them.
"""

from __future__ import annotations

from stores.label_rules import normalize_nick


class LabelFilter:
    """Answers `may this person be touched?`, with the reason."""

    def __init__(self, owner) -> None:
        self._owner = owner

    def filter(self) -> dict:
        return self._owner._normalized()["filter"]

    def set_filter(self, include=None, exclude=None) -> dict:
        data = self._owner._normalized()
        known = {d["id"] for d in data["defs"]}
        inc = list(dict.fromkeys(str(i) for i in (include or []) if str(i) in known))
        exc = list(dict.fromkeys(str(i) for i in (exclude or []) if str(i) in known))
        inc = [i for i in inc if i not in exc]
        data["filter"] = {"include": inc, "exclude": exc}
        self._owner._save(data)
        return dict(data["filter"])

    def clear_filter(self) -> dict:
        return self.set_filter([], [])

    def allows(self, nick) -> bool:
        """Does this person pass the label filter?

        Exclusion always wins; a non-empty include set behaves as a
        whitelist. With no filter configured everyone passes, so the guard
        can never become a silent off-switch (AGENT_RULES RULE 9).
        """
        data = self._owner._normalized()
        rule = data["filter"]
        if not rule["include"] and not rule["exclude"]:
            return True
        mine = set(data["assign"].get(normalize_nick(nick), []))
        if mine & set(rule["exclude"]):
            return False
        if rule["include"]:
            return bool(mine & set(rule["include"]))
        return True

    def reject_reason(self, nick) -> str:
        """Why `allows()` said no (for the log line), or ''."""
        data = self._owner._normalized()
        rule = data["filter"]
        index = {d["id"]: d["name"] for d in data["defs"]}
        mine = set(data["assign"].get(normalize_nick(nick), []))
        hit = mine & set(rule["exclude"])
        if hit:
            return "labelled " + ", ".join(sorted(index.get(i, i) for i in hit))
        if rule["include"] and not (mine & set(rule["include"])):
            return ("missing label " +
                    ", ".join(sorted(index.get(i, i) for i in rule["include"])))
        return ""
