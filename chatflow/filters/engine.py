"""Filter rule evaluation (pure, no Playwright). Rules combine with AND."""
from __future__ import annotations

import re

from ..core.models import FilterRule, RuleType, UserRow, new_id


def evaluate(row: UserRow, rules: list[FilterRule]) -> tuple[bool, str | None]:
    """Return (passed, failing_reason). A bad regex fails safe (skip user)."""
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.type == RuleType.CLASS_INCLUDES.value:
            ok = rule.selector in row.classes
        elif rule.type == RuleType.CLASS_EXCLUDES.value:
            ok = rule.selector not in row.classes
        elif rule.type == RuleType.REGEX_MATCH.value:
            ok = _match(rule, row)
        elif rule.type == RuleType.REGEX_NOT_MATCH.value:
            ok = not _match(rule, row)
        else:
            continue
        if not ok:
            label = rule.selector if rule.selector != "nickname" else rule.value
            return False, f"{rule.type}:{label}"
    return True, None


def _match(rule: FilterRule, row: UserRow) -> bool:
    if not rule.value:
        return False
    try:
        return re.search(rule.value, row.nickname) is not None
    except re.error:
        return False


def validate_rule(rule: FilterRule) -> str | None:
    """Return an error message if the rule is invalid, else None."""
    if rule.type in (RuleType.REGEX_MATCH.value, RuleType.REGEX_NOT_MATCH.value):
        if not rule.value:
            return "empty regex"
        try:
            re.compile(rule.value)
        except re.error as e:
            return f"invalid regex: {e}"
    elif rule.type in (RuleType.CLASS_INCLUDES.value, RuleType.CLASS_EXCLUDES.value):
        if not rule.selector:
            return "empty class name"
    else:
        return f"unknown rule type: {rule.type}"
    return None


def default_rules() -> list[FilterRule]:
    """F-FC-01/02: females only, guests only (no registered badge)."""
    return [
        FilterRule(new_id(), RuleType.CLASS_INCLUDES.value,
                   "female-avatar", "", True, 0),
        FilterRule(new_id(), RuleType.CLASS_EXCLUDES.value,
                   "registered-badge", "", True, 1),
    ]
