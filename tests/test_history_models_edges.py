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
        self.assertNotEqual(rec_a.ensure_fp(), rec_b.ensure_fp())


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

    def test_ensure_fp_computes_once(self):  # MDL-10
        rec = MessageRecord(text="x")
        first = rec.ensure_fp()
        rec.text = "changed underneath"
        self.assertEqual(rec.ensure_fp(), first)


if __name__ == "__main__":
    unittest.main()
