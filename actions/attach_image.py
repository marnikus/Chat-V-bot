"""Attach an image from a folder via the hidden file input."""

import logging
from typing import Optional
from actions.base_action import BaseAction, ActionResult
from backend.cdp_client import CDPClient
from backend.media_handler import attach_image

log = logging.getLogger("chatbot")


class AttachImage(BaseAction):
    block_id = "ATTACH_IMAGE"
    name = "Attach Image"
    icon = "🖼️"

    def __init__(self, folder_path: str = "", file_pattern: str = "*.jpg",
                 rotation_mode: str = "sequential", pre_delay_ms: int = 500, **kw):
        super().__init__(pre_delay_ms=pre_delay_ms, **kw)
        self.folder_path = folder_path
        self.file_pattern = file_pattern
        self.rotation_mode = rotation_mode

    async def execute(self, user_nick: str, cdp: CDPClient,
                      engine: Optional[object] = None) -> str:
        await self.pre_delay()
        report = engine.report if engine else None
        ok = await attach_image(cdp, self.folder_path, self.file_pattern,
                                self.rotation_mode, report)
        return ActionResult.OK if ok else ActionResult.FAIL

    def config_schema(self) -> dict:
        s = super().config_schema()
        s["folder_path"] = {"type": "text", "default": "", "label": "Image folder path"}
        s["file_pattern"] = {"type": "text", "default": "*.jpg", "label": "File pattern"}
        return s
