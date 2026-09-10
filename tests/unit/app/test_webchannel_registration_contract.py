"""B4 — WebChannel registration contract (behavioral, not a source grep).

`tests/test_bridge_router.js` historically asserted that `main.py` contains
`registerObject("bridge")`. Registration moved to `app/window.py:create_window`,
so that source assertion went stale. This test executes the real
`create_window` under the scoped Qt stubs (no WebEngine is ever started) and
asserts the *behavior* the JS test used to grep for:

- the channel registers the exact provided bridge under the name "bridge";
- the channel is installed on the page and kept alive on the window;
- the expected local UI URL is loaded;
- the window is shown.

If registration is removed or the object name changes, these assertions fail
(verified against a temporarily mutated copy of app/window.py).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from qt_stubs import load_app_window  # noqa: E402

from backend.bridge import Bridge  # noqa: E402
from backend.config_manager import ConfigManager  # noqa: E402


class TestWebChannelRegistrationContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.winmod = load_app_window()   # app.window under scoped Qt stubs

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.cfg = ConfigManager(os.path.join(tmp, "config.json"))
        self.bridge = Bridge(config=self.cfg)

    def _create(self, **kwargs):
        return self.winmod.create_window(self.cfg, self.bridge, **kwargs)

    def test_channel_registers_the_exact_bridge_under_bridge(self):
        registrations = []

        class RecordingChannel:
            def __init__(self, parent=None):
                pass

            def registerObject(self, name, obj):
                registrations.append((name, obj))

        with mock.patch.object(self.winmod, "QWebChannel", RecordingChannel):
            self._create()
        self.assertEqual(len(registrations), 1)
        self.assertEqual(registrations[0][0], "bridge")
        self.assertIs(registrations[0][1], self.bridge)

    def test_channel_is_installed_on_page_and_kept_alive_on_window(self):
        window = self._create()
        channel = window._channel
        self.assertIsNotNone(channel)
        self.assertIs(channel.objects.get("bridge"), self.bridge)
        self.assertIs(window._view.page().channel, channel)
        self.assertIs(window._channel, channel)

    def test_window_loads_the_expected_local_ui_url_and_is_shown(self):
        window = self._create()
        loaded = window._view.loaded
        self.assertIsNotNone(loaded)
        self.assertTrue(loaded.is_local)
        self.assertEqual(loaded.toString(),
                         str(Path(self.winmod.UI_PATH).resolve()))
        self.assertTrue(window.show_called)

    def test_explicit_ui_path_is_honoured(self):
        custom = Path(tempfile.mkdtemp()) / "custom.html"
        window = self._create(ui_path=str(custom))
        self.assertEqual(window._view.loaded.toString(), str(custom.resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
