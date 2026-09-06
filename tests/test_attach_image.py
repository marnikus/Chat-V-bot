"""Attach Image: human-like dialog flow, all image formats, send verify.

FEATURE —
  * the block picks .jpg/.jpeg/.png/.gif (any case) from the folder —
    not only *.jpg;
  * when `simulate_dialog` is on it first clicks the site's image (attach)
    button — the "open the upload dialog" step — then sets the file on the
    hidden input (the same result as choosing in the dialog);
  * after injection it reads back `input.files.length` so a silent no-op
    injection is impossible;
  * it then verifies a new `.message-container` really appeared (the site
    auto-sends the image once chosen), unless verification is disabled.

Run with:  python3 tests/test_attach_image.py
"""

import asyncio
import os
import sys
import tempfile
import shutil
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# actions first: importing the actions package triggers its full import
# chain (click_back -> find_click_runner -> visual_click ...), which must
# run before backend.visual_click is touched from anywhere else.
import actions.attach_image  # noqa: E402,F401
import backend.media_handler as media  # noqa: E402
from actions.attach_image import AttachImage  # noqa: E402

PROBE_FOUND = ('{"phase":"probe","found":true,"total":1,"visible":true,'
               '"disabled":false,"clickable":true,"error":null}')


class FakeCDP:
    """Records evaluate/set-file calls; answers the three probe families."""

    def __init__(self, readback="1", counts=None, probe=PROBE_FOUND):
        self.readback = readback
        self.counts = list(counts or [])
        self.probe = probe
        self.evals = []
        self.sets = []

    async def evaluate(self, expression):
        self.evals.append(expression)
        if "message-container" in expression:
            return str(self.counts.pop(0)) if self.counts else "0"
        if "files.length" in expression:
            return self.readback
        return self.probe

    async def set_file_input_files(self, selector, files):
        self.sets.append((selector, files))


def run(coro):
    return asyncio.run(coro)


def tmp_folder(files):
    d = tempfile.mkdtemp()
    for name in files:
        with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
            fh.write("x")
    return d


# ── pattern parsing + file discovery ─────────────────────────────
class TestFormats(unittest.TestCase):
    def test_default_pattern_covers_jpg_jpeg_png_gif(self):
        self.assertEqual(
            media.parse_patterns(media.DEFAULT_FILE_PATTERN),
            ["*.jpg", "*.jpeg", "*.png", "*.gif"])

    def test_bare_extension_is_wrapped(self):
        self.assertEqual(media.parse_patterns("gif, jpg"), ["*.gif", "*.jpg"])

    def test_semicolons_and_leading_dots(self):
        self.assertEqual(media.parse_patterns("gif;.png ; *.JPG"),
                         ["*.gif", "*.png", "*.jpg"])

    def test_finds_all_image_formats_case_insensitively(self):
        d = tmp_folder(["a.jpg", "b.GIF", "c.Png", "d.jpeg", "note.txt", "x.gif"])
        found = [os.path.basename(f) for f in media.list_image_files(
            d, media.DEFAULT_FILE_PATTERN)]
        self.assertEqual(found, ["a.jpg", "b.GIF", "c.Png", "d.jpeg", "x.gif"])
        shutil.rmtree(d, ignore_errors=True)

    def test_single_legacy_pattern_still_works(self):
        d = tmp_folder(["a.jpg", "b.gif"])
        found = [os.path.basename(f) for f in media.list_image_files(d, "*.jpg")]
        self.assertEqual(found, ["a.jpg"])
        shutil.rmtree(d, ignore_errors=True)


