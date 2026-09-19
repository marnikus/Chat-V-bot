"""Compatibility shim — the archive repository lives in stores/history_repo.py."""

from backend.legacy_shims import deprecated_module

deprecated_module("history_repo", "stores.history_repo")

from stores.history_repo import HistoryRepo, align_batch  # noqa: F401

__all__ = ["HistoryRepo", "align_batch"]
