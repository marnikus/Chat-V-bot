"""Attach Image: active-chat targeting, dialog flow, formats, send verify.

FEATURE —
  * the block resolves the ACTIVE (visible) conversation and attaches there
    — when several chat panels are mounted (e.g. a hidden main-room
    composer plus the open private chat) it uses the private chat's own
    image button and file input, never the first one in the DOM;
  * the image-button click runs through the shared visual-confirmation
    runner (red find outline -> pause -> orange click outline);
  * it picks .jpg/.jpeg/.png/.gif (any case) from the folder;
  * after injection it reads back `input.files.length` so a silent no-op
    injection is impossible;
  * it verifies a new `.message-container` really appeared INSIDE the same
    conversation, unless verification is disabled;
  * when the active-conversation probe cannot resolve it falls back to the
    global selectors with a warning.

Run with:  python3 tests/test_attach_image.py
"""

import asyncio
import os
import shutil
import sys
import tempfile
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

#: Default probe answer: a single visible composer that resolves to the
#: classic global selectors (equivalent to the pre-scoping layout).
DEFAULT_CTX = {
    "ok": True, "chat_count": 1,
    "input_css": media.FILE_INPUT_SELECTOR,
    "button_css": media.IMAGE_BUTTON_SELECTOR,
    "shell_css": "",
}

#: Two chat panels mounted; the second one is the visible private chat.
SECOND_CHAT_CTX = {
    "ok": True, "chat_count": 2,
    "input_css": "app-chat:nth-of-type(2) input#file[type='file']",
    "button_css": "app-chat:nth-of-type(2) "
                  ".mat-mdc-form-field-icon-suffix button",
    "shell_css": "app-chat:nth-of-type(2)",
}


class FakeCDP:
    """Records evaluate/set-file calls; answers the probe families."""

    def __init__(self, readback="1", counts=None, probe=PROBE_FOUND,
                 ctx=None):
        self.readback = readback
        self.counts = list(counts or [])
        self.probe = probe
        self.ctx = ctx if ctx is not None else dict(DEFAULT_CTX)
        self.evals = []
        self.sets = []

    async def evaluate(self, expression):
        self.evals.append(expression)
        if "ACTIVE_CHAT_CTX" in expression:
            return __import__("json").dumps(self.ctx)
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


