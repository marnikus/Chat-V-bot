"""Qt conftest for integration tests — same seeding as unit/app.

Integration tests need full container + real Qt.
"""

from __future__ import annotations

from PySide6.QtCore import QObject  # noqa: E402

_real_qobj = getattr(QObject.__init__, "__objclass__", None)
assert _real_qobj is not None and getattr(_real_qobj, "__module__", "").startswith("PySide6"), (
    "tests/integration/conftest.py requires real PySide6"
)

from services.run import RunCoordinator, RunProgress  # noqa: E402,F401
from app.bootstrap import create_container, queue_path  # noqa: E402,F401
import main  # noqa: E402,F401
