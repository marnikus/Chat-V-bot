"""stores — pure I/O: one file per store, atomic saves, no business logic.

Dependency rule: a store never imports a service or a bridge. Config-file
stores are synchronous; the SQLite stores (history_db, history_repo,
media_store) are await-only.
"""

from stores.jsonio import load_json, save_json, config_dir_for

__all__ = ["load_json", "save_json", "config_dir_for"]