# ── active-conversation scoping ──────────────────────────────────
class TestActiveChatScoping(unittest.TestCase):
    def test_injects_into_the_visible_conversation_when_several_are_mounted(self):
        """Two panels mounted: the block must use the SECOND chat's input
        (the visible private chat), not the first (hidden main room)."""
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(ctx=dict(SECOND_CHAT_CTX), counts=[2, 3])
            messages = []
            ok = await media.attach_image(
                cdp, d, simulate_dialog=True, verify_timeout_ms=200,
                verify_poll_ms=20,
                report=lambda m, lvl="info": messages.append(m))
            self.assertTrue(ok)
            # file landed in the SECOND chat panel's own input
            self.assertEqual(cdp.sets[0][0], SECOND_CHAT_CTX["input_css"])
            # verification counted inside the second panel only
            scoped_count_js = any(
                "app-chat:nth-of-type(2) .message-container" in e
                for e in cdp.evals)
            self.assertTrue(scoped_count_js,
                            "send verification must be scoped to the "
                            "active conversation")
            return d, " ".join(messages)
        d, msg = run(go())
        self.assertIn("2 chat panel(s)", msg,
                      "the run log should say how many panels were found")
        shutil.rmtree(d, ignore_errors=True)

    def test_single_composer_layout_uses_global_selectors(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(counts=[2, 3])       # default ctx = single panel
            ok = await media.attach_image(
                cdp, d, simulate_dialog=False, verify_timeout_ms=200,
                verify_poll_ms=20)
            self.assertTrue(ok)
            self.assertEqual(cdp.sets[0][0], media.FILE_INPUT_SELECTOR)
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_probe_failure_falls_back_to_global_selectors(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(ctx={"ok": False, "chat_count": 0,
                               "input_css": "", "button_css": "",
                               "shell_css": ""}, counts=[1, 2])
            messages = []
            ok = await media.attach_image(
                cdp, d, simulate_dialog=True, verify_timeout_ms=200,
                verify_poll_ms=20,
                report=lambda m, lvl="info": messages.append(m))
            self.assertTrue(ok)
            self.assertEqual(cdp.sets[0][0], media.FILE_INPUT_SELECTOR)
            return d, " ".join(messages)
        d, msg = run(go())
        self.assertIn("falling back", msg)
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
            # evaluate sequence: ctx, probe, readback, baseline count, poll
            text = " ".join(cdp.evals)
            self.assertIn("ACTIVE_CHAT_CTX", text)
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


# ── dialog simulation step + visual confirmation ─────────────────
class TestDialogSimulation(unittest.TestCase):
    def test_clicks_the_image_button_with_visual_confirmation(self):
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
            # the shared visual runner must be ON (BUG #3)
            self.assertTrue(kwargs.get("highlight_enabled"),
                            "the dialog click needs the red/orange outlines")
            self.assertGreater(kwargs.get("confirm_pause_ms", 0), 0,
                               "the click needs the confirm pause")
            self.assertTrue(hasattr(kwargs.get("engine"), "report"),
                            "logs must stream through engine.report")
            self.assertTrue(cdp.sets, "file injection must still happen")
            return d
        d = run(go())
        shutil.rmtree(d, ignore_errors=True)

    def test_click_targets_the_active_chat_image_button(self):
        async def go():
            d = tmp_folder(["a.jpg"])
            cdp = FakeCDP(ctx=dict(SECOND_CHAT_CTX), counts=[2, 3])
            click = mock.AsyncMock(return_value="ok")
            with mock.patch("backend.visual_click.find_and_click", click):
                ok = await media.attach_image(
                    cdp, d, simulate_dialog=True, verify_timeout_ms=200,
                    verify_poll_ms=20)
            self.assertTrue(ok)
            self.assertEqual(click.await_count, 1)
            kwargs = click.await_args.kwargs
            self.assertEqual(kwargs.get("selector"),
                             SECOND_CHAT_CTX["button_css"],
                             "must click the VISIBLE conversation's button")
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
            self.assertEqual(click.await_count, 2,
                             "a scoped miss must retry with the text search")
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
        self.assertTrue(blk.highlight_enabled)
        self.assertEqual(blk.confirm_pause_ms, 700)
        self.assertEqual(blk.verify_timeout_ms, 8000)

    def test_schema_exposes_every_setting(self):
        schema = AttachImage().config_schema()
        for key in ("folder_path", "file_pattern", "rotation_mode",
                    "simulate_dialog", "highlight_enabled",
                    "confirm_pause_ms", "verify_timeout_ms"):
            self.assertIn(key, schema)
        self.assertEqual(schema["rotation_mode"]["type"], "select")
        self.assertEqual(schema["simulate_dialog"]["type"], "checkbox")
        self.assertEqual(schema["highlight_enabled"]["type"], "checkbox")

    def test_to_dict_round_trips(self):
        blk = AttachImage(folder_path="/x", file_pattern="*.gif",
                          rotation_mode="random", simulate_dialog=False,
                          highlight_enabled=False, confirm_pause_ms=1500,
                          verify_timeout_ms=3000)
        d = blk.to_dict()
        again = AttachImage(**{k: v for k, v in d.items()
                               if k != "block_id"})
        self.assertEqual(again.file_pattern, "*.gif")
        self.assertEqual(again.rotation_mode, "random")
        self.assertFalse(again.simulate_dialog)
        self.assertFalse(again.highlight_enabled)
        self.assertEqual(again.confirm_pause_ms, 1500)
        self.assertEqual(again.verify_timeout_ms, 3000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
