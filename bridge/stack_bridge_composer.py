"""Stack bridge composer — extracted from stack_bridge_parts (H-C5 split)

Composer draft and criteria, ≤80 LOC.
"""

from __future__ import annotations

import logging

from bridge.stack_bridge_run import _Part

log = logging.getLogger("chatbot")


class Composer(_Part):
    def __init__(self, host):
        super().__init__(host)
        self._message_text = ""

    def save_message(self, text) -> None:
        self._message_text = text
        try:
            self._ctx.engine.composer_text = text
        except Exception:
            pass

    def get_message(self) -> str:
        return self._message_text

    def save_criteria(self, j) -> None:
        self._ctx.criteria.load_json(j)
        self._log("💾 Criteria saved", "info")

    def get_criteria(self) -> str:
        return self._ctx.criteria.to_json()
