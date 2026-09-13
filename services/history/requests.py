"""The dependency value of `HistoryService` (Round G step 4).

One object per real consumer (the F5 rule). The facade constructor reads
the six collaborators from here; nothing else in the family needs them as
a bundle, so this module holds exactly one dataclass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class HistoryDeps:
    """What `HistoryService.__init__` builds the whole family from."""

    cdp: Any = None
    config: Any = None
    db_path: Optional[str] = None
    session_id: str = ""
    memory: Any = None
    labels: Any = None
