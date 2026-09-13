"""stores/history_models — validation and value-object edges.

Design refs: docs/archive/2026-09-09-test-suite/STORES_TEST_DESIGN_2026-09-09.md §12 (MDL-01–10).

tests/unit/backend/test_history_models.py pins the JS-parity constants,
UTF-16 astral handling and the basic round-trip. This file pins the
validation contract around it: every identity field matters, the tolerant
int coercion never raises, from_dict() survives hostile agent JSON, and
the result objects stay JSON-safe no matter what they carry.

Run with:  python3 tests/test_history_models_edges.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stores.history_models import (  # noqa: E402
    MAX_LIVE_ITEMS,
    Alignment,
    AppendResult,
    MessageRecord,
    SyncResult,
    _int_or,
    dedupe_key,
    fingerprint,
)


def fp(**kw):
    args = {"direction": "in", "from_nick": "Ann", "ts_display": "10:01",
            "kind": "text", "payload": "hi", "occ": 0}
    args.update(kw)
    return fingerprint(**args)


def dk(**kw):
    args = {"direction": "in", "from_nick": "Ann", "ts_display": "10:01",
            "kind": "text", "payload": "hi"}
    args.update(kw)
    return dedupe_key(**args)


class TestIdentityFields(unittest.TestCase):
    def test_every_identity_field_moves_the_fingerprint(self):  # MDL-01
        base = fp()
        flips = [fp(direction="out"), fp(from_nick="Bob"),
                 fp(ts_display="10:02"), fp(kind="image"),
                 fp(payload="bye"), fp(occ=1)]
        for other in flips:
            self.assertNotEqual(other, base)
        self.assertEqual(len(set(flips)), len(flips))

    def test_dedupe_key_ignores_only_occ(self):  # MDL-02
        base = dk()
        for other in (dk(direction="out"), dk(from_nick="Bob"),
                      dk(ts_display="10:02"), dk(kind="image"),
                      dk(payload="bye")):
            self.assertNotEqual(other, base)
        # … and occ is NOT part of it (re-reads shift occurrences)
        rec_a = MessageRecord(direction="in", from_nick="Ann",
                              ts_display="10:01", kind="text", text="hi",
                              occ=0)
        rec_b = MessageRecord(direction="in", from_nick="Ann",
                              ts_display="10:01", kind="text", text="hi",
                              occ=5)
        self.assertEqual(rec_a.dup_key, rec_b.dup_key)
        # … while the full fingerprint DOES separate them
        self.assertNotEqual(rec_a.ensure_fp(), rec_b.ensure_fp())

    def test_dedupe_key_pins_occ_to_exactly_zero(self):
        """G5: `dedupe_key` hardcodes occ=0, and mutating that constant to 1
        (or dropping it) survived every test. It must not: the dedupe key is
        compared against keys computed on EARLIER runs, so changing the
        constant makes the archive stop recognising its own stored rows and
        re-append the whole conversation."""
        self.assertEqual(dk(), fp(occ=0))
        self.assertNotEqual(dk(), fp(occ=1))


class TestIntOr(unittest.TestCase):
    def test_tolerant_matrix(self):  # MDL-03
        self.assertEqual(_int_or("12", 0), 12)
        self.assertEqual(_int_or("xx", 7), 7)
        self.assertEqual(_int_or(None, 7), 7)
        self.assertEqual(_int_or(12.9, 0), 12)
        self.assertEqual(_int_or(True, 0), 1)
        self.assertEqual(_int_or([1], 3), 3)
        self.assertEqual(_int_or("", 9), 9)


class TestFromDict(unittest.TestCase):
    def test_empty_dict_is_a_usable_record(self):  # MDL-04
        rec = MessageRecord.from_dict({})
        self.assertEqual(rec.direction, "in")
        self.assertEqual(rec.kind, "text")
        self.assertTrue(rec.fp)  # identity computed, not blank
        self.assertTrue(rec.dup_key)

    def test_none_is_a_usable_record(self):  # MDL-04b
        rec = MessageRecord.from_dict(None)
        self.assertEqual(rec.direction, "in")

    def test_wrong_typed_fields_coerce(self):  # MDL-05
        rec = MessageRecord.from_dict({"occ": "xx", "idx": None,
                                       "from": 5, "dir": 0,
                                       "media": "garbage-not-dict"})
        self.assertEqual(rec.occ, 0)
        self.assertEqual(rec.idx, 0)
        self.assertEqual(rec.from_nick, "5")
        self.assertEqual(rec.media_url, "")
        self.assertTrue(rec.fp)

    def test_a_valid_media_block_is_actually_read(self):
        """G5 gap: no test ever supplied a WELL-FORMED media block, so reading
        the wrong key entirely survived mutation. That failure mode is every
        image in a conversation silently becoming a text line with no URL."""
        rec = MessageRecord.from_dict({
            "from": "Ann", "media": {"url": "https://x/a.png", "kind": "image"}})
        self.assertEqual(rec.media_url, "https://x/a.png")
        self.assertEqual(rec.media_kind, "image")

    def test_the_nested_media_block_wins_over_the_flat_spelling(self):
        """Both spellings arrive from different agent versions; the nested one
        is the current shape and must take precedence."""
        rec = MessageRecord.from_dict({
            "media": {"url": "https://new/a.png", "kind": "image"},
            "media_url": "https://old/b.png", "media_kind": "gif"})
        self.assertEqual(rec.media_url, "https://new/a.png")
        self.assertEqual(rec.media_kind, "image")

    def test_the_flat_spelling_is_used_when_there_is_no_block(self):
        rec = MessageRecord.from_dict({"media_url": "https://old/b.png",
                                       "media_kind": "gif"})
        self.assertEqual(rec.media_url, "https://old/b.png")
        self.assertEqual(rec.media_kind, "gif")

    def test_a_garbage_media_block_falls_back_instead_of_discarding(self):
        """A non-dict `media` degrades to no-block — but must not also throw
        away a usable flat URL sitting next to it."""
        rec = MessageRecord.from_dict({"media": "garbage",
                                       "media_url": "https://x/c.png"})
        self.assertEqual(rec.media_url, "https://x/c.png")

    def test_unknown_keys_are_dropped(self):  # MDL-06
        rec = MessageRecord.from_dict({"text": "hi", "zzz": 1,
                                       "nested": {"a": [1]}})
        self.assertEqual(rec.text, "hi")
        self.assertFalse(hasattr(rec, "zzz"))

    def test_media_record_identity(self):  # MDL-07
        rec = MessageRecord(direction="in", from_nick="Ann",
                            ts_display="10:01", kind="image",
                            media_url="https://x/a.png")
        self.assertEqual(rec.payload, "https://x/a.png")
        twin = MessageRecord(direction="in", from_nick="Ann",
                             ts_display="10:01", kind="image",
                             media_url="https://x/a.png", occ=3)
        self.assertEqual(rec.dup_key, twin.dup_key)

    def test_text_beats_no_media_url_for_payload(self):  # MDL-07b
        rec = MessageRecord(text="hello")
        self.assertEqual(rec.payload, "hello")


class TestResultObjects(unittest.TestCase):
    def test_result_dicts_are_json_safe(self):  # MDL-08
        live = MessageRecord(direction="in", from_nick="A",
                             ts_display="t", text="x")
        live.ensure_fp()
        for obj in (AppendResult(added=1, records=[live]),
                    Alignment(start=3, gap=True, reason="dom_jump",
                              overlap=2, matched=True),
                    SyncResult(ok=True, nick="A", records=[{"k": 1}],
                               chunks=[1, 2])):
            json.dumps(obj.to_dict())

    def test_alignment_default_is_append_all(self):  # MDL-09
        alg = Alignment()
        self.assertEqual((alg.start, alg.matched, alg.gap), (0, False, False))

    def test_live_items_bound_is_sane(self):  # MDL-08b
        self.assertGreater(MAX_LIVE_ITEMS, 0)
        res = AppendResult(records=list(range(MAX_LIVE_ITEMS + 5)))
        self.assertEqual(len(res.to_dict()["records"]), MAX_LIVE_ITEMS + 5)

    # ── G5: gaps mutation testing found in `fingerprint` ──────────
    def test_every_field_changes_the_fingerprint(self):
        """Each component must actually reach the hash. A field dropped from
        the join makes two DIFFERENT lines collide, and a collision in this
        function means a real message is silently discarded as a duplicate."""
        base = dict(direction="in", from_nick="Ann", ts_display="10:02",
                    kind="text", payload="hello", occ=0)
        baseline = fingerprint(**base)
        for field, other in (("direction", "out"), ("from_nick", "Bob"),
                             ("ts_display", "10:03"), ("kind", "image"),
                             ("payload", "goodbye"), ("occ", 1)):
            changed = dict(base, **{field: other})
            self.assertNotEqual(fingerprint(**changed), baseline,
                                f"{field} does not affect the fingerprint")

    def test_occ_defaults_to_zero(self):
        """The default is part of the contract: callers that omit `occ` must
        agree with callers that pass 0, or the same line hashes two ways."""
        self.assertEqual(fingerprint("in", "Ann", "10:02", "text", "hi"),
                         fingerprint("in", "Ann", "10:02", "text", "hi", 0))

    def test_falsy_fields_normalise_rather_than_crash(self):
        """None and "" are the same absence, and `kind` falls back to text."""
        self.assertEqual(fingerprint(None, None, None, None, None),
                         fingerprint("", "", "", "text", ""))

    def test_fields_cannot_bleed_across_the_separator(self):
        """Without a separator, ("ab","c") and ("a","bc") would hash alike —
        that is a duplicate-detection bug, not a cosmetic one."""
        self.assertNotEqual(
            fingerprint("in", "ab", "c", "text", "x"),
            fingerprint("in", "a", "bc", "text", "x"))

    def test_the_fingerprint_is_stable_and_well_formed(self):
        first = fingerprint("in", "Ann", "10:02", "text", "hi")
        self.assertEqual(first, fingerprint("in", "Ann", "10:02", "text", "hi"))
        self.assertEqual(len(first), 16)
        int(first, 16)          # must be hex; raises otherwise
        # LOWERCASE hex, specifically. Fingerprints are stored in the database
        # and compared as strings, so switching the format to %08X would make
        # every previously-archived line fail to match itself — the archive
        # would re-append its entire history as "new".
        self.assertEqual(first, first.lower())

    def test_the_hash_reads_utf16_code_units_little_endian(self):
        """G5: the byte-pairing arithmetic in `_utf16_units` was unpinned —
        `<< 8` could become `>> 8` or `<< 9` and every ASCII test still passed,
        because ASCII's high byte is zero. Only non-ASCII text notices.

        This matters because the fingerprint is stored: if the hash changes,
        every archived Cyrillic or emoji line stops matching itself.
        """
        # Characters that differ ONLY in the high byte of their code unit.
        # A broken shift collapses them to the same hash.
        self.assertNotEqual(fp(payload="\u0100"), fp(payload="\u0000"))
        self.assertNotEqual(fp(payload="Ā"), fp(payload="ā"))
        # Byte order: "\u0102" and "\u0201" are the same two bytes swapped.
        self.assertNotEqual(fp(payload="\u0102"), fp(payload="\u0201"))
        # A GOLDEN value. Everything above proves the hash distinguishes
        # things; only a fixed expected output proves it has not shifted
        # wholesale — which is what a changed seed, mask, shift width or
        # index offset does. These strings are on disk in every user's
        # archive, so this constant is a compatibility pin, not a snapshot.
        self.assertEqual(
            fingerprint("in", "Аня", "10:01", "text", "привет 🎉"),
            "49cf6d3fa70a1604")
        self.assertEqual(fingerprint("in", "Ann", "10:01", "text", "hi"),
                         "679b985cbe677f65")

    def test_lone_surrogates_do_not_crash_the_fingerprint(self):
        """Chat payloads arrive from JS, where a split emoji can leave a lone
        surrogate. Encoding without "surrogatepass" raises on it, which would
        take down the archive write rather than store an odd string."""
        broken = "hi \ud83d there"
        self.assertEqual(len(fingerprint("in", "Ann", "1", "text", broken)),
                         16)
        self.assertNotEqual(
            fingerprint("in", "Ann", "1", "text", broken),
            fingerprint("in", "Ann", "1", "text", "hi  there"))

    def test_ensure_fp_computes_once(self):  # MDL-10
        rec = MessageRecord(text="x")
        first = rec.ensure_fp()
        rec.text = "changed underneath"
        self.assertEqual(rec.ensure_fp(), first)


if __name__ == "__main__":
    unittest.main()
