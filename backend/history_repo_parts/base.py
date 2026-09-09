"""History repo base (<150)."""
from __future__ import annotations
import asyncio, json, logging, re
from datetime import datetime
from typing import Optional, Iterable, Sequence
from backend.history_db import HistoryDB

log = logging.getLogger("chatbot")

class HistoryRepoBase:
    pass
