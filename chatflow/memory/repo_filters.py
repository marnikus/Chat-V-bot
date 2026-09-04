"""Filter rule persistence (main thread)."""
from __future__ import annotations

from ..core.models import FilterRule
from .db import Database


class FilterRuleRepo:
    def __init__(self, db: Database):
        self._db = db

    def list(self) -> list[FilterRule]:
        rows = self._db.query(
            "SELECT rule_id, type, selector, value, enabled, position "
            "FROM filter_rules ORDER BY position, id")
        return [FilterRule(r["rule_id"], r["type"], r["selector"],
                           r["value"], bool(r["enabled"]), r["position"]) for r in rows]

    def save(self, rule: FilterRule) -> None:
        self._db.execute(
            "INSERT INTO filter_rules(rule_id, type, selector, value, enabled, position) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(rule_id) DO UPDATE SET type=excluded.type, "
            "selector=excluded.selector, value=excluded.value, "
            "enabled=excluded.enabled, position=excluded.position",
            (rule.rule_id, rule.type, rule.selector, rule.value,
             int(rule.enabled), rule.position))

    def delete(self, rule_id: str) -> None:
        self._db.execute("DELETE FROM filter_rules WHERE rule_id=?", (rule_id,))

    def seed_defaults(self) -> None:
        if self._db.query("SELECT COUNT(*) c FROM filter_rules")[0]["c"]:
            return
        from ..filters.engine import default_rules
        for i, rule in enumerate(default_rules()):
            self.save(rule)
