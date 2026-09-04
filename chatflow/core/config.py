"""Application settings: dataclass + JSON load/save with safe merging."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Settings:
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9222
    tab_url_pattern: str = "virt-chat.com/chat"
    scroll_px: int = 300
    scroll_pause: float = 1.5
    empty_runs: int = 3
    max_scrolls: int = 50
    op_timeout_ms: int = 8000
    jitter: float = 0.3
    typing_cps: int = 60
    typing_var: float = 20.0
    micro_pause_every: int = 5
    micro_pause_sec: float = 30.0
    min_delay_floor: float = 0.2
    db_path: str = "chatflow.db"
    log_dir: str = "logs"
    log_level: str = "INFO"
    retention_days: int = 7
    cooldown_days: int = 30
    msg_max_len: int = 1000
    message: str = "Hi {nick}! How is your {day} going? :)"
    message_pool: str = ""
    image_folder: str = ""
    attach_image: bool = True
    fail_policy: str = "skip_block"  # skip_block | skip_iteration

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        s = cls()
        known = {f.name: f for f in fields(cls)}
        for k, v in (d or {}).items():
            if k not in known or v is None:
                continue
            try:
                setattr(s, k, type(known[k].default)(v) if known[k].default is not None else v)
            except (TypeError, ValueError):
                continue
        return s

    @classmethod
    def load(cls, path: str | Path) -> "Settings":
        p = Path(path)
        if p.exists():
            try:
                return cls.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return cls()

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


def coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
