"""Actions package.

Importing this package (or `actions.base_action`) registers every action
block in the action registry via `__init_subclass__`. Without these imports
the engine would never resolve any block_id — this used to silently produce
an empty stack at runtime.
"""

from actions.base_action import BaseAction, ActionResult  # noqa: F401
from actions import (  # noqa: F401
    attach_image,
    click_back,
    click_main_tab,
    click_send,
    click_user,
    conditional_skip,
    pause,
    scroll_parse,
    type_message,
    wait_page,
)
