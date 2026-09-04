"""Bridge slots: sequence presets and filter rules."""
from __future__ import annotations

from PySide6.QtCore import Slot

from ..core.models import FilterRule
from .util import jdump, jload


class PresetSlots:
    @Slot(str, result=str)
    def getPresets(self, _p: str = "{}") -> str:
        return jdump({"presets": self.sv.presets.list()})

    @Slot(str, result=str)
    def getPreset(self, payload: str = "{}") -> str:
        name = jload(payload).get("name", "")
        return jdump(self.sv.presets.get(name) or {})

    @Slot(str, result=str)
    def savePreset(self, payload: str = "{}") -> str:
        f = jload(payload)
        return jdump(self.sv.presets.save(f.get("name", "Default"),
                                          f.get("description", ""),
                                          f.get("blocks", [])))

    @Slot(str, result=str)
    def deletePreset(self, payload: str = "{}") -> str:
        return jdump(self.sv.presets.delete(jload(payload).get("name", "")))


class RuleSlots:
    @Slot(str, result=str)
    def getRules(self, _p: str = "{}") -> str:
        return jdump({"rules": [r.to_dict() for r in self.sv.filters.list()]})

    @Slot(str, result=str)
    def saveRule(self, payload: str = "{}") -> str:
        from ..filters.engine import validate_rule
        rule = FilterRule.from_dict(jload(payload))
        err = validate_rule(rule)
        if err:
            return jdump({"ok": False, "error": err})
        self.sv.filters.save(rule)
        return jdump({"ok": True,
                      "rules": [r.to_dict() for r in self.sv.filters.list()]})

    @Slot(str, result=str)
    def deleteRule(self, payload: str = "{}") -> str:
        self.sv.filters.delete(jload(payload).get("rule_id", ""))
        return jdump({"ok": True,
                      "rules": [r.to_dict() for r in self.sv.filters.list()]})
