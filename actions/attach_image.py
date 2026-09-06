"""Attach an image from a folder — human-like upload-dialog flow.

The block resolves the ACTIVE conversation (the visible composer) and
attaches the image there — a private chat tab, never a hidden main-room
composer. Opening the dialog runs through the shared visual-confirmation
runner (red find outline → pause → orange click outline), like every other
find-and-click block.

Settings (see docs/EXTRA_PAUSE_STATUS_AND_ATTACH_TARGETING_DESIGN_2026-09-06.md):
  * `file_pattern`      — comma-separated patterns/extensions
                          (default *.jpg, *.jpeg, *.png, *.gif);
  * `simulate_dialog`   — click the active chat's image button first
                          (like a human opening the upload dialog);
  * `highlight_enabled` — draw the visual confirmation outlines;
  * `confirm_pause_ms`  — pause between the red find and the orange click;
  * `verify_timeout_ms` — wait for the image message to really appear in
                          the active chat (0 = skip the verification).
"""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.media_handler import attach_image, DEFAULT_FILE_PATTERN

log = logging.getLogger("chatbot")


class AttachImage(BaseAction):
    block_id = "ATTACH_IMAGE"
    name = "Attach Image"
    icon = "🖼️"

    def __init__(self, folder_path: str = "", file_pattern: str = "",
                 rotation_mode: str = "sequential",
                 simulate_dialog: bool = True, verify_timeout_ms: int = 8000,
                 highlight_enabled: bool = True, confirm_pause_ms: int = 700,
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.folder_path = folder_path
        self.file_pattern = file_pattern or DEFAULT_FILE_PATTERN
        self.rotation_mode = rotation_mode
        self.simulate_dialog = bool(simulate_dialog)
        self.verify_timeout_ms = max(0, int(verify_timeout_ms or 0))
        self.highlight_enabled = bool(highlight_enabled)
        self.confirm_pause_ms = max(0, int(confirm_pause_ms or 0))

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = engine.report if engine else None
        ok = await attach_image(cdp, self.folder_path, self.file_pattern,
                                self.rotation_mode, self.simulate_dialog,
                                self.verify_timeout_ms,
                                self.highlight_enabled,
                                self.confirm_pause_ms, report)
        return ActionResult.OK if ok else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["folder_path"] = {"type": "text", "default": "",
                            "label": "Image folder path"}
        s["file_pattern"] = {"type": "text",
                             "default": DEFAULT_FILE_PATTERN,
                             "label": "Image formats (comma separated — "
                                      "e.g. jpg, jpeg, png, gif)"}
        s["rotation_mode"] = {"type": "select", "default": "sequential",
                              "options": ["sequential", "random"],
                              "label": "Pick order"}
        s["simulate_dialog"] = {"type": "checkbox", "default": True,
                                "label": "Open the upload dialog first "
                                         "(click the image button, like "
                                         "a human)"}
        s["highlight_enabled"] = {"type": "checkbox", "default": True,
                                  "label": "Draw confirmation outlines "
                                           "(red = found, orange = click)"}
        s["confirm_pause_ms"] = {"type": "number", "default": 700,
                                 "label": "Pause after found (ms)"}
        s["verify_timeout_ms"] = {"type": "number", "default": 8000,
                                  "label": "Wait for the image to send (ms, "
                                           "0 = skip)"}
        return s
