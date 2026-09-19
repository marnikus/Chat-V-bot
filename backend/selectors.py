"""Fixed collector/scroll selectors, with a checked standalone JS mirror.

Area A seam #3: this registry owns the listed subset, not arbitrary user
selectors or every selector in the application. A parity test pins the agent
and documentation; synthetic DOM approvals detect regressions, not live drift.
"""
from __future__ import annotations

import json
import re
from types import MappingProxyType

SELECTORS = MappingProxyType({
    "active_tab": ".tab-item.active",
    "tab_type_icon": "mat-icon.chat-type-icon",
    "tab_icon_any": "mat-icon",
    "tab_title": "p.chat-title",
    "user_item": "user-item",
    "user_nick": ".primary-text",
    "my_user_row": ".primary-text.bold",
    "users_counter": ".users-counter",
    "avatar_wrapper": ".avatar-wrapper",
    "user_badge": ".badge",
    "messages_pane": "app-messages",
    "messages_root": ".messages-root",
    "message_node": "div.message-container",
    "message_body": "p.message",
    "message_from": "span.from",
    "message_text": "span.message",
    "message_image": "app-chat-image img",
    "image_any": "img",
    "sent_time": "span.sent-time",
    "sent_time_any": ".sent-time",
})
JS_BEGIN = "/*CVB_SELECTORS_BEGIN*/"
JS_END = "/*CVB_SELECTORS_END*/"
_MIRROR = re.compile(re.escape(JS_BEGIN) + r"\s*var SEL = (\{.*?\});\s*"
                     + re.escape(JS_END), re.S)


def selector(name: str) -> str:
    """Look up a fixed selector; unknown names are programming errors."""
    return SELECTORS[name]


def js_literal(name: str) -> str:
    """JSON-quoted selector for a Python-generated JavaScript probe."""
    return json.dumps(SELECTORS[name], ensure_ascii=False)


def js_literals() -> dict[str, str]:
    """The named substitutions for a probe template."""
    return {name: js_literal(name) for name in SELECTORS}


def mirror_block() -> str:
    """Canonical standalone JavaScript registry block."""
    body = json.dumps(dict(SELECTORS), ensure_ascii=False, indent=4)
    return f"{JS_BEGIN}\n  var SEL = {body};\n  {JS_END}"


def parse_mirror(agent_source: str) -> dict[str, str] | None:
    """Read the mirror, returning None for missing or malformed JSON."""
    match = _MIRROR.search(agent_source)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None
