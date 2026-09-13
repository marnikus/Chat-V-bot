"""Shared constants for the deletion family.

Pure data, no imports: sits at the top of the dependency order.
"""

#: SQLite file group members removed on delete. `SUFFIXES` in db_service
#: stays (\"\",\"-wal\",\"-shm\") for size/compat; deletion also best-effort
#: removes a rollback-journal sibling when present.
DB_GROUP_SUFFIXES = ("", "-wal", "-shm", "-journal")

SUPPORTED_BOUNDARY = (
    "active folder scan + active file + victim-directory scan + "
    "remembered in-root .db paths (deduped). Worlds outside this boundary "
    "are NOT scanned and NOT protected."
)
