"""Core dataclasses and enums shared across the app (pure Python)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid.uuid4())


class Gender(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    UNKNOWN = "UNKNOWN"


class UserStatus(str, Enum):
    NEW = "NEW"
    QUEUED = "QUEUED"
    MESSAGED = "MESSAGED"
    SKIPPED = "SKIPPED"


class RuleType(str, Enum):
    CLASS_INCLUDES = "CLASS_INCLUDES"
    CLASS_EXCLUDES = "CLASS_EXCLUDES"
    REGEX_MATCH = "REGEX_MATCH"
    REGEX_NOT_MATCH = "REGEX_NOT_MATCH"


class EngineState(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"


@dataclass
class UserRow:
    """Raw DOM extraction result (not persisted)."""
    nickname: str
    gender: str = Gender.UNKNOWN.value
    registered: bool = False
    is_guest: bool = False
    classes: frozenset = frozenset()


@dataclass
class UserRecord:
    id: int
    nickname: str
    gender: str
    registered: bool
    status: str
    skip_reason: str | None
    first_seen: str
    last_seen: str
    messaged_at: str | None
    message_count: int
    notes: str

    @classmethod
    def from_row(cls, r) -> "UserRecord":
        return cls(r["id"], r["nickname"], r["gender"], bool(r["registered"]),
                   r["status"], r["skip_reason"], r["first_seen"], r["last_seen"],
                   r["messaged_at"], r["message_count"], r["notes"] or "")

    def to_dict(self) -> dict:
        return {"id": self.id, "nickname": self.nickname, "gender": self.gender,
                "registered": self.registered, "status": self.status,
                "skip_reason": self.skip_reason, "first_seen": self.first_seen,
                "last_seen": self.last_seen, "messaged_at": self.messaged_at,
                "message_count": self.message_count, "notes": self.notes}


@dataclass
class FilterRule:
    rule_id: str
    type: str
    selector: str
    value: str
    enabled: bool = True
    position: int = 0

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "type": self.type, "selector": self.selector,
                "value": self.value, "enabled": self.enabled, "position": self.position}

    @classmethod
    def from_dict(cls, d: dict) -> "FilterRule":
        return cls(d.get("rule_id") or new_id(), d.get("type", "CLASS_INCLUDES"),
                   d.get("selector", ""), d.get("value", ""),
                   bool(d.get("enabled", True)), int(d.get("position", 0)))


@dataclass
class Block:
    block_id: str
    action_type: str
    params: dict = field(default_factory=dict)
    delay_after: float = 1.0
    enabled: bool = True
    position: int = 0

    def to_dict(self) -> dict:
        return {"block_id": self.block_id, "action_type": self.action_type,
                "params": dict(self.params), "delay_after": self.delay_after,
                "enabled": self.enabled, "position": self.position}

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(d.get("block_id") or new_id(), d.get("action_type", "wait"),
                   dict(d.get("params") or {}), float(d.get("delay_after", 1.0)),
                   bool(d.get("enabled", True)), int(d.get("position", 0)))


@dataclass
class Preset:
    name: str
    description: str
    blocks: list[Block] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