# ── the attach pipeline (no dialog step) ─────────────────────────
class TestAttachPipeline(unittest.TestCase):
    def test_injects_and_verifies_the_send(self):
        async def go():
            d = tmp_folder(["1.gif", "2.jpg"])
            cdp = FakeCDP(counts=[3, 4])      # message count grows → sent
            ok = await media.attach_image(
                cdp, d, simulate_dialog=False, verify_timeout_ms=300,
                verify_poll_ms=20)
            self.assertTrue(ok)
            self.assertEqual(len(cdp.sets), 1)
            self.assertTrue(cdp.sets[0][1][0].endswith("1.gif") or
                            cdp.sets[0][1][0].endswith("2.jpg"))
            # evaluate sequence: probe, readback, baseline count, poll count
            text = " ".join(cdp.evals)
            self.assertIn("files.length", text)
            self.assertIn("message-container", text)
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_readback_zero_is_a_loud_failure(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(readback="0", counts=[5, 6])
            ok = await media.attach_image(
                cdp, d, simulate_dialog=False, verify_timeout_ms=200,
                verify_poll_ms=20)
            self.assertFalse(ok, "files.length=0 must fail the block")
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_verification_timeout_fails_with_stage_message(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(counts=[3, 3, 3, 3])   # never grows
            messages = []
            ok = await media.attach_image(
                cdp, d, simulate_dialog=False, verify_timeout_ms=120,
                verify_poll_ms=20,
                report=lambda m, lvl="info": messages.append(m))
            self.assertFalse(ok)
            joined = " ".join(messages)
            self.assertIn("No new message", joined,
                            "the failure must name the verify stage: "
                            + joined)
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_verification_can_be_disabled(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(counts=[])
            ok = await media.attach_image(
                cdp, d, simulate_dialog=False, verify_timeout_ms=0)
            self.assertTrue(ok)
            self.assertTrue(cdp.sets)
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_missing_folder_fails(self):
        async def go():
            ok = await media.attach_image(FakeCDP(), "/no/such/folder")
            return ok
        self.assertFalse(run(go()))

    def test_no_matching_files_fails_and_lists_formats(self):
        async def go():
            d = tmp_folder(["readme.txt"])
            messages = []
            ok = await media.attach_image(
                FakeCDP(), d, file_pattern="*.png",
                report=lambda m, lvl="info": messages.append(m))
            self.assertFalse(ok)
            return d, " ".join(messages)
        d, msg = run(go())
        self.assertIn("png", msg)
        shutil.rmtree(d, ignore_errors=True)

    def test_missing_file_input_fails(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(probe='{"phase":"probe","found":false,"total":0,'
                                '"visible":false,"disabled":false,'
                                '"clickable":false,"error":null}')
            ok = await media.attach_image(cdp, d, simulate_dialog=False)
            return d, ok
        d, ok = run(go())
        self.assertFalse(ok)
        shutil.rmtree(d, ignore_errors=True)


# ── dialog simulation step ───────────────────────────────────────
class TestDialogSimulation(unittest.TestCase):
    def test_clicks_the_image_button_first(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(counts=[2, 3])
            click = mock.AsyncMock(return_value="ok")
            with mock.patch("backend.visual_click.find_and_click", click):
                ok = await media.attach_image(
                    cdp, d, simulate_dialog=True, verify_timeout_ms=200,
                    verify_poll_ms=20)
            self.assertTrue(ok)
            self.assertEqual(click.await_count, 1)
            kwargs = click.await_args.kwargs
            self.assertIn("image", kwargs.get("match_text", ""))
            self.assertIn("suffix", kwargs.get("selector", ""))
            self.assertTrue(cdp.sets, "file injection must still happen")
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_button_click_failure_warns_but_injects_directly(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(counts=[1, 2])
            messages = []
            click = mock.AsyncMock(return_value="fail")
            with mock.patch("backend.visual_click.find_and_click", click):
                ok = await media.attach_image(
                    cdp, d, simulate_dialog=True, verify_timeout_ms=200,
                    verify_poll_ms=20,
                    report=lambda m, lvl="info": messages.append(m))
            self.assertTrue(ok)
            self.assertTrue(cdp.sets)
            return d, " ".join(messages)
        d, msg = run(go())
        self.assertIn("image", msg)
        shutil.rmtree(d, ignore_errors=True)


# ── block settings round-trip ────────────────────────────────────
class TestBlockSettings(unittest.TestCase):
    def test_defaults(self):
        blk = AttachImage()
        self.assertEqual(blk.file_pattern, media.DEFAULT_FILE_PATTERN)
        self.assertEqual(blk.rotation_mode, "sequential")
        self.assertTrue(blk.simulate_dialog)
        self.assertEqual(blk.verify_timeout_ms, 8000)

    def test_schema_exposes_every_setting(self):
        schema = AttachImage().config_schema()
        for key in ("folder_path", "file_pattern", "rotation_mode",
                    "simulate_dialog", "verify_timeout_ms"):
            self.assertIn(key, schema)
        self.assertEqual(schema["rotation_mode"]["type"], "select")
        self.assertEqual(schema["simulate_dialog"]["type"], "checkbox")

    def test_to_dict_round_trips(self):
        blk = AttachImage(folder_path="/x", file_pattern="*.gif",
                          rotation_mode="random", simulate_dialog=False,
                          verify_timeout_ms=3000)
        d = blk.to_dict()
        again = AttachImage(**{k: v for k, v in d.items()
                               if k != "block_id"})
        self.assertEqual(again.file_pattern, "*.gif")
        self.assertEqual(again.rotation_mode, "random")
        self.assertFalse(again.simulate_dialog)
        self.assertEqual(again.verify_timeout_ms, 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
