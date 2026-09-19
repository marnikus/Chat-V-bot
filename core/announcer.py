"""Outcome-based reporting; only synchronous labels may announce intent."""
from core.events import LogMessage

INTENT_ONLY = ("labels",)


def confirmed(result) -> bool:
    return isinstance(result, dict) and bool(result.get("ok"))


class Announcer:
    def __init__(self, bus):
        self.bus = bus

    def report(self, kind: str, result, message: str) -> bool:
        if kind not in INTENT_ONLY and not confirmed(result):
            return False
        self.bus.emit(LogMessage(message=message, level="success"))
        return True

    def report_intent(self, kind: str, forward: bool, label: str) -> bool:
        if kind not in INTENT_ONLY:
            return False
        prefix = "↪ Redo" if forward else "↩ Undo"
        self.bus.emit(LogMessage(message=f"{prefix} — {label}", level="info"))
        return True
