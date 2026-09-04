"""Criteria / filter engine for user evaluation."""

import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import aiosqlite

log = logging.getLogger("chatbot")

_DEFAULT_CRITERIA = [
    {"label": "Must be female", "enabled": True, "selector": ".avatar-wrapper",
     "class_name": "female-avatar", "check_type": "MUST_HAVE_CLASS"},
    {"label": "Must NOT be registered", "enabled": True, "selector": ".badge",
     "class_name": "registered-badge", "check_type": "MUST_NOT_HAVE_CLASS"},
    {"label": "Must be guest", "enabled": False, "selector": ".avatar-wrapper",
     "class_name": "guest-avatar", "check_type": "MUST_HAVE_CLASS"},
    {"label": "Must NOT be anonymous", "enabled": False, "selector": ".badge",
     "class_name": "anonymous-badge", "check_type": "MUST_NOT_HAVE_CLASS"},
]


@dataclass
class Criterion:
    """Single filter rule."""
    label: str
    enabled: bool
    selector: str
    class_name: str
    check_type: str  # MUST_HAVE_CLASS | MUST_NOT_HAVE_CLASS


class CriteriaEngine:
    """Load, evaluate, and persist user criteria."""

    def __init__(self):
        self.criteria: list[Criterion] = [
            Criterion(**c) for c in _DEFAULT_CRITERIA
        ]

    def load_json(self, data: str) -> None:
        try:
            items = json.loads(data)
            self.criteria = [Criterion(**c) for c in items]
            log.info("Criteria loaded: %d rules", len(self.criteria))
        except Exception as exc:
            log.error("Criteria load error: %s", exc)

    def to_json(self) -> str:
        return json.dumps([asdict(c) for c in self.criteria], ensure_ascii=False)

    def evaluate_user(self, user_data: dict) -> bool:
        """Evaluate a user dict (nick, gender, registered, anonymous, guest)
        against all enabled criteria. Returns True if user passes."""
        for c in self.criteria:
            if not c.enabled:
                continue
            if c.check_type == "MUST_HAVE_CLASS":
                if not self._user_has_class(user_data, c.class_name):
                    return False
            elif c.check_type == "MUST_NOT_HAVE_CLASS":
                if self._user_has_class(user_data, c.class_name):
                    return False
        return True

    def filter_users(self, users: list[dict]) -> list[dict]:
        """Return only users passing all enabled criteria."""
        return [u for u in users if self.evaluate_user(u)]

    async def save_to_db(self, db: aiosqlite.Connection, name: str = "default") -> None:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS criteria "
            "(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, "
            "criteria TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
        )
        await db.execute(
            "INSERT OR REPLACE INTO criteria (name, criteria) VALUES (?,?)",
            (name, self.to_json()),
        )
        await db.commit()

    async def load_from_db(self, db: aiosqlite.Connection, name: str = "default") -> bool:
        cur = await db.execute(
            "SELECT criteria FROM criteria WHERE name=?", (name,)
        )
        row = await cur.fetchone()
        if row:
            self.load_json(row[0])
            return True
        return False

    @staticmethod
    def _user_has_class(user_data: dict, class_name: str) -> bool:
        mapping = {
            "female-avatar": "female",
            "male-avatar": "male",
            "guest-avatar": "guest",
            "registered-badge": "registered",
            "anonymous-badge": "anonymous",
        }
        attr = mapping.get(class_name, "")
        return bool(user_data.get(attr, False))
