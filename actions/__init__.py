"""Actions package.

Importing this package scans every module via pkgutil and registers each
action block in the ActionRegistry through ``__init_subclass__`` — a new
block is a new file in actions/, with no central import list to edit
(previously this module hand-imported 17 modules; forgetting one silently
produced an empty stack at runtime).

Run ``ActionRegistry.scan()`` again after dynamically creating modules
(e.g. in tests).
"""

from actions.registry import ActionRegistry  # noqa: F401

ActionRegistry.scan()
