"""History repo helpers (<150)."""
from __future__ import annotations
import re
from datetime import datetime
from typing import Sequence, Optional

def align_batch(batch_fps: Sequence[str],
                tail_fps: Sequence[str]) -> Alignment:
    """Find where `batch_fps` continues the stored conversation.

    Returns the index of the first record after the known tail — the LAST
    place in the batch where our stored suffix occurs, so a conversation
    whose older half was re-rendered above us (the user scrolled up) is not
    mistaken for new messages. When nothing overlaps at all and we do have a
    stored tail, alignment is lost: the caller must append everything and
    record a gap.
    """
    batch = list(batch_fps)
    tail = list(tail_fps)
    if not batch or not tail:
        return Alignment(start=0, matched=True)       # first ever batch
    for end in range(len(batch), 0, -1):
        for k in range(min(len(tail), end), 0, -1):
            if batch[end - k:end] == tail[-k:]:
                return Alignment(start=end, overlap=k, matched=True)
    return Alignment(start=0, gap=True, reason="alignment_lost")



def resolve_days(times: Sequence[str], now: datetime) -> list[str]:
    """Turn HH:MM-only stamps into dates by walking the list BACKWARDS.

    The site shows no date separators, so the newest line is "today" (or
    yesterday if its clock time is still ahead of now) and every step back in
    time that increases the clock crosses midnight.
    """
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
    except Exception:                                # noqa: BLE001
        return None



def _as_record(item) -> MessageRecord:
    if isinstance(item, MessageRecord):
        item.ensure_fp()
        return item
    return MessageRecord.from_dict(item)


class HistoryRepo:
    """Append-only writer for one archive database."""


