"""JSON helpers for the bridge."""
from __future__ import annotations

import json


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def jload(payload: str) -> dict:
    try:
        data = json.loads(payload or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
