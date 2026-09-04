"""📷 Attach Image: random file from the configured folder (F-MM-04/05).

Primary path: the page's hidden `input#file` (set_input_files) — no OS dialog
race. Falls back to the file-chooser only if the input is missing.
"""
from __future__ import annotations

import os

from ..browser import selectors as sel
from ..engine.errors import OpError
from .base import BaseExecutor, BlockResult
from .registry import register

EXTS = (".gif", ".png", ".jpg", ".jpeg", ".webp")


def list_images(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder)
                  if f.lower().endswith(EXTS)
                  and os.path.isfile(os.path.join(folder, f)))


@register
class AttachImage(BaseExecutor):
    action_type = "attach_image"
    label = "Attach Image"
    icon = "📷"
    params_schema = []

    async def execute(self, ctx, block) -> BlockResult:
        if not ctx.s.attach_image:
            return BlockResult(data={"skipped": True})
        files = list_images(ctx.s.image_folder)
        if not files:
            ctx.log(self.icon, "No images in folder — skipped")
            return BlockResult(data={"skipped": True})
        name = ctx.rng.choice(files)
        path = os.path.abspath(os.path.join(ctx.s.image_folder, name))
        try:
            await ctx.ops.set_files(sel.FILE_INPUT, path)
        except OpError:
            await self._via_chooser(ctx, path)
        ctx.log(self.icon, f'Attached "{name}"')
        return BlockResult(data={"file": name})

    async def _via_chooser(self, ctx, path: str) -> None:
        with ctx.page.expect_file_chooser() as fc:
            await ctx.ops.click(sel.IMAGE_BTN)
        await fc.value.set_files(path)
