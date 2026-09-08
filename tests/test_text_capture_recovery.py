"""Real parser → repo → SQLite recovery tests for blank chat bubbles.

Legacy metadata-only rows are seeded directly through the repository. New
collector writes must defer missing payloads, retry, and preserve ordering when
those lines eventually render. Private-chat and explicit-deletion gates remain
in force while recovering, including when media downloading is off.
"""

import asyncio
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.chat_parser import ChatParser, sync_conversation
from backend.history_models import MessageRecord, fingerprint
from test_chat_parser_delta import raw
from test_db_connection_safety import ME, NICK, NOW, Page, SafetyCase


def conversation(empty=False):
    return [raw("" if empty else text, from_nick=author, direction=direction,
                time=time, idx=i)
            for i, (text, author, direction, time) in enumerate([
                ("Привет, как дела? 😊", NICK, "in", "18:00"),
                ("Хорошо!\nА у тебя?", ME, "out", "18:01"),
                ("Сохрани весь текст <b>как текст</b>", ME, "out", "18:02")])]


class TestTextRecovery(SafetyCase):
    async def legacy(self, records=None, use_live_fingerprints=False):
        live = conversation()
        blanks = records or conversation(empty=True)
        if use_live_fingerprints:
            blanks = [dict(empty, fp=full["fp"]) for empty, full in zip(blanks, live)]
        await self.service.repo.append(NICK, blanks, my_nick=ME, now=NOW,
                                       dom_count=len(blanks), head_sig=blanks[0]["fp"],
                                       tail_sig=blanks[-1]["fp"])
        return await self.contents()

    async def test_unchanged_cursor_does_not_hide_missing_text_with_media_off(self):
        before = await self.legacy(use_live_fingerprints=True)
        self.page.messages = conversation()
        self.service.collector.media = None
        notifications = []
        self.service.collector.history_appended.connect(lambda p: notifications.append(json.loads(p)))
        await self.service.collector.tick()
        rows = await self.contents()
        self.assertEqual(len(rows), 3)
        for old, row, source in zip(before, rows, self.page.messages):
            self.assertEqual(row["text"], source["text"])
            self.assertEqual(row["text_lc"], source["text"].lower())
            for field in ("id", "ord", "person_id", "from_nick", "my_nick", "day",
                          "ts_display", "ts_resolved", "session_id", "created_at", "media_id"):
                self.assertEqual(row[field], old[field], field)
            self.assertTrue(row["text_recovered_at"])
        self.assertEqual(self.service.collector.state_payload()["text_repaired"], 3)
        self.assertTrue(notifications[-1]["refresh"], "repair-only updates must refresh existing bubbles")
        self.assertEqual(notifications[-1]["added"], 0)
        if self.service.db.fts_enabled:
            result = await self.service.query.search_person(NICK, "Привет")
            self.assertEqual(len(result["items"]), 1, "FTS must index the repaired text")
        before_reads = len(self.page.slice_calls)
        await self.service.collector.tick()
        self.assertEqual(len(self.page.slice_calls), before_reads, "fully captured idle chat stays cheap")
        self.assertEqual(len(await self.contents()), 3)

    async def test_manual_backfill_reextracts_blank_text_in_place(self):
        self.page.messages = conversation()
        await self.service.collector.tick()
        originals = await self.contents()
        await self.service.db.execute("UPDATE messages SET text='', text_lc=''")
        await self.service.db.commit()
        await self.service.collector.backfill_older()
        rows = await self.contents()
        self.assertEqual([r["id"] for r in rows], [r["id"] for r in originals])
        self.assertEqual([r["text"] for r in rows], [r["text"] for r in originals])
        self.assertEqual(self.service.collector.state_payload()["text_repaired"], 3)

    async def test_repair_works_after_independent_database_creation(self):
        await self.legacy()
        old = self.service.db
        await self.make("new")
        self.page.messages = conversation()
        await self.service.collector.tick()
        self.assertIs(self.service.db, old)
        self.assertEqual([r["text"] for r in await self.contents()], [r["text"] for r in conversation()])
        await self.manager.load(str(Path(self.root) / "new.db"))
        self.assertEqual(await self.contents(), [])
        await self.service.collector.tick()
        self.assertEqual([r["text"] for r in await self.contents()], [r["text"] for r in conversation()])
        await self.manager.load(self.path)
        self.assertEqual(len(await self.contents()), 3)

    async def test_transient_text_extraction_retries_before_saving(self):
        class LatePage(Page):
            async def evaluate(page, expression):
                response = await super().evaluate(expression)
                if "/*CVB_SLICE*/" in expression and len(page.slice_calls) == 1:
                    data = json.loads(response)
                    items = data["items"] if isinstance(data, dict) else data
                    items[0] = dict(items[0], text="", capture_pending=True)
                    return json.dumps(data)
                return response
        page = LatePage(conversation(), partner=NICK, me=ME)
        parser = ChatParser(page, chunk_pause_ms=0)
        result = await sync_conversation(parser, self.service.repo, NICK, my_nick=ME,
                                         require_private=True, verify_partner=True, now=NOW)
        self.assertEqual(len(page.slice_calls), 2)
        self.assertEqual(result.capture_missing, 0)
        self.assertEqual(result.added, 3)
        self.assertTrue(all(r["text"] for r in await self.contents()))

    async def test_exhausted_retries_defer_metadata_only_rows_and_leave_cursor_incomplete(self):
        self.page.messages = conversation(empty=True)
        await self.service.collector.tick()
        self.assertEqual(await self.contents(), [], "timestamps alone are not successful captures")
        self.assertEqual(len(self.page.slice_calls), 4)
        pid = await self.service.repo.ensure_person(NICK)
        cursor = await self.service.repo.get_cursor(pid)
        self.assertFalse(cursor["full_scan_complete"])
        self.assertFalse(cursor["tail_sig"])
        self.assertEqual(self.service.collector.state_payload()["capture_missing"], 3)
        self.assertIn("retrying", self.service.collector.state_payload()["warning"])
        self.page.messages = conversation()
        await self.service.collector.tick()
        self.assertEqual(len(await self.contents()), 3)
        self.assertEqual(self.service.collector.state_payload()["capture_missing"], 0)

    async def test_deferred_middle_message_is_inserted_between_its_known_neighbors(self):
        partial = conversation()
        partial[1] = raw("", from_nick=ME, direction="out", time="18:01", idx=1)
        self.page.messages = partial
        await self.service.collector.tick()
        before = await self.contents()
        self.assertEqual([r["text"] for r in before], [conversation()[0]["text"], conversation()[2]["text"]])
        self.page.messages = conversation()
        await self.service.collector.tick()
        rows = await self.contents()
        self.assertEqual([r["text"] for r in rows], [r["text"] for r in conversation()])
        self.assertEqual([r["ord"] for r in rows], [1, 2, 3])
        self.assertEqual((rows[0]["id"], rows[2]["id"]), (before[0]["id"], before[1]["id"]))

    async def test_whitespace_only_text_is_incomplete_but_a_media_only_message_is_valid(self):
        self.page.messages = [raw(" \n\t ", from_nick=NICK, time="18:00"),
                              raw("", from_nick=NICK, kind="gif", time="18:01", idx=1,
                                  media={"url": "https://example.test/a.gif", "kind": "gif"})]
        await self.service.collector.tick()
        rows = await self.contents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "gif")
        self.assertIsNotNone(rows[0]["media_id"])
        self.assertEqual(self.service.collector.state_payload()["capture_missing"], 1)

    async def test_empty_push_is_deferred_and_next_payload_push_saves_full_text(self):
        await self.seed()
        notifications = []
        self.service.collector.history_appended.connect(lambda p: notifications.append(json.loads(p)))
        empty = {"tab": "private", "partner": NICK, "title": NICK,
                 "items": [raw("", from_nick=NICK, time="18:01", idx=1)]}
        self.assertEqual(await self.service.collector.handle_push(empty), 0)
        self.assertEqual(len(await self.contents()), 1)
        full = dict(empty, items=[raw("Полностью получено", from_nick=NICK, time="18:01", idx=1)])
        self.assertEqual(await self.service.collector.handle_push(full), 1)
        self.assertEqual((await self.contents())[-1]["text"], "Полностью получено")
        self.assertEqual(len(await self.contents()), 2)
        self.assertEqual(notifications[-1]["items"][-1]["text"], "Полностью получено")

    async def test_recovery_push_refreshes_instead_of_appending_a_duplicate_bubble(self):
        self.page.messages = conversation()
        await self.service.collector.tick()
        await self.service.db.execute("UPDATE messages SET text='',text_lc='' WHERE ord=2")
        await self.service.db.commit()
        notifications = []
        self.service.collector.history_appended.connect(lambda p: notifications.append(json.loads(p)))
        result = await self.service.collector.handle_push({"tab": "private", "partner": NICK, "title": NICK,
                                                          "items": [conversation()[1]]})
        self.assertEqual(result, 0)
        self.assertEqual(len(await self.contents()), 3)
        self.assertTrue(notifications[-1]["refresh"])
        self.assertEqual((await self.contents())[1]["text"], conversation()[1]["text"])

    async def test_caption_recovery_keeps_the_existing_media_reference(self):
        photo = raw("", from_nick=NICK, kind="gif", time="18:00",
                    media={"url": "https://example.test/a.gif", "kind": "gif"})
        self.page.messages = [photo]
        await self.service.collector.tick()
        before = (await self.contents())[0]
        caption = dict(photo, text="Новая подпись 😊")
        result = await self.service.repo.append(NICK, [caption], now=NOW)
        after = (await self.contents())[0]
        self.assertEqual(result.text_repaired, 1)
        self.assertEqual(result.added, 0)
        self.assertEqual(after["text"], caption["text"])
        self.assertEqual(after["media_id"], before["media_id"])
        self.assertEqual(after["id"], before["id"])

    async def test_text_cannot_steal_a_same_minute_media_slot(self):
        await self.legacy([raw("", from_nick=NICK, time="18:00", idx=0)])
        records = [raw("", from_nick=NICK, kind="gif", time="18:00", idx=0,
                       media={"url": "https://example.test/a.gif", "kind": "gif"}),
                   raw("отдельный текст", from_nick=NICK, time="18:00", idx=1)]
        result = await self.service.repo.append(NICK, records, align=False, now=NOW)
        rows = await self.contents()
        self.assertEqual(result.text_repaired, 0)
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0]["media_id"])
        self.assertEqual(rows[0]["text"], "")
        self.assertEqual(rows[1]["text"], "отдельный текст")

    async def test_two_same_minute_text_slots_are_matched_by_position_not_timestamp_only(self):
        # The old occurrence-based schema could hold two empty slots. The
        # current content deduper intentionally cannot create that fixture.
        before = await self.legacy([raw("", from_nick=NICK, time="18:00", idx=0)])
        second = dict(before[0])
        second.pop("id")
        second.update(ord=2, dom_idx=1, occ=1, dup_key="legacy-empty-2",
                      fp=fingerprint("in", NICK, "18:00", "text", "", 1))
        await self.service.db.execute(
            "INSERT INTO messages(" + ",".join(second) + ") VALUES(" + ",".join("?" for _ in second) + ")",
            second.values())
        await self.service.db.commit()
        records = [raw(text, from_nick=NICK, time="18:00", idx=i)
                   for i, text in enumerate(("первый", "второй"))]
        result = await self.service.repo.append(NICK, records, now=NOW)
        self.assertEqual(result.text_repaired, 2)
        self.assertEqual(result.added, 0)
        self.assertEqual([r["text"] for r in await self.contents()], ["первый", "второй"])

    async def test_backfilled_index_shift_uses_known_neighbors_to_repair_original_slot(self):
        records = conversation()
        blanks = [records[0], dict(records[1], text=""), records[2]]
        before = await self.legacy(blanks)
        older = raw("раньше", from_nick=NICK, time="17:59", idx=0)
        shifted = [older] + [dict(r, idx=i + 1) for i, r in enumerate(records)]
        self.page.messages = shifted
        await self.service.collector.tick()
        rows = await self.contents()
        self.assertEqual([r["text"] for r in rows], [r["text"] for r in shifted])
        self.assertEqual(rows[2]["id"], before[1]["id"])
        self.assertTrue(rows[2]["text_recovered_at"])

    async def test_a_new_day_same_author_and_minute_does_not_fill_yesterdays_slot(self):
        before = await self.legacy([raw("", from_nick=NICK, time="18:00")])
        await self.service.db.execute("UPDATE messages SET day='2026-09-07',ts_resolved='2026-09-07 18:00'")
        await self.service.db.commit()
        result = await self.service.repo.append(NICK, [raw("сегодня", from_nick=NICK, time="18:00")], now=NOW)
        rows = await self.contents()
        self.assertEqual(result.text_repaired, 0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], before[0]["id"])
        self.assertEqual(rows[0]["text"], "")
        self.assertEqual(rows[1]["text"], "сегодня")

    async def test_ambiguous_shifted_slot_keeps_placeholder_instead_of_guessing(self):
        rows = await self.legacy([raw("", from_nick=NICK, time="18:00", idx=10)])
        stats = await self.service.repo.recover_text(rows[0]["person_id"],
                                                   [raw("might be different", from_nick=NICK, time="18:00", idx=0)], now=NOW)
        self.assertEqual(stats["repaired"], 0)
        self.assertEqual((await self.contents())[0]["text"], "")

    async def test_unavailable_text_is_marked_scanned_and_automatic_retry_is_bounded(self):
        before = await self.legacy([raw("", from_nick=NICK, time="10:00")])
        pid = before[0]["person_id"]
        self.page.messages = conversation()
        await self.service.collector.tick()
        self.assertFalse(await self.service.repo.has_missing_text(pid))
        self.assertTrue(await self.service.repo.has_missing_text(pid, force=True), "manual backfill may retry anytime")
        blank = await self.service.db.fetchone("SELECT text,text_scan_at FROM messages WHERE id=?", (before[0]["id"],))
        self.assertEqual(blank["text"], "")
        self.assertTrue(blank["text_scan_at"])

    async def test_explicit_deletion_is_not_undone_when_an_empty_body_later_renders(self):
        before = await self.legacy([raw("", from_nick=NICK, time="18:00")])
        token = await self.service.repo.soft_delete_message(NICK, before[0]["id"])
        result = await self.service.repo.append(NICK, [raw("later body", from_nick=NICK, time="18:00")], now=NOW)
        self.assertEqual(result.text_repaired, 0)
        self.assertEqual(result.added, 0)
        rows = await self.contents()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["deleted_at"], token)
        self.assertEqual(rows[0]["text"], "")
        self.assertEqual((await self.service.query.page(NICK))["items"], [])

    async def test_changed_private_chat_is_refused_during_retry(self):
        class ChangingPage(Page):
            async def evaluate(page, expression):
                answer = await super().evaluate(expression)
                if "/*CVB_SLICE*/" in expression:
                    page.partner = "SomeoneElse"
                return answer
        before = await self.legacy()
        page = ChangingPage(conversation(), partner=NICK, me=ME)
        result = await sync_conversation(ChatParser(page), self.service.repo, NICK,
                                         my_nick=ME, require_private=True, verify_partner=True, now=NOW)
        self.assertFalse(result.ok)
        self.assertEqual([r["text"] for r in await self.contents()], [r["text"] for r in before])

    async def test_third_author_cannot_supply_recovery_text(self):
        before = await self.legacy()
        self.page.messages = [dict(r, **{"from": "Stranger"}) for r in conversation()]
        await self.service.collector.tick()
        self.assertEqual(self.service.collector.state, "group_tab")
        self.assertEqual([r["text"] for r in await self.contents()], [r["text"] for r in before])

    async def test_stop_is_honored_inside_payload_retries(self):
        stopping = {"flag": False}
        class StopPage(Page):
            async def evaluate(page, expression):
                answer = await super().evaluate(expression)
                if "/*CVB_SLICE*/" in expression:
                    stopping["flag"] = True
                return answer
        page = StopPage(conversation(empty=True), partner=NICK, me=ME)
        result = await asyncio.wait_for(sync_conversation(
            ChatParser(page), self.service.repo, NICK, my_nick=ME, now=NOW,
            should_stop=lambda: stopping["flag"]), 1)
        self.assertTrue(result.stopped)
        self.assertEqual(len(page.slice_calls), 1)
        self.assertEqual(await self.contents(), [])

    async def test_unavailable_agent_upgrade_never_saves_with_an_old_parser(self):
        class OldPage(Page):
            async def evaluate(page, expression):
                if "/*CVB_INSTALL*/" in expression:
                    return 0
                result = await super().evaluate(expression)
                if "/*CVB_STATE*/" in expression:
                    data = json.loads(result)
                    data["agent"] = 9
                    return json.dumps(data)
                return result
        page = OldPage(conversation(), partner=NICK, me=ME)
        result = await sync_conversation(ChatParser(page), self.service.repo, NICK, my_nick=ME, now=NOW)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "agent_unavailable")
        self.assertEqual(page.slice_calls, [])
        self.assertEqual(await self.contents(), [])

    async def test_preexisting_empty_plus_real_duplicate_recovers_original_row_once(self):
        before = await self.legacy([raw("", from_nick=NICK, time="18:00")])
        full = MessageRecord.from_dict(raw("один раз", from_nick=NICK, time="18:00"))
        await self.service.db.execute(
            "INSERT INTO messages(person_id,ord,fp,direction,from_nick,text,text_lc,day,ts_display,dom_idx,dup_key) "
            "VALUES(?,2,?,'in',?,?,?,'2026-09-08','18:00',0,?)",
            (before[0]["person_id"], full.fp, NICK, full.text, full.text.lower(), full.dup_key))
        await self.service.db.commit()
        result = await self.service.repo.append(NICK, [full], now=NOW)
        rows = await self.contents()
        self.assertEqual(result.text_repaired, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], before[0]["id"])
        self.assertEqual(rows[0]["text"], full.text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
