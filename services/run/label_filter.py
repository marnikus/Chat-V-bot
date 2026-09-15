"""Label filtering — part of RunQueueMixin, extracted by responsibility.

H-C1: RunQueueMixin (227 LOC, LCOM 0.94) mixed label filtering, queue ordering,
single-target and take phase. This file owns only label filtering:
`label_allows`, `filter_by_labels`, `_label_reason_for`, `_announce_label_skips`.

Design: docs/archive/2026-09-14-round-h/AREA_C_SERVICES_STORES_DESIGN_2026-09-14.md H-C1
"""

from __future__ import annotations

import logging

log = logging.getLogger("chatbot")


class LabelFilterMixin:
    """Label filter half — fail-open, announces first few skips."""

    def label_allows(self, nick) -> bool:
        if not callable(getattr(self, "label_filter", None)):
            return True
        try:
            return bool(self.label_filter(nick))
        except Exception as exc:
            log.warning("label filter failed for %r: %s", nick, exc)
            return True

    def filter_by_labels(self, users: list, announce: bool = False) -> list:
        if not callable(getattr(self, "label_filter", None)):
            return list(users or [])
        kept, skipped = [], []
        for user in users or []:
            nick = getattr(user, "nick", user)
            if self.label_allows(nick):
                kept.append(user)
            else:
                skipped.append(str(nick))
        if skipped and announce:
            self._announce_label_skips(skipped)
        return kept

    def _label_reason_for(self, nick) -> str:
        """Why the label filter rejected one nick (fail-open to no reason)."""
        if not callable(getattr(self, "label_reason", None)):
            return ""
        try:
            return str(self.label_reason(nick) or "")
        except Exception:
            return ""

    def _announce_label_skips(self, skipped: list) -> None:
        """One info line naming the first few rejected people (+N more)."""
        samples = []
        for nick in skipped[:5]:
            why = self._label_reason_for(nick)
            samples.append(f"{nick}{f' ({why})' if why else ''}")
        more = (
            f" +{len(skipped) - len(samples)} more"
            if len(skipped) > len(samples)
            else ""
        )
        self.debug_msg.emit(
            f"🏷 Label filter skipped {len(skipped)} person(s): "
            + ", ".join(samples)
            + more,
            "info",
        )
