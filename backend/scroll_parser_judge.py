"""Per-person decisions of one scroll-parse run.

Part of the `scroll_parser_*` family (facade and family map:
`backend/scroll_parser.py`). A seek only looks, a stranger is
rejected-and-purged, a match is confirmed and announced — plus the two
callbacks that keep the UI and the store in step with the run.
"""

from __future__ import annotations

import asyncio
import logging

from backend.scroll_parser_dom import _to_dict, _to_record
from backend.scroll_parser_model import PassState

log = logging.getLogger("chatbot")


class PersonJudge:
    """The judgement half of one parser: filter verdicts and their effects.

    Holds the facade and reads its `options` / `known_nicks` / callbacks
    **live** — the callback setters replace the frozen options object.
    """

    def __init__(self, parser):
        self.p = parser

    async def consume_batch(self, run: PassState) -> None:
        """One viewport's worth of people.

        The three modes are separate methods now (design doc §4): a seek only
        looks, a stranger is rejected-and-purged, a match is confirmed and
        announced. What every mode shares is the counting of NEWLY RENDERED
        people — that is what the stall detector feeds on, and a seek that
        stopped counting would stall out before reaching its target.
        """
        for item in (run.snap or {}).get("users", []) or []:
            nick = (item.get("nick") or "").strip()
            if not nick:
                continue
            is_new = nick not in self.p.known_nicks
            if is_new:
                self.p.known_nicks.add(nick)
                run.new_this_scroll += 1
            if run.seeking:
                if await self.seek_hit(nick, item, run):
                    return
                continue
            if not is_new:
                continue
            await self.judge(nick, item, run)

    async def seek_hit(self, nick: str, item: dict, run: PassState) -> bool:
        """Scroll-only mode: is this the person we are hunting for?

        A target is by definition ALREADY known, so the `known_nicks`
        short-circuit in the caller would skip exactly the people we are after
        — membership is tested instead. And a target that does not pass the
        filter is passed over, never purged: it is not being judged for
        membership, only for suitability right now.
        """
        if nick not in run.seek_nicks:
            return False
        verdict = run.person_filter.check(_to_dict(item))
        if not verdict.passed:
            self.p._say(f"  ↷ “{nick}” is waiting but does not pass "
                        f"the filter ({verdict.reason}) — skipping", "info")
            run.seek_nicks = run.seek_nicks - {nick}
            return False
        record = _to_record(item)
        record.messaged = False
        shown = await self.p._dom.confirm_person(nick)
        self.p._say(f"  🎯 Found “{nick}” on the page — {verdict.reason}"
                    + (" — outline drawn" if shown else ""), "success")
        await self.hold_confirmation(shown)
        run.result.found = record
        run.result.collected.append(record)
        run.result.all_people.append(record)
        return True

    async def judge(self, nick: str, item: dict, run: PassState) -> None:
        """Every person the page showed us is REPORTED, whoever passes.

        `all_people` is the run's "seen" list — the log summary, the queue
        builder and the debugger table all read it, so a rejected person has
        to be in it too.
        """
        record = _to_record(item)
        run.result.all_people.append(record)
        verdict = run.person_filter.check(_to_dict(item))
        if not verdict.passed:
            await self.reject_one(record, verdict.reason, run)
            return
        if nick in run.collected_nicks:              # belt and braces
            return
        await self.collect_one(record, nick, verdict.reason, run)

    async def reject_one(self, record, reason: str, run: PassState) -> None:
        run.result.rejected[reason] = run.result.rejected.get(reason, 0) + 1
        # Confirmed NOT to pass: destroy any stored record so the
        # person cannot survive from an earlier / laxer run.
        await self.notify_rejected(record, reason, run.result)

    async def collect_one(self, record, nick: str, reason: str,
                          run: PassState) -> None:
        result = run.result
        # Visual confirmation BEFORE adding: show the user exactly
        # which person was detected, then hold so it can be seen.
        shown = await self.p._dom.confirm_person(nick)
        self.p._say(f"  🟢 Match “{nick}” — {reason}"
                    + (" — green outline drawn" if shown else ""), "success")
        await self.hold_confirmation(shown)

        run.collected_nicks.add(nick)
        record.messaged = nick in run.known_messaged
        result.collected.append(record)
        self.p._say(f"  ✅ Added “{nick}” to the list "
                    f"({len(result.collected)} collected)", "success")
        # Refresh the UI immediately — do not wait for the scroll
        # cycle to finish.
        await self.notify_collected(record, result)

    async def hold_confirmation(self, shown: bool) -> None:
        if shown and self.p.options.confirm_pause_ms:
            await asyncio.sleep(self.p.options.seconds("confirm_pause_ms"))

    async def notify_collected(self, record, result) -> None:
        """Tell the caller a person was added, so the UI can refresh now."""
        callback = self.p._on_collect
        if callback is None:
            return
        try:
            outcome = callback(record, list(result.collected))
            if asyncio.iscoroutine(outcome):
                await outcome
        except Exception as exc:      # a UI hiccup must never kill the parse
            log.warning("on_collect callback failed for %s: %s",
                        record.nick, exc)

    async def notify_rejected(self, record, reason: str, result) -> None:
        """Tell the caller a person FAILED the filter.

        The caller destroys any stored record for them, so a person who does
        not pass the filter can never linger in the list from an earlier run.
        """
        result.rejected_people.append((record, reason))
        callback = self.p._on_reject
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
