"""Collector archive predicates — extracted from collector_archive (H-C5 split)

≤100 LOC.
"""

from __future__ import annotations


def _is_nick_changed(saved: str, current: str) -> bool:
    return bool(saved) and current != saved


def _is_gate_ok(check) -> bool:
    return bool(check.ok)


def _has_verified_flag(host) -> bool:
    return bool(host._verified)


def _is_unchanged_cursor(cursor: dict, count: int, sigs) -> bool:
    return (
        cursor["bootstrapped"]
        and count == cursor["dom_count"]
        and sigs.tail_sig
        and sigs.tail_sig == cursor["tail_sig"]
        and sigs.head_sig == cursor["head_sig"]
    )


def _should_backfill(host, cursor: dict) -> bool:
    full_scan_complete = bool(cursor.get("full_scan_complete"))
    auto = bool(host._settings.get("auto_backfill", True))
    return (auto and not full_scan_complete and not host._backfill_pending) or host._force_backfill


def _is_bootstrap(cursor: dict) -> bool:
    return not cursor["bootstrapped"]


def _has_new_messages(result) -> bool:
    return bool(result.added)


def _is_sync_ok(result) -> bool:
    return bool(result.ok)


def _is_throttled(host) -> bool:
    return bool(host._throttled)
