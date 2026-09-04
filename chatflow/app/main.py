"""ChatFlow Orchestrator — source entry point that launches the updated UI.

This is a source-side runner for `python -m chatflow.app.main`. It reuses the
`backend` implementation (including the generic FIND_ELEMENT block, stack
preset manager, URL presets, and per-step debugger) so the feature set is
visible from this entry point too, not only from `python main.py`.
"""

import sys
import os

# Ensure project root is on path (this file lives at <root>/chatflow/app/main.py)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from main import MainWindow, main  # noqa: E402  (mirrors the root launcher)


if __name__ == "__main__":
    main()
