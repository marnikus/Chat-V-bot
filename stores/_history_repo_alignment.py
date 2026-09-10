"""HistoryRepo alignment — pure helpers (AREA B)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from stores.history_models import Alignment

def align_batch(batch_fps: Sequence[str], tail_fps: Sequence[str]) -> Alignment:
    batch = list(batch_fps)
    tail = list(tail_fps)
    if not batch or not tail:
        return Alignment(start=0, matched=True)
    for end in range(len(batch), 0, -1):
        for k in range(min(len(tail), end), 0, -1):
            if batch[end - k:end] == tail[-k:]:
                return Alignment(start=end, overlap=k, matched=True)
    return Alignment(start=0, gap=True, reason="alignment_lost")

def resolve_days(times: Sequence[str], now: datetime) -> list[str]:
    day = now.date()
    prev = now.hour * 60 + now.minute
    out: list[str] = []
    for stamp in reversed(list(times)):
        minutes = _minutes(stamp)
        if minutes is None:
            out.append(day.isoformat())
            continue
        if minutes > prev:
            day = day - timedelta(days=1)
        prev = minutes
        out.append(day.isoformat())
    out.reverse()
    return out

def _minutes(stamp: str) -> Optional[int]:
    try:
        hh, mm = str(stamp).strip().split(":")[:2]
        return int(hh) * 60 + int(mm)
    except Exception:
        return None
