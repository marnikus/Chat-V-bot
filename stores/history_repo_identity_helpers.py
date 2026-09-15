"""Identity helpers — extracted from ConversationIdentity (H-C4).

Named responsibility: batch alignment, day resolution, record shaping.

Design: AREA_C H-C4 — helper named by responsibility, ≤200 LOC.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Sequence

from stores.history_models import Alignment, MessageRecord


def align_batch(batch_fps: Sequence[str], tail_fps: Sequence[str]) -> Alignment:
    batch = list(batch_fps)
    tail = list(tail_fps)
    if not batch or not tail:
        return Alignment(start=0, matched=True)
    for end in range(len(batch), 0, -1):
        for k in range(min(len(tail), end), 0, -1):
            if batch[end - k : end] == tail[-k:]:
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
    except Exception:  # noqa: BLE001
        return None


def _as_record(item) -> MessageRecord:
    if isinstance(item, MessageRecord):
        item.ensure_fp()
        return item
    return MessageRecord.from_dict(item)


_UI_HEAD_SPECS = (
    (("fp",), "fp", "", False),
    (("dir", "direction"), "direction", "in", False),
    (("from", "from_nick"), "from_nick", "", False),
)
_UI_BODY_SPECS = (
    (("kind",), "kind", "text", False),
    (("text",), "text", "", False),
)
_UI_TAIL_SPECS = (
    (("time", "ts_display"), "ts_display", "", False),
)


def _record_fields(rec, specs) -> dict:
    out = {}
    for keys, attr, default, as_int in specs:
        value = getattr(rec, attr) or default
        for key in keys:
            out[key] = int(value) if as_int else value
    return out


def _ui_media_payload(row: dict, media_id, rec) -> dict:
    return {
        "id": int(row.get("id") or media_id),
        "url": row.get("url") or rec.media_url or "",
        "kind": row.get("kind") or rec.media_kind or rec.kind,
        "state": row.get("state") or "pending",
        "path": row.get("cache_path") or "",
    }
