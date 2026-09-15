"""Run tracer — extracted from hooks.py (H-C5 split)

Trace file handling, ≤100 LOC.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger("chatbot")
_TRACER_VER = 1


class RunTracer:
    def __init__(self, run_id: str, log_dir: str = "logs"):
        os.makedirs(log_dir, exist_ok=True)
        self.run_id = run_id
        self.path = os.path.join(log_dir, f"run_trace_{run_id}.jsonl")
        self._fh = open(self.path, "a", encoding="utf-8")

    def note(self, record: dict) -> None:
        try:
            stamp = datetime.now().isoformat(timespec="milliseconds")
            self._fh.write(json.dumps({"ts": stamp, "run_id": self.run_id, **record}, ensure_ascii=False) + "\n")
            self._fh.flush()
        except OSError as exc:
            log.error("Trace write failed: %s", exc)

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass
