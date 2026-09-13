"""`merge_live` — fold one `AppendResult` into the live `SyncResult`.

The single place that decides which freshly-written rows may be pushed through
the live-append channel to the UI. A leaf module: it imports only
`stores.history_models`, and `session.SyncSession.absorb` is its only caller.
"""

from __future__ import annotations

from stores.history_models import MAX_LIVE_ITEMS, SyncResult


def merge_live(result: SyncResult, appended, baseline: int = 0) -> None:
    """Keep only the newest records actually inserted for a live UI update.

    `baseline` is the previous archive `last_ord`: rows a backfill prepends
    (they are *older* than everything the user already had) must not be
    pushed through the live-append channel; only rows appended after the
    previous tail belong there.
    """
    for record in (getattr(appended, "records", None) or []):
        if len(result.records) >= MAX_LIVE_ITEMS:
            break
        try:
            ord_value = int(record.get("ord") or 0)
        except (TypeError, ValueError):
            ord_value = 0
        if ord_value <= baseline:
            continue
        result.records.append(record)
