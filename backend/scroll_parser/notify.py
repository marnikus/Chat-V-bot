"""Telling the outside world what the run is doing.

`NotifyMixin` owns the two outbound seams every phase relies on: the log/stop
seam (`_say`, `_stop_requested`, `set_log_cb`) and the collection/rejection
callbacks (`_notify_collected`, `_notify_rejected`). Neither decides anything
about the run — they only report and, for the callbacks, let the caller react
without ever letting a caller error kill the parse.
"""

import asyncio
import logging

log = logging.getLogger("chatbot")


class NotifyMixin:
    # ── logging ──────────────────────────────────────────────────
    def set_log_cb(self, cb) -> None:
        """Optional (message, level) callback for debugger log lines."""
        self._log_cb = cb

    def _say(self, message: str, level: str = "info") -> None:
        if self._log_cb:
            try:
                self._log_cb(message, level)
            except Exception:
                pass
        log.log(getattr(logging, level.upper(), logging.INFO)
                if level else logging.INFO, "%s", message)

    async def _notify_collected(self, record, result) -> None:
        """Tell the caller a person was added, so the UI can refresh now."""
        callback = self._on_collect
        if callback is None:
            return
        try:
            outcome = callback(record, list(result.collected))
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception as exc:      # a UI hiccup must never kill the parse
            log.warning("on_collect callback failed for %s: %s",
                        record.nick, exc)

    async def _notify_rejected(self, record, reason: str, result) -> None:
        """Tell the caller a person FAILED the filter.

        The caller destroys any stored record for them, so a person who does
        not pass the filter can never linger in the list from an earlier run.
        """
        result.rejected_people.append((record, reason))
        callback = self._on_reject
        if callback is None:
            return
        try:
            outcome = callback(record, reason)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            if outcome:
                result.purged.append(record.nick)
        except Exception as exc:      # a purge hiccup must never kill the parse
            log.warning("on_reject callback failed for %s: %s",
                        record.nick, exc)

    def _stop_requested(self) -> bool:
        predicate = self._should_stop
        if predicate is None:
            return False
        try:
            return bool(predicate())
        except Exception:
            return False
