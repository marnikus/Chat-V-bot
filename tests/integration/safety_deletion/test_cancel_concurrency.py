"""Cancellation / concurrency: boundaries, overlapping deletes, stale plan."""

import asyncio
import os
import shutil
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _helpers import TempWorld, insert_media_row_sync, write_file


class TestCancelConcurrency(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.w = TempWorld()
        await self.w.setup(with_b=True, with_c=True)

    async def asyncTearDown(self):
        await self.w.teardown()

    async def test_cancel_before_destructive_boundary_no_removal(self):
        mgr = self.w.manager
        victim = self.w.world_a  # active → switch has awaits to cancel in
        media = os.path.join(self.w.media_dir_for(victim), "a.jpg")
        write_file(media, b"x")
        insert_media_row_sync(victim, "https://x/a.jpg", media)
        # Cancel while in switch (before any unlink)
        orig_switch = self.w.svc.switch_db

        async def slow_switch(path):
            await asyncio.sleep(0.2)
            return await orig_switch(path)

        with mock.patch.object(self.w.svc, "switch_db",
                               side_effect=slow_switch):
            task = asyncio.ensure_future(mgr.delete(victim))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(os.path.exists(victim),
                        "cancel before boundary must not remove")
        self.assertTrue(os.path.exists(media))

    async def test_cancel_after_partial_reconciles_then_propagates(self):
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        a = os.path.join(base, "c", "a.jpg")
        b = os.path.join(base, "c", "b.jpg")
        write_file(a, b"a")
        write_file(b, b"b")
        insert_media_row_sync(victim, "https://x/a.jpg", a)
        insert_media_row_sync(victim, "https://x/b.jpg", b)
        real_unlink = os.unlink
        first = {"done": False}

        def flaky(path, *args, **kwargs):
            # let DB group pass, cancel on second media file
            ap = os.path.abspath(str(path))
            if ap == os.path.abspath(b) and first["done"]:
                raise asyncio.CancelledError()
            if ap == os.path.abspath(a):
                first["done"] = True
            return real_unlink(path, *args, **kwargs)

        with mock.patch("os.unlink", side_effect=flaky):
            with self.assertRaises(asyncio.CancelledError):
                await mgr.delete(victim)
        # a removed, b survives, victim DB gone (DB phase done before media)
        self.assertFalse(os.path.exists(a))
        self.assertTrue(os.path.exists(b))
        # reconciliation: active still valid, no exception swallowed
        self.assertTrue(os.path.exists(mgr.active_path()))

    async def test_overlapping_deletes_same_victim_one_wins(self):
        mgr = self.w.manager
        victim = self.w.world_b
        # Two concurrent deletes of same victim; exactly one ok True.
        r1, r2 = await asyncio.gather(mgr.delete(victim), mgr.delete(victim))
        oks = [r for r in (r1, r2) if r.get("ok")]
        self.assertEqual(len(oks), 1,
                         f"exactly one must win, got {r1} vs {r2}")
        # survivor worlds intact
        self.assertTrue(os.path.exists(self.w.world_a))
        self.assertTrue(os.path.exists(self.w.world_c))

    async def test_overlapping_deletes_last_two_worlds_leaves_one(self):
        # Fresh 2-world setup: concurrent deletes of BOTH worlds must leave 1.
        w2 = TempWorld()
        await w2.setup(with_b=True, with_c=False)
        try:
            mgr = w2.manager
            a, b = w2.world_a, w2.world_b
            r1, r2 = await asyncio.gather(mgr.delete(a), mgr.delete(b))
            remaining = [p for p in (a, b) if os.path.exists(p)]
            self.assertEqual(len(remaining), 1,
                             f"one world must survive, got {r1} vs {r2}, "
                             f"remaining={remaining}")
            # loser must be last-database or missing refusal, not success
            oks = [r for r in (r1, r2) if r.get("ok")]
            self.assertEqual(len(oks), 1)
        finally:
            await w2.teardown()

    async def test_new_world_between_plan_and_execute_invalidates(self):
        from contextlib import ExitStack
        mgr = self.w.manager
        victim = self.w.world_b
        base = self.w.media_base
        shared = os.path.join(base, "stale", "a.jpg")
        write_file(shared, b"s")
        insert_media_row_sync(victim, "https://x/s.jpg", shared)

        def _make_stale_world():
            newp = os.path.join(self.w.dir, "stale_new.db")
            if not os.path.exists(newp):
                shutil.copyfile(self.w.world_a, newp)
                insert_media_row_sync(newp, "https://x/s.jpg", shared)
            return newp

        # Fixed hook: first inventory call returns stale, then new world
        # appears before revalidation (legacy _world_footprint hook removed
        # with the dead fail-open helpers).
        with ExitStack() as stack:
            try:
                import services.db_deletion as delmod
                orig_inv = delmod.build_deletion_inventory
                state = {"calls": 0}

                def hooked_inv(*a, **k):
                    res = orig_inv(*a, **k)
                    if state["calls"] == 0:
                        _make_stale_world()
                    state["calls"] += 1
                    return res

                stack.enter_context(mock.patch.object(
                    delmod, "build_deletion_inventory", side_effect=hooked_inv))
            except ImportError:
                pass
            result = await mgr.delete(victim)
        # Fixed: inventory changed → refuse, shared survives, victim survives.
        # Baseline: stale existing list misses new world → deletes shared (red).
        self.assertTrue(os.path.exists(shared),
                        "stale plan must not delete newly referenced file")
        # Fixed refuses (ok False); baseline deletes (ok True) — assert refuse
        self.assertFalse(result.get("ok"),
                         f"stale inventory must refuse, got {result}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
