"""Memory layer tests: transitions, counts, cooldown, CSV round-trip."""
import sqlite3

import pytest

from chatflow.core.models import UserRow
from chatflow.memory.csv_io import export_users, import_users
from chatflow.memory.db import Database
from chatflow.memory.repo_status import StatusRepo
from chatflow.memory.repo_users import UserRepo

FEMALE = frozenset({"female-avatar", "anonymous-badge"})
MALE = frozenset({"male-avatar"})


def make(tmp_path):
    db = Database(tmp_path / "t.db")
    return db, UserRepo(db), StatusRepo(db)


def rows():
    return [UserRow("Lizalo4ka", "FEMALE", False, True, FEMALE),
            UserRow("Dr0che", "MALE", False, True, MALE),
            UserRow("МилаяКися", "FEMALE", True, False,
                    frozenset({"female-avatar", "registered-badge"}))]


def verdicts(all_pass=False):
    if all_pass:
        return {r.nickname: (True, None) for r in rows()}
    return {"Lizalo4ka": (True, None),
            "Dr0che": (False, "CLASS_INCLUDES:female-avatar"),
            "МилаяКися": (False, "CLASS_EXCLUDES:registered-badge")}


def test_discovery_transitions(tmp_path):
    db, users, status = make(tmp_path)
    stats = status.upsert_batch(rows(), verdicts())
    assert stats == {"inserted": 3, "queued": 1, "skipped": 2}
    c = users.counts()
    assert c["total"] == 3 and c["queued"] == 1 and c["skipped"] == 2
    assert users.get("Lizalo4ka").status == "QUEUED"
    assert users.get("Dr0che").skip_reason == "CLASS_INCLUDES:female-avatar"
    # re-scan: no duplicates, statuses preserved, last_seen refreshed
    stats2 = status.upsert_batch(rows(), verdicts())
    assert stats2["inserted"] == 0 and users.counts()["total"] == 3
    db.close()


def test_messaged_never_regresses(tmp_path):
    db, users, status = make(tmp_path)
    status.upsert_batch(rows(), verdicts())
    assert status.mark_messaged("Lizalo4ka")
    status.upsert_batch(rows(), verdicts())  # still QUEUED verdict
    u = users.get("Lizalo4ka")
    assert u.status == "MESSAGED" and u.message_count == 1 and u.messaged_at
    assert status.mark_messaged("Dr0che") is False  # was SKIPPED
    db.close()


def test_cooldown_requeue(tmp_path):
    db, users, status = make(tmp_path)
    status.upsert_batch(rows(), verdicts())
    status.mark_messaged("Lizalo4ka")
    assert status.requeue_due(30) == 0  # too recent
    db.conn.execute("UPDATE users SET messaged_at='2020-01-01T00:00:00' "
                    "WHERE nickname='Lizalo4ka'")
    assert status.requeue_due(30) == 1
    assert users.get("Lizalo4ka").status == "QUEUED"
    assert "Lizalo4ka" in users.queued_nicks()
    db.close()


def test_reset_and_delete(tmp_path):
    db, users, status = make(tmp_path)
    status.upsert_batch(rows(), verdicts())
    assert users.reset_all() == 3
    assert users.counts() == {"total": 3, "new": 3, "queued": 0,
                              "messaged": 0, "skipped": 0}
    uid = users.get("Dr0che").id
    assert users.delete(uid) and users.counts()["total"] == 2
    db.close()


def test_csv_round_trip(tmp_path):
    db, users, status = make(tmp_path)
    status.upsert_batch(rows(), verdicts())
    status.mark_messaged("Lizalo4ka")
    path = str(tmp_path / "out.csv")
    assert export_users(users, path) == 3
    db2, users2, status2 = make(tmp_path)
    res = import_users(status2, path)
    assert res["imported"] == 3 and res["errors"] == 0
    assert users2.get("Lizalo4ka").status == "MESSAGED"
    assert users2.get("Dr0che").status == "SKIPPED"
    db.close(); db2.close()


def test_case_insensitive_nickname(tmp_path):
    db, users, status = make(tmp_path)
    status.upsert_batch([UserRow("Lizalo4ka", "FEMALE", False, True, FEMALE)],
                        {"Lizalo4ka": (True, None)})
    status.upsert_batch([UserRow("lIZALO4ka", "FEMALE", False, True, FEMALE)],
                        {"lIZALO4ka": (True, None)})
    assert users.counts()["total"] == 1
    db.close()


def test_db_wal_mode(tmp_path):
    db, *_ = make(tmp_path)
    mode = sqlite3.connect(str(db.path)).execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    db.close()
