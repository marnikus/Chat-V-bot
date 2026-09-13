"""Judging each rendered person against the filter.

`JudgeMixin` owns the three verdicts a person can receive — a seek *looks*, a
stranger is *rejected-and-purged*, a match is *confirmed and announced*. What
every mode shares is the counting of NEWLY RENDERED people (done in
`_consume_batch`), which is what the stall detector feeds on.
"""

from .runstate import _Pass


class JudgeMixin:
    # ── phase 2: judge everybody the viewport is showing ─────────
    async def _consume_batch(self, run: _Pass) -> None:
        """One viewport's worth of people.

        The three modes are separate methods now (design doc §4): a seek only
        looks, a stranger is rejected-and-purged, a match is confirmed and
        announced. What every mode shares is the counting of NEWLY RENDERED
        people — that is what the stall detector below feeds on, and a seek
        that stopped counting would stall out before reaching its target.
        """
        for item in (run.snap or {}).get("users", []) or []:
            nick = (item.get("nick") or "").strip()
            if not nick:
                continue
            is_new = nick not in self.known_nicks
            if is_new:
                self.known_nicks.add(nick)
                run.new_this_scroll += 1
            if run.seeking:
                if await self._seek_hit(nick, item, run):
                    return
                continue
            if not is_new:
                continue
            await self._judge(nick, item, run)

    async def _seek_hit(self, nick: str, item: dict, run: _Pass) -> bool:
        """Scroll-only mode: is this the person we are hunting for?

        A target is by definition ALREADY known, so the `known_nicks`
        short-circuit in the caller would skip exactly the people we are after
        — membership is tested instead. And a target that does not pass the
        filter is passed over, never purged: it is not being judged for
        membership, only for suitability right now.
        """
        if nick not in run.seek_nicks:
            return False
        verdict = run.person_filter.check(self._to_dict(item))
        if not verdict.passed:
            self._say(f"  ↷ “{nick}” is waiting but does not pass "
                      f"the filter ({verdict.reason}) — skipping", "info")
            run.seek_nicks = run.seek_nicks - {nick}
            return False
        record = self._to_record(item)
        record.messaged = False
        shown = await self._confirm_person(nick)
        self._say(f"  🎯 Found “{nick}” on the page — {verdict.reason}"
                  + (" — outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)
        run.result.found = record
        run.result.collected.append(record)
        run.result.all_people.append(record)
        return True

    async def _judge(self, nick: str, item: dict, run: _Pass) -> None:
        """Every person the page showed us is REPORTED, whoever passes.

        `all_people` is the run's "seen" list — the log summary, the queue
        builder and the debugger table all read it, so a rejected person has
        to be in it too.
        """
        record = self._to_record(item)
        run.result.all_people.append(record)
        verdict = run.person_filter.check(self._to_dict(item))
        if not verdict.passed:
            await self._reject_one(record, verdict.reason, run)
            return
        if nick in run.collected_nicks:              # belt and braces
            return
        await self._collect_one(record, nick, verdict.reason, run)

    async def _reject_one(self, record, reason: str, run: _Pass) -> None:
        run.result.rejected[reason] = run.result.rejected.get(reason, 0) + 1
        # Confirmed NOT to pass: destroy any stored record so the
        # person cannot survive from an earlier / laxer run.
        await self._notify_rejected(record, reason, run.result)

    async def _collect_one(self, record, nick: str, reason: str,
                           run: _Pass) -> None:
        result = run.result
        # Visual confirmation BEFORE adding: show the user exactly
        # which person was detected, then hold so it can be seen.
        shown = await self._confirm_person(nick)
        self._say(f"  🟢 Match “{nick}” — {reason}"
                  + (" — green outline drawn" if shown else ""), "success")
        await self._hold_confirmation(shown)

        run.collected_nicks.add(nick)
        record.messaged = nick in run.known_messaged
        result.collected.append(record)
        self._say(f"  ✅ Added “{nick}” to the list "
                  f"({len(result.collected)} collected)", "success")
        # Refresh the UI immediately — do not wait for the scroll
        # cycle to finish.
        await self._notify_collected(record, result)
