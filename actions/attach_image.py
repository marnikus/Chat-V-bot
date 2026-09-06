"""Attach an image from a folder — human-like upload-dialog flow.

New settings (see docs/ATTACH_IMAGE_DIALOG_FORMATS_DESIGN_2026-09-06.md):
  * `file_pattern`      — comma-separated patterns/extensions
                          (default *.jpg, *.jpeg, *.png, *.gif);
  * `simulate_dialog`   — click the site's image button first (like a
                          human opening the upload dialog);
  * `verify_timeout_ms` — wait for the image message to really appear in
                          the chat (0 = skip the verification).
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
                 pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.folder_path = folder_path
        self.file_pattern = file_pattern or DEFAULT_FILE_PATTERN
        self.rotation_mode = rotation_mode
        self.simulate_dialog = bool(simulate_dialog)
        self.verify_timeout_ms = max(0, int(verify_timeout_ms or 0))

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = engine.report if engine else None
        ok = await attach_image(cdp, self.folder_path, self.file_pattern,
                                self.rotation_mode, self.simulate_dialog,
                                self.verify_timeout_ms, report)
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
        s["verify_timeout_ms"] = {"type": "number", "default": 8000,
                                  "label": "Wait for the image to send (ms, "
                                           "0 = skip)"}
        return s
