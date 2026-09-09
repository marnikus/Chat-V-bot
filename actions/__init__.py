"""Actions package — auto-discovery via registry.

No manual import list: `discover()` scans the package and fires @register
decorators (or __init_subclass__ hooks). Keeps Open/Closed principle.
"""

from actions.base_action import BaseAction, ActionResult  # noqa: F401
from actions.registry import (  # noqa: F401
    ActionContext,
    all_action_ids,
    discover,
    get_action_class,
    register,
)

# The scan already ran: importing actions.registry calls discover(), which
# imports every module in the package one by one, logging any module that
# fails - so a single broken action can neither take the others down with it
# nor vanish from the palette without a line in the log (BUG-03).
