"""Qt-free validation and compatibility projections of the global timeline."""
import json

from services.layout_service import LayoutService


def global_payload(kind: str, raw: str) -> tuple:
    if kind == "stack":
        try:
            value = json.loads(raw or "[]")
        except json.JSONDecodeError:
            return False, None
        return isinstance(value, list), value
    if kind == "grid":
        value, error = LayoutService.canonical_grid_payload(raw or "")
        return not error, value
    return False, None


def kind_value(raw: str, kind: str) -> str:
    try:
        entry = json.loads(raw)
        if not isinstance(entry, dict) or entry.get("kind") != kind:
            return "null"
        if kind == "grid":
            return LayoutService.legacy_grid_payload(entry.get("value", "null"))
        return json.dumps(entry["value"], ensure_ascii=False)
    except (TypeError, KeyError, json.JSONDecodeError):
        return "null"


def list_arg(raw: str) -> list | None:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def trim_history(history: list, index, cap: int) -> tuple:
    if not isinstance(index, int):
        index = -1
    if len(history) > cap:
        overflow = len(history) - cap
        return history[overflow:], max(0, index - overflow)
    return history, index
