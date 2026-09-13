"""Deciding what happens to each person the viewport is showing.

Owns the `Judge` collaborator: one viewport's worth of people, and the three
mutually exclusive modes a person can meet —

  * **seek** — only looks. Never writes, never purges (RULE 11).
  * **reject** — fails the filter, so any stored record is destroyed (RULE 6).
  * **collect** — passes, is confirmed on screen, then announced (RULE 5).

What every mode shares is the counting of NEWLY RENDERED people: that is what
the stall detector feeds on, and a seek that stopped counting would stall out
before reaching its target (RULE 11).

Host protocol: reads `host.options`, `host.known_nicks`, `host._say()`,
`host.viewport` and the two notify hooks `host._notify_collected/_rejected`.
"""

import asyncio
import logging

from backend.scroll_parser.probe import to_dict, to_record

log = logging.getLogger("chatbot")


class Judge:
    """Per-person verdicts for one scroll pass."""

    def __init__(self, host):
        self.p = host

    async def consume_batch(self, run) -> None:
        """One viewport's worth of people.

        The three modes are separate methods: a seek only looks, a stranger is
        rejected-and-purged, a match is confirmed and announced.
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
                if await self._seek_hit(nick, item, run):
                    return
                continue
            if not is_new:
                continue
            await self._judge(nick, item, run)

    async def _seek_hit(self, nick: str, item: dict, run) -> bool:
        """Scroll-only mode: is this the person we are hunting for?

        A target is by definition ALREADY known, so the `known_nicks`
        short-circuit in the caller would skip exactly the people we are after
        — membership is tested instead. And a target that does not pass the
        filter is passed over, never purged: it is not being judged for
        membership, only for suitability right now.
        """
        if nick not in run.seek_nicks:
            return False
        verdict = run.person_filter.check(to_dict(item))
        if not verdict.passed:
            self.p._say(f"  ↷ “{nick}” is waiting but does not pass "
                        f"the filter ({verdict.reason}) — skipping", "info")
            run.seek_nicks = run.seek_nicks - {nick}
            return False
        record = to_record(item)
        record.messaged = False
        shown = await self.p.viewport.confirm_person(nick)
        self.p._say(f"  🎯 Found “{nick}” on the page — {verdict.reason}"
                    + (" — outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)
        run.result.found = record
        run.result.collected.append(record)
        run.result.all_people.append(record)
        return True

    async def _judge(self, nick: str, item: dict, run) -> None:
        """Every person the page showed us is REPORTED, whoever passes.

        `all_people` is the run's "seen" list — the log summary, the queue
        builder and the debugger table all read it, so a rejected person has
        to be in it too.
        """
        record = to_record(item)
        run.result.all_people.append(record)
        verdict = run.person_filter.check(to_dict(item))
        if not verdict.passed:
            await self._reject_one(record, verdict.reason, run)
            return
        if nick in run.collected_nicks:              # belt and braces
            return
        await self._collect_one(record, nick, verdict.reason, run)

    async def _reject_one(self, record, reason: str, run) -> None:
        run.result.rejected[reason] = run.result.rejected.get(reason, 0) + 1
        # Confirmed NOT to pass: destroy any stored record so the
        # person cannot survive from an earlier / laxer run.
        await self.p._notify_rejected(record, reason, run.result)

    async def _collect_one(self, record, nick: str, reason: str, run) -> None:
        result = run.result
        # Visual confirmation BEFORE adding: show the user exactly
        # which person was detected, then hold so it can be seen.
        shown = await self.p.viewport.confirm_person(nick)
        self.p._say(f"  🟢 Match “{nick}” — {reason}"
                    + (" — green outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)

        run.collected_nicks.add(nick)
        record.messaged = nick in run.known_messaged
        result.collected.append(record)
        self.p._say(f"  ✅ Added “{nick}” to the list "
                    f"({len(result.collected)} collected)", "success")
        # Refresh the UI immediately — do not wait for the scroll
        # cycle to finish.
        await self.p._notify_collected(record, result)

    async def _hold_confirmation(self, shown: bool) -> None:
        if shown and self.p.options.confirm_pause_ms:
            await asyncio.sleep(self.p.options.seconds("confirm_pause_ms"))
