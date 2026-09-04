"""Image/GIF attachment via CDP file input injection."""

import os
import glob
import random
import logging
from backend.cdp_client import CDPClient

log = logging.getLogger("chatbot")

FILE_INPUT_SELECTOR = "input#file[type='file']"


async def attach_image(cdp: CDPClient, folder_path: str,
                       file_pattern: str = "*.jpg",
                       mode: str = "sequential") -> bool:
    """Inject an image file via DOM.setFileInputFiles."""
    if not os.path.isdir(folder_path):
        log.error("Image folder not found: %s", folder_path)
        return False
    files = sorted(glob.glob(os.path.join(folder_path, file_pattern)))
    if not files:
        log.error("No files matching %s in %s", file_pattern, folder_path)
        return False
    if mode == "random":
        path = random.choice(files)
    else:  # sequential — pick first (caller should rotate externally)
        path = files[0]
    await cdp.set_file_input_files(FILE_INPUT_SELECTOR, [os.path.abspath(path)])
    log.info("Image attached: %s", os.path.basename(path))
    return True
