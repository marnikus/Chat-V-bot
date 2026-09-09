"""Compatibility shim — the archive repository lives in stores/history_repo.py."""

from stores.history_repo import HistoryRepo, align_batch  # noqa: F401

__all__ = ["HistoryRepo", "align_batch"]
